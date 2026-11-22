"""Tipos do eval: transcricao observavel, resultado de checagem e cenarios declarativos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

# Data fixa de "hoje" em todos os cenarios (reprodutibilidade; "daqui a 20 dias" = 2026-12-10).
HOJE = date(2026, 11, 20)
MAX_CHARS_PADRAO = 700
MAX_TURNOS_PADRAO = 12


@dataclass(frozen=True, slots=True)
class MensagemCliente:
    texto: str


@dataclass(frozen=True, slots=True)
class MensagemAgente:
    texto: str


@dataclass(frozen=True, slots=True)
class ExecucaoFerramenta:
    nome: str
    entrada: dict[str, Any]
    resultado: dict[str, Any]
    erro: bool = False
    erro_interno: bool = False
    """Excecao nao tratada dentro da ferramenta (o orquestrador devolveu a mensagem generica)."""


Evento = MensagemCliente | MensagemAgente | ExecucaoFerramenta


@dataclass(frozen=True, slots=True)
class Transcricao:
    """Tudo o que as checagens enxergam de uma conversa, em ordem."""

    eventos: tuple[Evento, ...]
    etapa_final: str
    handoff: bool

    @property
    def mensagens_agente(self) -> list[MensagemAgente]:
        return [e for e in self.eventos if isinstance(e, MensagemAgente)]

    @property
    def ferramentas(self) -> list[ExecucaoFerramenta]:
        return [e for e in self.eventos if isinstance(e, ExecucaoFerramenta)]


@dataclass(frozen=True, slots=True)
class Checagem:
    nome: str
    passou: bool
    motivo: str = ""
    aplicavel: bool = True


@dataclass(frozen=True, slots=True)
class Parametros:
    teto: Decimal
    oportunidade_max: Decimal
    max_chars: int = MAX_CHARS_PADRAO
    max_perguntas: int = 1


@dataclass(frozen=True, slots=True)
class Expectativas:
    etapa_final: str | None = None
    handoff: bool | None = None
    max_chars: int = MAX_CHARS_PADRAO
    frases_proibidas: tuple[str, ...] = ()
    """Regex (sem diferenciar caixa) que o agente nao pode dizer."""
    valores_esperados: tuple[str, ...] = ()
    """Valores 'R$ x' que o agente precisa dizer em algum momento."""
    acordo_fechado: bool | None = None
    """True: o agente tem de fechar o acordo (fechar_acordo ok), dizer o endereco devolvido e so
    depois chamar o vendedor."""


@dataclass(frozen=True, slots=True)
class Cenario:
    id: str
    titulo: str
    persona: str
    objetivo: str
    roteiro: tuple[str, ...]
    """Falas do cliente. Modo fake: todas, em ordem. Modo real: so a primeira (abertura);
    o resto o LLM do cliente improvisa a partir de persona/objetivo/sabe."""
    sabe: dict[str, str] = field(default_factory=dict)
    expectativas: Expectativas = field(default_factory=Expectativas)
    max_turnos: int = MAX_TURNOS_PADRAO
    deve_reprovar: bool = False
    """Controle negativo: o cenario viola uma regra de proposito e DEVE ser reprovado."""
