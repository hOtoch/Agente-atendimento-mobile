"""Composicao dos ganchos do handoff: em sequencia, e a falha de um nunca derruba os outros."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.handoff import GanchosHandoff, ResumoHandoff

RESUMO = ResumoHandoff(
    motivo="m",
    aparelho_desejado=None,
    troca=None,
    valor_troca=None,
    proposta=None,
    valor_proposta=None,
    forma_pagamento=None,
    data_prevista=None,
    pendencias=[],
    observacoes=None,
    gerado_em=datetime(2026, 11, 22, tzinfo=UTC),
)


class Gancho:
    def __init__(self, nome: str, ordem: list[str], *, falhar: bool = False) -> None:
        self.nome, self.ordem, self.falhar = nome, ordem, falhar

    async def handoff_solicitado(self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff) -> None:
        self.ordem.append(self.nome)
        if self.falhar:
            raise RuntimeError(self.nome)


async def test_roda_os_ganchos_na_ordem_dada() -> None:
    ordem: list[str] = []
    ganchos = GanchosHandoff([Gancho("aviso", ordem), Gancho("exportar", ordem)])
    await ganchos.handoff_solicitado(uuid4(), uuid4(), RESUMO)
    assert ordem == ["aviso", "exportar"]


async def test_falha_do_primeiro_nao_impede_o_segundo_e_nao_levanta() -> None:
    ordem: list[str] = []
    ganchos = GanchosHandoff([Gancho("aviso", ordem, falhar=True), Gancho("exportar", ordem)])
    await ganchos.handoff_solicitado(uuid4(), uuid4(), RESUMO)  # nao levanta
    assert ordem == ["aviso", "exportar"]


async def test_falha_do_ultimo_nao_levanta() -> None:
    ordem: list[str] = []
    ganchos = GanchosHandoff([Gancho("aviso", ordem), Gancho("exportar", ordem, falhar=True)])
    await ganchos.handoff_solicitado(uuid4(), uuid4(), RESUMO)
    assert ordem == ["aviso", "exportar"]
