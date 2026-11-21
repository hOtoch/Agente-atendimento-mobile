"""Follow-up automatico: QUEM recebe e QUANDO (funcao pura; o LLM so redige o texto).

O relogio e o parametro `agora` (datetime com fuso); o horario comercial usa o fuso fixo de
Brasilia (UTC-3, sem DST desde 2019), o mesmo que define "hoje" no resto do sistema.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType

from app.domain.kanban import Etapa

FUSO_LOJA = timezone(timedelta(hours=-3))

ETAPAS_COM_FOLLOWUP: tuple[Etapa, ...] = (
    Etapa.NOVO_CONTATO,
    Etapa.INTERESSE_IDENTIFICADO,
    Etapa.INTERESSE_QUALIFICADO,
)
"""Etapas em que a IA e dona do lead; de "Com o vendedor" em diante o follow-up e humano."""

MAX_TENTATIVAS_PERMITIDO = 5


class ConfigFollowupInvalida(ValueError):
    """Configuracao de follow-up que o dominio nao aceita (`campo` = nome no painel/API)."""

    def __init__(self, campo: str, mensagem: str) -> None:
        super().__init__(f"{campo}: {mensagem}")
        self.campo = campo
        self.mensagem = mensagem


class MotivoEspera(StrEnum):
    DESLIGADO = "desligado"
    DONO_VENDEDOR = "dono_vendedor"
    ETAPA_NAO_CONFIGURADA = "etapa_nao_configurada"
    AGUARDANDO_IA = "aguardando_ia"
    MAXIMO_DE_TENTATIVAS = "maximo_de_tentativas"
    ABANDONADO = "abandonado"
    AINDA_NAO_PARADO = "ainda_nao_parado"
    INTERVALO = "intervalo"
    FORA_DO_HORARIO = "fora_do_horario"


@dataclass(frozen=True, slots=True)
class ConfigFollowup:
    """Configuracao por loja. `horas_por_etapa`: horas parado ate o primeiro follow-up."""

    ligado: bool = False
    horas_por_etapa: Mapping[Etapa, int] = field(default_factory=dict)
    max_tentativas: int = 2
    intervalo_horas: int = 24
    hora_inicio: time = time(9, 0)
    hora_fim: time = time(18, 0)
    max_dias_parado: int = 7

    def __post_init__(self) -> None:
        for etapa, horas in self.horas_por_etapa.items():
            if etapa not in ETAPAS_COM_FOLLOWUP:
                raise ConfigFollowupInvalida(
                    "horas_por_etapa", f"etapa sem follow-up da IA: {etapa.value}"
                )
            if horas < 1:
                raise ConfigFollowupInvalida(
                    "horas_por_etapa", f"horas deve ser >= 1 ({etapa.value})"
                )
        if not 1 <= self.max_tentativas <= MAX_TENTATIVAS_PERMITIDO:
            raise ConfigFollowupInvalida(
                "max_tentativas", f"deve estar entre 1 e {MAX_TENTATIVAS_PERMITIDO}"
            )
        if self.intervalo_horas < 1:
            raise ConfigFollowupInvalida("intervalo_horas", "deve ser >= 1")
        if self.hora_inicio >= self.hora_fim:
            raise ConfigFollowupInvalida("hora_inicio", "deve ser anterior ao fim do horário")
        if self.max_dias_parado < 1:
            raise ConfigFollowupInvalida("max_dias_parado", "deve ser >= 1")
        object.__setattr__(self, "horas_por_etapa", MappingProxyType(dict(self.horas_por_etapa)))

    @classmethod
    def padrao(cls) -> ConfigFollowup:
        """Desligada; ao ligar: qualificado em 2 h, interesse identificado em 24 h."""
        return cls(
            ligado=False,
            horas_por_etapa={Etapa.INTERESSE_QUALIFICADO: 2, Etapa.INTERESSE_IDENTIFICADO: 24},
        )


@dataclass(frozen=True, slots=True)
class FatosFollowup:
    """O que o repositorio sabe do lead. `tentativas` conta os follow-ups enviados DEPOIS da
    ultima mensagem do cliente (quando ele responde, o ciclo recomeca)."""

    etapa: Etapa
    dono_e_ia: bool
    ultima_mensagem_em: datetime
    ultima_mensagem_do_cliente: bool
    tentativas: int
    ultimo_followup_em: datetime | None


@dataclass(frozen=True, slots=True)
class DecisaoFollowup:
    enviar: bool
    motivo: MotivoEspera | None = None
    tentativa: int = 0
    """Numero da tentativa a enviar (1-based); 0 quando espera."""


def _espera(motivo: MotivoEspera) -> DecisaoFollowup:
    return DecisaoFollowup(False, motivo)


def dentro_do_horario(config: ConfigFollowup, agora: datetime) -> bool:
    """Horario comercial no fuso da loja; inicio inclusivo, fim exclusivo."""
    _exigir_fuso(agora)
    hora = agora.astimezone(FUSO_LOJA).time()
    return config.hora_inicio <= hora < config.hora_fim


def _exigir_fuso(agora: datetime) -> None:
    if agora.tzinfo is None:
        raise ValueError("`agora` precisa ter fuso (timezone-aware)")


def decidir_followup(
    config: ConfigFollowup, fatos: FatosFollowup, agora: datetime
) -> DecisaoFollowup:
    _exigir_fuso(agora)
    if not config.ligado:
        return _espera(MotivoEspera.DESLIGADO)
    if not fatos.dono_e_ia:
        return _espera(MotivoEspera.DONO_VENDEDOR)
    horas = config.horas_por_etapa.get(fatos.etapa)
    if horas is None:
        return _espera(MotivoEspera.ETAPA_NAO_CONFIGURADA)
    if fatos.ultima_mensagem_do_cliente:
        return _espera(MotivoEspera.AGUARDANDO_IA)
    if fatos.tentativas >= config.max_tentativas:
        return _espera(MotivoEspera.MAXIMO_DE_TENTATIVAS)
    parado = agora - fatos.ultima_mensagem_em
    if parado > timedelta(days=config.max_dias_parado):
        return _espera(MotivoEspera.ABANDONADO)
    if parado < timedelta(hours=horas):
        return _espera(MotivoEspera.AINDA_NAO_PARADO)
    if fatos.ultimo_followup_em is not None and (
        agora - fatos.ultimo_followup_em < timedelta(hours=config.intervalo_horas)
    ):
        return _espera(MotivoEspera.INTERVALO)
    if not dentro_do_horario(config, agora):
        return _espera(MotivoEspera.FORA_DO_HORARIO)
    return DecisaoFollowup(True, None, fatos.tentativas + 1)
