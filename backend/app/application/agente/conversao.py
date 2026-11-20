"""Conversao da ficha (dados parciais) para as entradas COMPLETAS do calculo.

Junta os vocabularios paralelos `ficha.TipoPagamento` x formas de `pagamento.py`. So converte
fichas sem pendencias; qualquer falta levanta `FichaIncompleta` (a trava ja deveria ter
barrado antes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.ficha import Ficha, PagamentoInformado, TipoPagamento, UsadoInformado, pendencias
from app.domain.pagamento import Credito, Debito, EntradaMaisCredito, FormaPagamento, PixDinheiro
from app.domain.troca import CondicaoUsado
from app.domain.valores import Capacidade, ModeloAparelho


class FichaIncompleta(ValueError):
    """A ficha ainda tem pendencias; nao da para montar as entradas de calculo."""


@dataclass(frozen=True, slots=True)
class UsadoParaAvaliar:
    modelo: ModeloAparelho
    capacidade: Capacidade
    condicao: CondicaoUsado


@dataclass(frozen=True, slots=True)
class EntradasDeCalculo:
    sku: str
    data_compra: date
    usado: UsadoParaAvaliar | None
    """None quando o cliente nao tem troca."""
    forma: FormaPagamento


def _usado(u: UsadoInformado) -> UsadoParaAvaliar:
    if (
        u.modelo is None
        or u.capacidade is None
        or u.tela_danificada is None
        or u.traseira_danificada is None
        or u.carcaca_marcada is None
        or u.bateria_pct is None
        or u.camera_ok is None
        or u.outros_defeitos is None
        or u.peca_trocada is None
    ):
        raise FichaIncompleta("dados do aparelho usado incompletos")
    condicao = CondicaoUsado(
        tela_danificada=u.tela_danificada,
        traseira_danificada=u.traseira_danificada,
        carcaca_marcada=u.carcaca_marcada,
        bateria_pct=u.bateria_pct,
        camera_ok=u.camera_ok,
        outros_defeitos=u.outros_defeitos,
        peca_trocada=u.peca_trocada,
    )
    return UsadoParaAvaliar(u.modelo, u.capacidade, condicao)


def _forma(p: PagamentoInformado) -> FormaPagamento:
    tipo, parcelas, bandeira, entrada = p.tipo, p.parcelas, p.bandeira, p.entrada
    if tipo is TipoPagamento.PIX:
        return PixDinheiro()
    if tipo is TipoPagamento.DEBITO and bandeira is not None:
        return Debito(bandeira)
    if tipo is TipoPagamento.CREDITO and parcelas is not None and bandeira is not None:
        return Credito(parcelas, bandeira)
    if (
        tipo is TipoPagamento.ENTRADA_MAIS_CREDITO
        and parcelas is not None
        and bandeira is not None
        and entrada is not None
    ):
        return EntradaMaisCredito(entrada, parcelas, bandeira)
    raise FichaIncompleta("forma de pagamento incompleta")


def entradas_de_calculo(ficha: Ficha) -> EntradasDeCalculo:
    """Converte uma ficha SEM pendencias; `FichaIncompleta` caso contrario."""
    faltas = pendencias(ficha)
    if faltas:
        raise FichaIncompleta("ficha com pendencias: " + ", ".join(p.name for p in faltas))
    sku = ficha.interesse.sku_estoque_confirmado
    data = ficha.data_prevista_compra
    if sku is None or data is None:  # inalcancavel sem pendencias; satisfaz o tipo
        raise FichaIncompleta("sku ou data ausentes")
    return EntradasDeCalculo(
        sku=sku,
        data_compra=data,
        usado=_usado(ficha.usado) if ficha.tem_troca else None,
        forma=_forma(ficha.pagamento),
    )
