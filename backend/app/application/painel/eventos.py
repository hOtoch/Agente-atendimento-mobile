"""Eventos publicados para o painel (SSE por loja).

`para_dict()` e o contrato do payload: `evento` e o discriminador (o cliente TypeScript
tem a mesma uniao em `frontend/src/lib/api/eventos.ts`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from app.domain.kanban import Etapa


@dataclass(frozen=True, slots=True)
class EventoEtapaMudou:
    lead_id: UUID
    de: Etapa
    para: Etapa
    ator: str
    """`ia`, `vendedor` ou `sistema`."""
    motivo: str
    em: datetime
    nome: ClassVar[str] = "EtapaMudou"

    def para_dict(self) -> dict[str, Any]:
        return {
            "evento": self.nome,
            "lead_id": str(self.lead_id),
            "de": self.de.value,
            "para": self.para.value,
            "ator": self.ator,
            "motivo": self.motivo,
            "em": self.em.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class EventoMensagemNova:
    lead_id: UUID
    conversa_id: UUID
    autor: str
    """`cliente`, `ia` ou `vendedor`."""
    direcao: str
    """`entrada` (do cliente) ou `saida` (para o cliente)."""
    tipo: str
    """`texto`, `audio` ou `imagem`."""
    texto: str | None
    midia_url: str | None
    em: datetime
    nome: ClassVar[str] = "MensagemNova"

    def para_dict(self) -> dict[str, Any]:
        return {
            "evento": self.nome,
            "lead_id": str(self.lead_id),
            "conversa_id": str(self.conversa_id),
            "autor": self.autor,
            "direcao": self.direcao,
            "tipo": self.tipo,
            "texto": self.texto,
            "midia_url": self.midia_url,
            "em": self.em.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class EventoDonoMudou:
    lead_id: UUID
    dono: str
    """`ia` ou `vendedor:<id>`."""
    vendedor_id: UUID | None
    """Quem assumiu (None ao devolver para a IA)."""
    em: datetime
    nome: ClassVar[str] = "DonoMudou"

    def para_dict(self) -> dict[str, Any]:
        return {
            "evento": self.nome,
            "lead_id": str(self.lead_id),
            "dono": self.dono,
            "vendedor_id": None if self.vendedor_id is None else str(self.vendedor_id),
            "em": self.em.isoformat(),
        }


EventoPainel = EventoEtapaMudou | EventoMensagemNova | EventoDonoMudou
