"""Sincronizacao do estoque do ERP para o `estoque_local` (o agente continua lendo o banco).

`FonteEstoqueErp` e a porta que um ERP implementa: ler o inventario inteiro de uma unidade (uma
vez por rodada) e aplicar o filtro de cada loja que aponta para ela. `SincronizarEstoqueErp` so
substitui o estoque quando a leitura inteira deu certo; qualquer falha mantem o ultimo estoque
bom e grava o motivo em `ultimo_status`/`ultimo_relatorio` da conexao.

Formato do relatorio (JSON gravado na conexao):
- ok: `lidos`, `importados`, `outra_loja`, `descartados`, `por_motivo`, `duracao_s`;
- erro: `erro` (mensagem), `duracao_s` e, conforme o caso, `retentavel`, `codigo` e os contadores.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.config.modelos import LinhaEstoqueLocal
from app.application.config.portas import RepositorioConexaoErp, RepositorioEstoqueLocal
from app.application.estoque import EstoqueIndisponivel
from app.application.relogio import RelogioPort
from app.domain.conexao_erp import ConexaoErp, sincronizacao_vencida
from app.domain.oferta import MotivoDescarte

log = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_ERRO = "erro"


class ErpNaoConfigurado(Exception):
    """O servidor nao tem a chave do ERP (`MERCADOPHONE_API_KEY`): a integracao esta desligada."""


class ConexaoErpNaoConfigurada(Exception):
    """A loja ainda nao configurou a conexao com o ERP."""


@dataclass(frozen=True, slots=True)
class LeituraErp:
    """Estoque de UMA loja, ja mapeado, mais o que ficou de fora e por que."""

    linhas: tuple[LinhaEstoqueLocal, ...]
    lidos: int
    """Itens que o ERP devolveu para a unidade (de todas as lojas)."""
    outra_loja: int = 0
    descartes: Mapping[MotivoDescarte, int] = field(default_factory=dict)


class LeituraUnidade(Protocol):
    """Inventario inteiro de uma unidade, lido uma vez; cada loja aplica o seu filtro."""

    def para_loja(self, filtro_loja: str | None) -> LeituraErp: ...


class FonteEstoqueErp(Protocol):
    async def ler_unidade(self, system_unit_id: int) -> LeituraUnidade:
        """Le todas as paginas. Levanta `EstoqueIndisponivel` se qualquer uma falhar."""
        ...

    async def ler(self, conexao: ConexaoErp) -> LeituraErp:
        """Atalho: `ler_unidade` da conexao + o filtro dela."""
        ...

    async def unidade_existe(self, system_unit_id: int) -> bool:
        """A unidade esta entre as da chave? Levanta `EstoqueIndisponivel` se o ERP falhar."""
        ...


@dataclass(frozen=True, slots=True)
class ResultadoSincronizacao:
    loja_id: UUID
    status: str
    relatorio: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResultadoTeste:
    ok: bool
    mensagem: str


Acao = Callable[[], Awaitable[None]]


async def _nada() -> None:
    return None


class _LeituraRejeitada(Exception):
    """Leitura que deu certo mas nao deve substituir o estoque (vazia, filtro errado)."""

    def __init__(self, mensagem: str, relatorio: dict[str, Any]) -> None:
        super().__init__(mensagem)
        self.relatorio = relatorio


class SincronizarEstoqueErp:
    """Sincroniza uma loja (`sincronizar`) ou todas as vencidas (`sincronizar_vencidas`).

    `commit`/`rollback` fecham a transacao de cada loja: o estoque novo e o status entram juntos;
    na falha, desfaz a tentativa e confirma so o status de erro.
    """

    def __init__(
        self,
        conexoes: RepositorioConexaoErp,
        estoque: RepositorioEstoqueLocal,
        fonte: FonteEstoqueErp,
        *,
        relogio: RelogioPort,
        agora: Callable[[], datetime],
        commit: Acao | None = None,
        rollback: Acao | None = None,
    ) -> None:
        self._conexoes = conexoes
        self._estoque = estoque
        self._fonte = fonte
        self._relogio = relogio
        self._agora = agora
        self._commit = commit or _nada
        self._rollback = rollback or _nada

    # --- testar -------------------------------------------------------------------------------

    async def testar(self, conexao: ConexaoErp) -> ResultadoTeste:
        """A unidade da conexao existe na chave? Nao grava nada."""
        unidade = conexao.system_unit_id
        try:
            existe = await self._fonte.unidade_existe(unidade)
        except EstoqueIndisponivel as exc:
            return ResultadoTeste(False, _mensagem_de_falha(exc))
        if existe:
            return ResultadoTeste(True, f"Conexão ok: a unidade {unidade} existe na chave do ERP.")
        return ResultadoTeste(False, f"A unidade {unidade} não existe na chave do ERP.")

    # --- sincronizar --------------------------------------------------------------------------

    async def sincronizar(self, conexao: ConexaoErp) -> ResultadoSincronizacao:
        """Sincroniza agora (nao exige `ativo`; ele so vale para o cron)."""
        inicio, em = self._relogio.agora(), self._agora()
        try:
            unidade = await self._fonte.ler_unidade(conexao.system_unit_id)
        except Exception as exc:
            return await self._falhar(conexao, exc, inicio, em)
        return await self._aplicar(conexao, unidade, inicio, em)

    async def sincronizar_vencidas(self) -> list[ResultadoSincronizacao]:
        """Rodada do cron: as conexoes ativas cujo intervalo venceu, uma leitura por unidade."""
        agora = self._agora()
        por_unidade: dict[int, list[ConexaoErp]] = {}
        for conexao in await self._conexoes.listar_ativas():
            if sincronizacao_vencida(conexao, agora):
                por_unidade.setdefault(conexao.system_unit_id, []).append(conexao)
        resultados: list[ResultadoSincronizacao] = []
        for unidade_id, conexoes in por_unidade.items():
            inicio, em = self._relogio.agora(), self._agora()
            try:
                unidade = await self._fonte.ler_unidade(unidade_id)
            except Exception as exc:
                for conexao in conexoes:
                    resultados.append(await self._falhar(conexao, exc, inicio, em))
                continue
            for conexao in conexoes:
                resultados.append(await self._aplicar(conexao, unidade, inicio, em))
        return resultados

    # --- internos -----------------------------------------------------------------------------

    async def _aplicar(
        self, conexao: ConexaoErp, unidade: LeituraUnidade, inicio: float, em: datetime
    ) -> ResultadoSincronizacao:
        try:
            linhas, relatorio = self._preparar(unidade.para_loja(conexao.filtro_loja), inicio)
            await self._estoque.substituir(conexao.loja_id, linhas)
            await self._conexoes.registrar_sincronizacao(
                conexao.loja_id, em=em, status=STATUS_OK, relatorio=relatorio
            )
            await self._commit()
        except Exception as exc:
            return await self._falhar(conexao, exc, inicio, em)
        return ResultadoSincronizacao(conexao.loja_id, STATUS_OK, relatorio)

    def _preparar(
        self, leitura: LeituraErp, inicio: float
    ) -> tuple[list[LinhaEstoqueLocal], dict[str, Any]]:
        linhas, duplicados = _sem_duplicados(leitura.linhas)
        por_motivo: Counter[MotivoDescarte] = Counter(leitura.descartes)
        if duplicados:
            por_motivo[MotivoDescarte.SKU_DUPLICADO] += duplicados
        relatorio: dict[str, Any] = {
            "lidos": leitura.lidos,
            "importados": len(linhas),
            "outra_loja": leitura.outra_loja,
            "descartados": sum(por_motivo.values()),
            "por_motivo": {motivo.value: n for motivo, n in por_motivo.items()},
            "duracao_s": self._duracao(inicio),
        }
        if leitura.lidos == 0:
            raise _LeituraRejeitada(
                "O ERP não devolveu nenhum item para a unidade; estoque anterior mantido.",
                relatorio,
            )
        if not linhas:
            raise _LeituraRejeitada(
                "Nenhum item da leitura é desta loja ou ofertável (confira o filtro da loja); "
                "estoque anterior mantido.",
                relatorio,
            )
        return linhas, relatorio

    async def _falhar(
        self, conexao: ConexaoErp, exc: Exception, inicio: float, em: datetime
    ) -> ResultadoSincronizacao:
        relatorio: dict[str, Any]
        if isinstance(exc, _LeituraRejeitada):
            relatorio = {**exc.relatorio, "erro": str(exc)}
        elif isinstance(exc, EstoqueIndisponivel):
            relatorio = {
                "erro": _mensagem_de_falha(exc),
                "retentavel": exc.retentavel,
                "duracao_s": self._duracao(inicio),
            }
            codigo = getattr(exc, "codigo", None)
            if codigo is not None:
                relatorio["codigo"] = str(codigo)
        else:
            log.exception("erro inesperado ao sincronizar a loja %s", conexao.loja_id)
            relatorio = {
                "erro": "Erro inesperado ao sincronizar; estoque anterior mantido.",
                "duracao_s": self._duracao(inicio),
            }
        # desfaz o que a tentativa tenha feito (o estoque so troca no caminho feliz) e confirma
        # apenas o status de erro
        await self._rollback()
        await self._conexoes.registrar_sincronizacao(
            conexao.loja_id, em=em, status=STATUS_ERRO, relatorio=relatorio
        )
        await self._commit()
        return ResultadoSincronizacao(conexao.loja_id, STATUS_ERRO, relatorio)

    def _duracao(self, inicio: float) -> float:
        return round(self._relogio.agora() - inicio, 3)


def _sem_duplicados(
    linhas: Sequence[LinhaEstoqueLocal],
) -> tuple[list[LinhaEstoqueLocal], int]:
    """Mantem a primeira linha de cada SKU (a constraint `loja_sku` nao aceita repeticao)."""
    vistos: set[str] = set()
    unicas: list[LinhaEstoqueLocal] = []
    for linha in linhas:
        if linha.sku in vistos:
            continue
        vistos.add(linha.sku)
        unicas.append(linha)
    return unicas, len(linhas) - len(unicas)


def _mensagem_de_falha(exc: EstoqueIndisponivel) -> str:
    texto = str(exc) or type(exc).__name__
    if exc.retentavel:
        return f"ERP indisponível no momento: {texto}"
    return f"O ERP recusou a conexão: {texto}"
