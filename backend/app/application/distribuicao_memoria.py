"""Implementacao em memoria de `AtribuicoesLead` (testes unitarios; sem IO)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from uuid import UUID, uuid4

from app.application.distribuir_lead import LeadNaoEncontrado


class MemoriaAtribuicoes:
    def __init__(self) -> None:
        self._lojas: dict[UUID, UUID] = {}  # lead -> loja
        self._vendedores: dict[UUID, UUID | None] = {}  # lead -> vendedor
        self.lojas_travadas: list[UUID] = []

    def criar_lead(self, loja_id: UUID) -> UUID:
        lead_id = uuid4()
        self._lojas[lead_id] = loja_id
        self._vendedores[lead_id] = None
        return lead_id

    def vendedor_do_lead(self, lead_id: UUID) -> UUID | None:
        return self._vendedores[lead_id]

    def contagem(self, loja_id: UUID) -> dict[UUID, int]:
        return dict(self._contar(loja_id))

    def _contar(self, loja_id: UUID) -> Counter[UUID]:
        return Counter(
            v
            for lead, v in self._vendedores.items()
            if v is not None and self._lojas[lead] == loja_id
        )

    async def travar_loja(self, loja_id: UUID) -> None:
        self.lojas_travadas.append(loja_id)

    async def vendedor_atribuido(self, loja_id: UUID, lead_id: UUID) -> UUID | None:
        if self._lojas.get(lead_id) != loja_id:
            raise LeadNaoEncontrado(lead_id)
        return self._vendedores[lead_id]

    async def contar_por_vendedor(self, loja_id: UUID) -> Mapping[UUID, int]:
        return self.contagem(loja_id)

    async def atribuir(self, loja_id: UUID, lead_id: UUID, vendedor_id: UUID) -> None:
        if self._lojas.get(lead_id) != loja_id:
            raise LeadNaoEncontrado(lead_id)
        self._vendedores[lead_id] = vendedor_id
