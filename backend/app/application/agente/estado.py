"""Estado do atendimento de um lead: ficha + desconto + marcos da conversa (imutavel).

E o que as ferramentas leem e devolvem; o orquestrador persiste via `RepositorioAtendimento`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Self

from app.domain.desconto import EstadoDesconto
from app.domain.ficha import Ficha, pode_passar_preco
from app.domain.kanban import FatosDoLead
from app.domain.valores import Dinheiro


@dataclass(frozen=True, slots=True)
class EstadoAtendimento:
    ficha: Ficha = field(default_factory=Ficha.vazia)
    desconto: EstadoDesconto = field(default_factory=EstadoDesconto)
    estoque_consultado: bool = False
    proposta_apresentada: bool = False
    handoff_solicitado: bool = False
    motivo_handoff: str | None = None
    ultima_proposta: dict[str, Any] | None = None
    """Resumo JSON da ultima proposta (alimenta o resumo do handoff)."""
    acordo: dict[str, Any] | None = None
    """Snapshot do acordo fechado por `fechar_acordo` (None ate a IA fechar; cai se algo muda)."""
    troca_perguntada: bool = False
    """A IA ja perguntou ao cliente se ele tem aparelho para a troca (resposta curta vale)."""

    def para_dict(self) -> dict[str, Any]:
        return {
            "ficha": self.ficha.para_dict(),
            "desconto_liberado": str(self.desconto.liberado.valor),
            "estoque_consultado": self.estoque_consultado,
            "proposta_apresentada": self.proposta_apresentada,
            "handoff_solicitado": self.handoff_solicitado,
            "motivo_handoff": self.motivo_handoff,
            "ultima_proposta": self.ultima_proposta,
            "acordo": self.acordo,
            "troca_perguntada": self.troca_perguntada,
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> Self:
        """Inverso de `para_dict`; chaves ausentes viram o valor inicial."""
        liberado = dados.get("desconto_liberado")
        return cls(
            ficha=Ficha.de_dict(dados.get("ficha") or {}),
            desconto=EstadoDesconto(
                Dinheiro.zero() if liberado is None else Dinheiro(Decimal(liberado))
            ),
            estoque_consultado=bool(dados.get("estoque_consultado", False)),
            proposta_apresentada=bool(dados.get("proposta_apresentada", False)),
            handoff_solicitado=bool(dados.get("handoff_solicitado", False)),
            motivo_handoff=dados.get("motivo_handoff"),
            ultima_proposta=dados.get("ultima_proposta"),
            acordo=dados.get("acordo"),
            troca_perguntada=bool(dados.get("troca_perguntada", False)),
        )


def fatos_do_lead(estado: EstadoAtendimento) -> FatosDoLead:
    """Fatos para o kanban, derivados do estado (nunca decididos pelo LLM)."""
    interesse = estado.ficha.interesse
    return FatosDoLead(
        aparelho_definido=interesse.modelo is not None and interesse.capacidade is not None,
        estoque_consultado=estado.estoque_consultado,
        qualificado=pode_passar_preco(estado.ficha),
        handoff_realizado=estado.handoff_solicitado,
    )


def aparelho_desejado(estado: EstadoAtendimento) -> str | None:
    """`iPhone 16 128GB` (ou so o modelo); None sem modelo na ficha."""
    i = estado.ficha.interesse
    if i.modelo is None:
        return None
    return f"{i.modelo.nome} {i.capacidade}" if i.capacidade is not None else i.modelo.nome


def descrever_troca(estado: EstadoAtendimento) -> str | None:
    """`iPhone 13 128GB`, "Sem aparelho na troca" ou None se ainda nao se sabe."""
    ficha = estado.ficha
    if ficha.tem_troca is None:
        return None
    if ficha.tem_troca is False:
        return "Sem aparelho na troca"
    u = ficha.usado
    if u.modelo is None:
        return "Aparelho usado (modelo ainda não informado)"
    return f"{u.modelo.nome} {u.capacidade}" if u.capacidade is not None else u.modelo.nome
