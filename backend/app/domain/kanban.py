"""Maquina de etapas do kanban.

A etapa e derivada de fatos booleanos calculados pela camada de aplicacao; o
LLM nunca decide a etapa. Funcoes puras, sem IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Etapa(StrEnum):
    """Etapa do lead no kanban. O valor (str) e gravado em `leads.etapa`."""

    NOVO_CONTATO = "novo_contato"
    INTERESSE_IDENTIFICADO = "interesse_identificado"
    INTERESSE_QUALIFICADO = "interesse_qualificado"
    COM_O_VENDEDOR = "com_o_vendedor"
    VENDA_FECHADA = "venda_fechada"

    @property
    def ordem(self) -> int:
        """Posicao da etapa no funil (0 = inicio)."""
        return _ORDEM[self]

    @property
    def nome_exibicao(self) -> str:
        """Nome em pt-BR para o painel."""
        return _NOMES[self]


_ORDEM: dict[Etapa, int] = {etapa: i for i, etapa in enumerate(Etapa)}

_NOMES: dict[Etapa, str] = {
    Etapa.NOVO_CONTATO: "Novo contato",
    Etapa.INTERESSE_IDENTIFICADO: "Interesse identificado",
    Etapa.INTERESSE_QUALIFICADO: "Interesse qualificado",
    Etapa.COM_O_VENDEDOR: "Com o vendedor",
    Etapa.VENDA_FECHADA: "Venda fechada",
}


class Ator(StrEnum):
    """Quem provoca uma mudanca de etapa."""

    IA = "ia"
    VENDEDOR = "vendedor"
    SISTEMA = "sistema"


@dataclass(frozen=True, slots=True)
class FatosDoLead:
    """Fatos ja calculados pela aplicacao. `qualificado` = pode_passar_preco."""

    aparelho_definido: bool = False
    estoque_consultado: bool = False
    qualificado: bool = False
    handoff_realizado: bool = False
    venda_fechada: bool = False  # ignorado pelo calculo automatico


@dataclass(frozen=True, slots=True)
class MovimentoInvalido:
    """Resultado de um movimento manual rejeitado."""

    motivo: str


@dataclass(frozen=True, slots=True)
class EtapaMudou:
    """Evento de dominio: a etapa do lead mudou."""

    de: Etapa
    para: Etapa
    ator: Ator
    motivo: str


def _etapa_alvo(fatos: FatosDoLead) -> Etapa:
    alvo = Etapa.NOVO_CONTATO
    if fatos.aparelho_definido and fatos.estoque_consultado:
        alvo = Etapa.INTERESSE_IDENTIFICADO
        if fatos.qualificado:
            alvo = Etapa.INTERESSE_QUALIFICADO
    if fatos.handoff_realizado:
        alvo = Etapa.COM_O_VENDEDOR
    return alvo


def calcular_etapa(atual: Etapa, fatos: FatosDoLead) -> Etapa:
    """Etapa automatica: max(atual, alvo derivado). Nunca regride nem fecha venda."""
    alvo = _etapa_alvo(fatos)
    return alvo if alvo.ordem > atual.ordem else atual


def mover_manual(atual: Etapa, destino: Etapa, ator: Ator) -> Etapa | MovimentoInvalido:
    """Movimento manual no painel. So o vendedor move; venda fechada e final."""
    if ator is not Ator.VENDEDOR:
        return MovimentoInvalido("Somente o vendedor move etapas manualmente.")
    if destino is atual:
        return MovimentoInvalido("O lead ja esta nesta etapa.")
    if atual is Etapa.VENDA_FECHADA:
        return MovimentoInvalido("Venda fechada e uma etapa final.")
    return destino


def atualizar_etapa(
    atual: Etapa, fatos: FatosDoLead, ator: Ator = Ator.SISTEMA
) -> tuple[Etapa, EtapaMudou | None]:
    """Aplica `calcular_etapa` e devolve o evento so se a etapa mudou."""
    nova = calcular_etapa(atual, fatos)
    if nova is atual:
        return atual, None
    motivo = f"Derivada dos fatos do lead: {nova.nome_exibicao}."
    return nova, EtapaMudou(de=atual, para=nova, ator=ator, motivo=motivo)


def mover_manual_com_evento(
    atual: Etapa, destino: Etapa, ator: Ator
) -> tuple[Etapa, EtapaMudou] | MovimentoInvalido:
    """Como `mover_manual`, mas devolve tambem o evento `EtapaMudou`."""
    resultado = mover_manual(atual, destino, ator)
    if isinstance(resultado, MovimentoInvalido):
        return resultado
    motivo = f"Movido manualmente para {resultado.nome_exibicao}."
    return resultado, EtapaMudou(de=atual, para=resultado, ator=ator, motivo=motivo)
