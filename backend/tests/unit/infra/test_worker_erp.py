"""Worker: cron da sincronizacao do estoque do ERP (a cada 5 min, unico) e o hook injetavel."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.infra import composicao, worker


def _job() -> Any:
    (job,) = [j for j in worker.WorkerSettings.cron_jobs if j.name == "sincronizar_estoque_erp"]
    return job


def test_cron_da_sincronizacao_esta_registrado_a_cada_5_minutos_e_e_unico() -> None:
    job = _job()
    assert job.coroutine is worker.sincronizar_erp_cron
    assert job.minute == set(range(0, 60, 5))
    assert job.run_at_startup is False
    assert job.unique is True
    assert job.timeout_s >= 300  # le varias unidades de ~20 s cada


async def test_cron_usa_o_hook_do_ctx_sem_abrir_banco() -> None:
    chamadas: list[int] = []

    async def hook() -> int:
        chamadas.append(1)
        return 2

    ctx: dict[str, Any] = {"sincronizar_erp": hook}
    assert await worker.sincronizar_erp_cron(ctx) == 2
    assert chamadas == [1]
    assert "engine" not in ctx


async def test_cron_monta_o_executor_real_uma_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    montados: list[dict[str, Any]] = []

    async def executor() -> int:
        return 0

    def falso(factory: Any, **kw: Any) -> Any:
        montados.append({"factory": factory, **kw})
        return executor

    monkeypatch.setattr(worker, "criar_sincronizador_erp", falso)
    ctx: dict[str, Any] = {"redis": object()}
    try:
        assert await worker.sincronizar_erp_cron(ctx) == 0
        assert await worker.sincronizar_erp_cron(ctx) == 0
        assert len(montados) == 1
    finally:
        await worker.encerrar(ctx)


async def test_sem_chave_o_sincronizador_nao_faz_nada_e_avisa_uma_vez(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.infra.mercadophone import MercadoPhoneNaoConfigurado

    def sem_chave() -> None:
        raise MercadoPhoneNaoConfigurado("sem chave")

    monkeypatch.setattr(composicao, "get_cliente_mercadophone", sem_chave)
    sincronizar = composicao.criar_sincronizador_erp(object())  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger=composicao.__name__):
        assert await sincronizar() == 0
        assert await sincronizar() == 0
    avisos = [r for r in caplog.records if "ERP" in r.getMessage()]
    assert len(avisos) == 1
    assert avisos[0].levelno == logging.INFO
