"""Smoke do Mercado Phone: SO LEITURA, para rodar a mao com a chave do `.env`.

    cd backend
    uv run python scripts/mercadophone_smoke.py
    uv run python scripts/mercadophone_smoke.py --unidade 4 \\
        --filtro-loja "Loja A" --filtro-loja "Loja B"
    uv run python scripts/mercadophone_smoke.py --filtro-loja "Loja A" --conferir 3

O que faz: `list_my_stores` (as unidades da chave), le o inventario inteiro da unidade (uma vez)
e, para cada `--filtro-loja`, imprime quantos itens foram lidos, importados, de outra loja e
descartados por motivo, mais a duracao. Com `--conferir N`, confere ao vivo os N primeiros itens
importados (a mesma conferencia que o agente usa antes da proposta).

Nunca escreve nada no ERP: so usa ferramentas `list_*` (o teste do script garante). Nao grava nada
no banco. A chave nunca e impressa. Sem chave: mensagem clara e codigo de saida 2.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.outbound.mercadophone.cliente import (  # noqa: E402
    ClienteMercadoPhone,
    ErroMercadoPhone,
)
from app.adapters.outbound.mercadophone.conferencia import (  # noqa: E402
    ConferenciaItemMercadoPhone,
)
from app.adapters.outbound.mercadophone.fonte import FonteEstoqueMercadoPhone  # noqa: E402
from app.application.estoque_ao_vivo import SituacaoAoVivo  # noqa: E402
from app.application.estoque_erp import LeituraErp  # noqa: E402
from app.domain.conexao_erp import ConexaoErp  # noqa: E402
from app.domain.estoque import Condicao, ItemEstoque  # noqa: E402
from app.infra.mercadophone import (  # noqa: E402
    MercadoPhoneNaoConfigurado,
    get_cliente_mercadophone,
)

MENSAGEM_SEM_CHAVE = (
    "MERCADOPHONE_API_KEY nao configurada. Defina a chave no .env (raiz do repo) ou no ambiente "
    "e rode de novo. Este smoke so le dados (nao escreve nada no ERP)."
)
SEM_FILTRO = "(sem filtro)"

Saida = Callable[[str], None]


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke do Mercado Phone (so leitura): unidades, leitura do estoque e descartes."
    )
    parser.add_argument(
        "--unidade",
        type=int,
        default=None,
        help="system_unit_id a ler (padrao: a primeira de list_my_stores)",
    )
    parser.add_argument(
        "--filtro-loja",
        action="append",
        default=[],
        metavar="TEXTO",
        help="filtro de loja (campo obs antes de ' | '); repetivel; sem ele, nao filtra",
    )
    parser.add_argument(
        "--conferir",
        type=int,
        default=0,
        metavar="N",
        help="confere ao vivo N itens importados (so leitura, nada e gravado)",
    )
    return parser


def _id_da_loja(loja: Any) -> int | None:
    if not isinstance(loja, Mapping):
        return None
    valor = loja.get("system_unit_id")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


class _ConexaoUnica:
    """`RepositorioConexaoErp` de mentira, so para a conferencia ao vivo (nao grava nada)."""

    def __init__(self, conexao: ConexaoErp) -> None:
        self._conexao = conexao

    async def obter(self, loja_id: UUID) -> ConexaoErp | None:
        return self._conexao


def _item_de_linha(linha: Any) -> ItemEstoque:
    return ItemEstoque(
        sku=linha.sku,
        modelo=linha.modelo,
        capacidade=linha.capacidade,
        cor=linha.cor or None,
        condicao=linha.condicao,
        preco_pix=linha.preco_pix,
        quantidade=linha.quantidade,
        bateria_pct=linha.bateria_pct if linha.condicao is Condicao.SEMINOVO else None,
    )


def _imprimir_resumo(saida: Saida, rotulo: str, leitura: LeituraErp, duracao_s: float) -> None:
    saida(f"\nFiltro de loja: {rotulo}")
    saida(f"  lidos: {leitura.lidos}")
    saida(f"  importados: {len(leitura.linhas)}")
    saida(f"  outra loja: {leitura.outra_loja}")
    descartes = sorted(leitura.descartes.items(), key=lambda par: (-par[1], par[0].value))
    total = sum(n for _, n in descartes)
    saida(f"  descartados: {total}")
    for motivo, quantidade in descartes:
        saida(f"    {motivo.value}: {quantidade}")
    saida(f"  duracao do mapeamento: {duracao_s:.2f} s")


async def _conferir(
    saida: Saida,
    cliente: ClienteMercadoPhone,
    unidade: int,
    filtro: str | None,
    leitura: LeituraErp,
    quantidade: int,
) -> None:
    saida(f"\nConferencia ao vivo ({quantidade} itens, filtro {filtro or SEM_FILTRO}):")
    if not leitura.linhas:
        saida("  nenhum item importado para conferir.")
        return
    loja_id = uuid4()
    conexao = ConexaoErp(loja_id=loja_id, system_unit_id=unidade, filtro_loja=filtro, ativo=True)
    conferencia = ConferenciaItemMercadoPhone(_ConexaoUnica(conexao), lambda: cliente)
    for posicao, linha in enumerate(leitura.linhas[:quantidade], start=1):
        inicio = time.perf_counter()
        resultado = await conferencia.conferir(loja_id, _item_de_linha(linha))
        duracao = time.perf_counter() - inicio
        situacao = resultado.situacao
        detalhe = situacao.value
        if situacao is SituacaoAoVivo.DISPONIVEL and resultado.linha is not None:
            igual = resultado.linha.preco_pix == linha.preco_pix
            detalhe += ", preco igual ao lido" if igual else ", PRECO MUDOU"
        saida(f"  {posicao}. sku {linha.sku}: {detalhe} ({duracao:.2f} s)")


async def executar(
    cliente: ClienteMercadoPhone,
    *,
    unidade: int | None,
    filtros: Sequence[str],
    conferir: int,
    saida: Saida = print,
    erro: Saida | None = None,
) -> int:
    """Roda o smoke. 0 = ok, 1 = falha (unidade inexistente, ERP fora...)."""
    erro = erro or (lambda texto: print(texto, file=sys.stderr))
    lojas_resposta = await cliente.chamar("list_my_stores", {})
    lojas = lojas_resposta.get("stores", lojas_resposta.get("items"))
    lojas = lojas if isinstance(lojas, list) else []
    ids = [i for i in (_id_da_loja(loja) for loja in lojas) if i is not None]
    if not ids:
        erro("A chave nao tem nenhuma unidade (list_my_stores veio vazio).")
        return 1

    saida(f"Unidades da chave: {len(ids)}")
    for loja in lojas:
        identificador = _id_da_loja(loja)
        nome = loja.get("name", "") if isinstance(loja, Mapping) else ""
        saida(f"  {identificador}: {nome}")

    escolhida = unidade if unidade is not None else ids[0]
    if escolhida not in ids:
        erro(f"A unidade {escolhida} nao esta entre as da chave: {ids}")
        return 1
    saida(f"\nUnidade {escolhida}: lendo o inventario inteiro (so leitura)...")

    inicio = time.perf_counter()
    inventario = await FonteEstoqueMercadoPhone(cliente).ler_unidade(escolhida)
    saida(f"Leitura completa em {time.perf_counter() - inicio:.1f} s.")

    primeira: tuple[str | None, LeituraErp] | None = None
    for filtro in filtros or [None]:
        inicio = time.perf_counter()
        leitura = inventario.para_loja(filtro)
        _imprimir_resumo(saida, filtro or SEM_FILTRO, leitura, time.perf_counter() - inicio)
        if primeira is None:
            primeira = (filtro, leitura)

    if conferir > 0 and primeira is not None:
        await _conferir(saida, cliente, escolhida, primeira[0], primeira[1], conferir)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    cliente_factory: Callable[[], ClienteMercadoPhone] = get_cliente_mercadophone,
) -> int:
    args = montar_parser().parse_args(argv)
    try:
        cliente = cliente_factory()
    except MercadoPhoneNaoConfigurado:
        print(MENSAGEM_SEM_CHAVE, file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            executar(
                cliente,
                unidade=args.unidade,
                filtros=args.filtro_loja,
                conferir=args.conferir,
            )
        )
    except ErroMercadoPhone as exc:
        print(f"Falha ao falar com o Mercado Phone: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
