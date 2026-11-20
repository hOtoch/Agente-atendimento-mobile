"""Montagem da proposta: unico lugar onde valores saem do dominio para o LLM.

So e chamada com a ficha completa (a trava fica em `ferramentas.calcular_proposta`). Devolve
um JSON curto com tudo formatado em pt-BR e os rotulos que separam desconto negociado de
oportunidade unica.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.application.agente.contexto import ContextoFerramentas, ErroFerramenta
from app.application.agente.conversao import entradas_de_calculo
from app.application.agente.estado import EstadoAtendimento
from app.domain.desconto import desconto_total, oportunidade_unica
from app.domain.pagamento import (
    Credito,
    Debito,
    EntradaMaisCredito,
    EntradaNaoAceita,
    FormaPagamento,
    PagamentoError,
    ParcelasAcimaDoMaximo,
    ParcelasInvalidas,
    PixDinheiro,
    Proposta,
    TaxaNaoCadastrada,
    calcular_pagamento,
    simular_opcoes,
)
from app.domain.troca import AvaliacaoNaLoja, MotivoLoja, ValorTroca, avaliar_troca
from app.domain.valores import Bandeira, Dinheiro

FRASE_OBRIGATORIA = "pré-avaliação, valor final confirmado na loja com o aparelho em mãos"

_MOTIVOS_LOJA: dict[MotivoLoja, str] = {
    MotivoLoja.SEM_VALOR_WHATSAPP: "esse tipo de problema só é avaliado presencialmente",
    MotivoLoja.OUTRO_DEFEITO: "defeito que precisa ser avaliado com o aparelho em mãos",
    MotivoLoja.PECA_TROCADA: "peça já trocada precisa ser avaliada com o aparelho em mãos",
    MotivoLoja.OUTRA_MARCA: "aparelho de outra marca é avaliado na loja",
    MotivoLoja.MODELO_FORA_DA_TABELA: "modelo fora da tabela de troca, avaliado na loja",
    MotivoLoja.VALOR_NAO_POSITIVO: "o aparelho precisa ser avaliado na loja",
    MotivoLoja.CAPACIDADE_ABAIXO_DA_TABELA: "capacidade fora da tabela de troca, avaliada na loja",
}
_PROBLEMAS = {
    "tela": "tela danificada",
    "traseira": "vidro traseiro danificado",
    "carcaca": "carcaça marcada",
    "bateria": "bateria abaixo do limite",
}
_AVISO_TROCA_COBRE = (
    "O valor da troca cobre o valor do aparelho: não há saldo a pagar no cartão. "
    "Confirme o restante com o vendedor."
)


def _pct(valor: Decimal) -> str:
    return f"{valor:.2f}".replace(".", ",") + "%"


def _bandeira(b: Bandeira) -> str:
    return b.value.title()


def _rotulo(forma: FormaPagamento) -> str:
    match forma:
        case PixDinheiro():
            return "Pix ou dinheiro à vista"
        case Debito(bandeira=b):
            return f"Débito {_bandeira(b)}"
        case Credito(parcelas=n, bandeira=b):
            return f"Cartão de crédito em {n}x {_bandeira(b)}"
        case EntradaMaisCredito(entrada=e, parcelas=n, bandeira=b):
            return f"Entrada de {e} + cartão em {n}x {_bandeira(b)}"


def _descrever(p: Proposta) -> dict[str, Any]:
    texto: dict[str, Any] = {"rotulo": _rotulo(p.forma)}
    if isinstance(p.forma, PixDinheiro):
        texto["valor_a_vista"] = str(p.total_pago)
        return texto
    texto["parcelas"] = p.parcelas
    texto["valor_parcela"] = str(p.valor_parcela)
    texto["total_pago"] = str(p.total_pago)
    texto["taxa"] = _pct(p.taxa_aplicada_pct)
    if isinstance(p.forma, EntradaMaisCredito):
        texto["entrada"] = str(p.entrada)
    return texto


def _prioridade(p: Proposta, maximo: int) -> int:
    if isinstance(p.forma, PixDinheiro):
        return 0
    if p.parcelas == maximo:
        return 1
    return {10: 2, 12: 3, 1: 4}.get(p.parcelas, 5)


def _erro_pagamento(exc: PagamentoError) -> ErroFerramenta:
    if isinstance(exc, ParcelasAcimaDoMaximo):
        return ErroFerramenta(
            f"A loja parcela em no máximo {exc.maximo}x. Peça ao cliente outra quantidade."
        )
    if isinstance(exc, ParcelasInvalidas):
        return ErroFerramenta("Quantidade de parcelas inválida. Peça ao cliente outra quantidade.")
    if isinstance(exc, EntradaNaoAceita):
        return ErroFerramenta("A loja não aceita entrada mais parcelas no cartão.")
    if isinstance(exc, TaxaNaoCadastrada):
        return ErroFerramenta(
            "A loja não tem a taxa dessa forma de pagamento cadastrada. Chame o vendedor."
        )
    return ErroFerramenta("Não foi possível calcular essa forma de pagamento. Chame o vendedor.")


async def montar_proposta(ctx: ContextoFerramentas, estado: EstadoAtendimento) -> dict[str, Any]:
    """Calcula a proposta da ficha COMPLETA. Levanta `ErroFerramenta`/`EstoqueIndisponivel`."""
    entradas = entradas_de_calculo(estado.ficha)
    preco_cfg = await ctx.config.obter_preco(ctx.loja_id)
    if preco_cfg is None:
        raise ErroFerramenta("A loja ainda não definiu as regras de preço. Chame o vendedor.")
    taxas = await ctx.config.obter_taxas(ctx.loja_id)
    tabela = await ctx.config.obter_troca(ctx.loja_id)

    item = await ctx.estoque.obter(ctx.loja_id, entradas.sku)
    if item is None or not item.disponivel:
        raise ErroFerramenta(
            "O item confirmado não está mais disponível. Consulte o estoque de novo "
            "e confirme outra opção com o cliente."
        )

    # troca
    troca = Dinheiro.zero()
    troca_info: dict[str, Any]
    if entradas.usado is None:
        troca_info = {"status": "sem_troca"}
    else:
        u = entradas.usado
        avaliacao = avaliar_troca(tabela, u.modelo, u.capacidade, u.condicao)
        if isinstance(avaliacao, ValorTroca):
            troca = avaliacao.valor
            troca_info = {
                "status": "avaliada",
                "valor": str(avaliacao.valor),
                "descontos_aplicados": [
                    {"problema": _PROBLEMAS.get(nome, nome), "desconto": str(d)}
                    for nome, d in avaliacao.descontos_aplicados
                ],
            }
        else:
            assert isinstance(avaliacao, AvaliacaoNaLoja)
            troca_info = {
                "status": "avaliacao_na_loja",
                "motivo": _MOTIVOS_LOJA[avaliacao.motivo],
                "observacao": (
                    "O valor do aparelho usado só sai na loja, com ele em mãos. "
                    "Esta proposta foi calculada SEM a troca."
                ),
            }

    # desconto: negociado (degraus liberados) e oportunidade unica ficam separados
    regras, politica, regra_op = preco_cfg.regras, preco_cfg.politica, preco_cfg.oportunidade
    oportunidade = oportunidade_unica(entradas.data_compra, ctx.hoje, regra_op)
    desconto = desconto_total(politica, estado.desconto, oportunidade, regra_op)
    negociado = estado.desconto.liberado
    observacao = (
        "Desconto negociado = liberado na conversa (limitado ao teto da loja). "
        "Oportunidade única = bônus por antecipar a compra"
        + (", contado dentro do teto." if regra_op.conta_no_teto else ", somado por fora do teto.")
    )

    try:
        escolhida = calcular_pagamento(
            item.preco_pix, desconto, troca, entradas.forma, regras, taxas
        )
    except PagamentoError as exc:
        raise _erro_pagamento(exc) from exc

    bandeira = getattr(entradas.forma, "bandeira", Bandeira.MASTERCARD)
    try:
        opcoes = simular_opcoes(item.preco_pix, desconto, troca, regras, taxas, bandeira)
    except PagamentoError:
        opcoes = []
    alternativas = sorted(
        (o for o in opcoes if o.forma != escolhida.forma),
        key=lambda o: _prioridade(o, regras.max_parcelas),
    )[:3]

    conteudo: dict[str, Any] = {
        "bloqueado": False,
        "aparelho": {
            "sku": item.sku,
            "modelo": item.modelo.nome,
            "capacidade": str(item.capacidade),
            "cor": item.cor,
            "condicao": item.condicao.value,
        },
        "preco_aparelho": str(item.preco_pix),
        "troca": troca_info,
        "desconto": {
            "negociado": str(negociado),
            "oportunidade_unica": None if oportunidade is None else str(desconto - negociado),
            "total": str(desconto),
            "observacao": observacao,
        },
        "base_parcelamento": str(escolhida.base),
        "forma_escolhida": _descrever(escolhida),
        "alternativas": [_descrever(a) for a in alternativas],
        "aviso": _AVISO_TROCA_COBRE if escolhida.aviso is not None else None,
        "pode_negociar_mais": negociado < politica.teto,
        "frase_obrigatoria": FRASE_OBRIGATORIA,
    }
    if isinstance(entradas.forma, EntradaMaisCredito):
        conteudo["observacao_alternativas"] = "As alternativas foram calculadas sem entrada."
    return conteudo
