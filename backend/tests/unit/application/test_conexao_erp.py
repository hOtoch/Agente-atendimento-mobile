"""Caso de uso da conexao com o ERP (repositorio em memoria)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.config.conexao_erp import ConfigurarConexaoErp, EntradaConexaoErp
from app.application.config.memoria import MemoriaConexaoErp, MemoriaLojas
from app.application.config.modelos import ErrosDeValidacao, LojaNaoEncontrada
from app.domain.conexao_erp import ConexaoErp

ENTRADA = EntradaConexaoErp(
    system_unit_id=12, filtro_loja="Centro", ativo=True, intervalo_min=30, exportar_handoff=True
)


async def _caso() -> tuple[ConfigurarConexaoErp, MemoriaConexaoErp, UUID]:
    lojas = MemoriaLojas()
    loja_id = await lojas.criar("Loja")
    repo = MemoriaConexaoErp()
    return ConfigurarConexaoErp(lojas, repo), repo, loja_id


async def test_loja_sem_conexao_devolve_none() -> None:
    caso, _, loja_id = await _caso()
    assert await caso.obter(loja_id) is None


async def test_salva_e_le_de_volta() -> None:
    caso, _, loja_id = await _caso()
    salva = await caso.atualizar(loja_id, ENTRADA)
    lida = await caso.obter(loja_id)
    assert lida == salva
    assert lida is not None
    assert (lida.system_unit_id, lida.filtro_loja, lida.ativo) == (12, "Centro", True)
    assert (lida.intervalo_min, lida.exportar_handoff) == (30, True)


async def test_regravar_nao_apaga_o_status_da_sincronizacao() -> None:
    caso, repo, loja_id = await _caso()
    await caso.atualizar(loja_id, ENTRADA)
    em = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    await repo.registrar_sincronizacao(
        loja_id,
        em=em,
        status="ok",
        relatorio={"produtos": 10},
    )
    nova = await caso.atualizar(loja_id, EntradaConexaoErp(system_unit_id=13))
    assert nova.system_unit_id == 13
    assert (nova.ultima_sincronizacao_em, nova.ultimo_status) == (em, "ok")
    assert nova.ultimo_relatorio == {"produtos": 10}


@pytest.mark.parametrize(
    ("entrada", "campo"),
    [
        (EntradaConexaoErp(system_unit_id=0), "system_unit_id"),
        (EntradaConexaoErp(system_unit_id=1, intervalo_min=4), "intervalo_min"),
        (EntradaConexaoErp(system_unit_id=1, intervalo_min=1441), "intervalo_min"),
    ],
)
async def test_validacao_vira_erro_por_campo(entrada: EntradaConexaoErp, campo: str) -> None:
    caso, repo, loja_id = await _caso()
    with pytest.raises(ErrosDeValidacao) as exc:
        await caso.atualizar(loja_id, entrada)
    assert exc.value.erros[0].caminho == campo
    assert await repo.obter(loja_id) is None


async def test_loja_inexistente() -> None:
    caso, _, _ = await _caso()
    with pytest.raises(LojaNaoEncontrada):
        await caso.obter(uuid4())
    with pytest.raises(LojaNaoEncontrada):
        await caso.atualizar(uuid4(), ENTRADA)


async def test_registrar_sincronizacao_sem_conexao_e_ignorado() -> None:
    repo = MemoriaConexaoErp()
    await repo.registrar_sincronizacao(
        uuid4(), em=datetime(2026, 11, 22, tzinfo=UTC), status="erro", relatorio=None
    )


async def test_listar_ativas() -> None:
    caso, repo, loja_a = await _caso()
    await caso.atualizar(loja_a, ENTRADA)
    await repo.salvar(ConexaoErp(loja_id=uuid4(), system_unit_id=3, ativo=False))
    assert [c.loja_id for c in await repo.listar_ativas()] == [loja_a]
