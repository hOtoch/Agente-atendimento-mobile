"""RepositorioAtendimentoEmMemoria: mesma semantica do repositorio SQL."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from app.application.agente.estado import EstadoAtendimento
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria


async def test_obter_sem_dados_devolve_estado_vazio() -> None:
    repo = RepositorioAtendimentoEmMemoria()
    assert await repo.obter(uuid4(), uuid4()) == EstadoAtendimento()


async def test_salvar_devolve_versoes_crescentes_e_obter_le_a_ultima() -> None:
    repo = RepositorioAtendimentoEmMemoria()
    loja, lead = uuid4(), uuid4()
    e1 = replace(EstadoAtendimento(), estoque_consultado=True)
    e2 = replace(e1, proposta_apresentada=True)
    assert await repo.salvar(loja, lead, e1) == 1
    assert await repo.salvar(loja, lead, e2) == 2
    assert await repo.obter(loja, lead) == e2


async def test_leads_sao_independentes() -> None:
    repo = RepositorioAtendimentoEmMemoria()
    loja = uuid4()
    a, b = uuid4(), uuid4()
    await repo.salvar(loja, a, replace(EstadoAtendimento(), handoff_solicitado=True))
    assert await repo.obter(loja, b) == EstadoAtendimento()
    assert await repo.salvar(loja, b, EstadoAtendimento()) == 1
