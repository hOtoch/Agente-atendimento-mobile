"""Regras puras das metricas do agente: periodo (fuso de Sao Paulo), razoes e variacao %.

O painel de desempenho agrega por periodo de DIAS no fuso da loja (America/Sao_Paulo): o dia
comeca e termina a meia-noite de Sao Paulo, nao a de UTC. Tudo aqui e funcao pura, sem IO.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

FUSO_NOME = "America/Sao_Paulo"
# UTC-3 fixo (sem horario de verao desde 2019): ZoneInfo dependeria do tzdata, ausente no Windows.
# O nome segue indo para o Postgres (AT TIME ZONE), que tem a propria base de fusos.
FUSO = timezone(timedelta(hours=-3), FUSO_NOME)

_UM_DECIMAL = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class Periodo:
    """Intervalo de dias, com os dois extremos incluidos, no fuso de Sao Paulo."""

    de: date
    ate: date

    def __post_init__(self) -> None:
        if self.de > self.ate:
            raise ValueError("`de` nao pode ser depois de `ate`")

    @property
    def dias(self) -> int:
        return (self.ate - self.de).days + 1

    @property
    def inicio(self) -> datetime:
        """Primeiro instante do periodo (00:00 de `de`, em Sao Paulo)."""
        return datetime.combine(self.de, time.min, tzinfo=FUSO)

    @property
    def fim_exclusivo(self) -> datetime:
        """Primeiro instante DEPOIS do periodo (00:00 do dia seguinte a `ate`)."""
        return datetime.combine(self.ate + timedelta(days=1), time.min, tzinfo=FUSO)

    def listar_dias(self) -> list[date]:
        return [self.de + timedelta(days=i) for i in range(self.dias)]

    def anterior(self) -> Periodo:
        """Periodo imediatamente anterior, do mesmo tamanho."""
        return Periodo(self.de - timedelta(days=self.dias), self.de - timedelta(days=1))


def razao(numerador: int | Decimal, denominador: int | Decimal) -> Decimal | None:
    """`numerador / denominador`; `None` quando nao ha denominador (nunca zero inventado)."""
    if denominador == 0:
        return None
    return Decimal(numerador) / Decimal(denominador)


def variacao_pct(atual: Decimal | None, anterior: Decimal | None) -> Decimal | None:
    """Variacao percentual (1 casa) do periodo atual sobre o anterior.

    `None` quando falta um dos lados ou quando o anterior e zero e o atual nao (nao existe %
    sobre zero); zero contra zero e 0,0.
    """
    if atual is None or anterior is None:
        return None
    if anterior == 0:
        return Decimal("0.0") if atual == 0 else None
    return ((atual - anterior) / anterior * 100).quantize(_UM_DECIMAL, rounding=ROUND_HALF_UP)


def taxa_cache(*, entrada: int, cache_leitura: int, cache_escrita: int) -> Decimal | None:
    """Fatia do prompt servida pelo cache: lido / (nao cacheado + lido + escrito)."""
    return razao(cache_leitura, entrada + cache_leitura + cache_escrita)


class MotivoHandoff(StrEnum):
    """Categoria do motivo com que a IA passou o atendimento a um vendedor."""

    PEDIDO_CLIENTE = "pedido_cliente"
    ACORDO_FECHADO = "acordo_fechado"
    FALHA_TECNICA = "falha_tecnica"
    NEGOCIACAO = "negociacao"
    OUTROS = "outros"

    @property
    def nome_exibicao(self) -> str:
        return _NOMES_MOTIVO[self]


_NOMES_MOTIVO: dict[MotivoHandoff, str] = {
    MotivoHandoff.PEDIDO_CLIENTE: "Pedido do cliente",
    MotivoHandoff.ACORDO_FECHADO: "Acordo fechado",
    MotivoHandoff.FALHA_TECNICA: "Falha técnica",
    MotivoHandoff.NEGOCIACAO: "Negociação além do teto",
    MotivoHandoff.OUTROS: "Outros",
}

MOTIVO_ACORDO_FECHADO = "acordo_fechado"
MOTIVO_FALHA_LLM = "falha_llm"
MOTIVO_NEGOCIACAO = "negociacao"

# O motivo de uma chamada da IA e texto livre; reconhecemos so o pedido explicito de falar com
# uma pessoa (trechos sem acento, em minusculas).
_PEDIDO_DO_CLIENTE = (
    "pediu",
    "pedido do cliente",
    "solicitou",
    "quer falar",
    "queria falar",
    "falar com",
    "atendente",
    "humano",
    "pessoa",
)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def classificar_motivo_handoff(motivo: str) -> MotivoHandoff:
    """Classifica o motivo gravado no handoff (os do sistema sao exatos; o resto, por trecho)."""
    texto = _normalizar(motivo)
    if texto == MOTIVO_ACORDO_FECHADO:
        return MotivoHandoff.ACORDO_FECHADO
    if texto == MOTIVO_FALHA_LLM:
        return MotivoHandoff.FALHA_TECNICA
    if texto == MOTIVO_NEGOCIACAO:
        return MotivoHandoff.NEGOCIACAO
    if any(trecho in texto for trecho in _PEDIDO_DO_CLIENTE):
        return MotivoHandoff.PEDIDO_CLIENTE
    return MotivoHandoff.OUTROS
