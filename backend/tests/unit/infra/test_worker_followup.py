"""Worker: o cron do follow-up esta registrado (a cada 5 min) e chama o hook injetado."""

from __future__ import annotations

from typing import Any

from app.infra import worker


def test_cron_do_follow_up_esta_registrado_a_cada_5_minutos() -> None:
    (job,) = worker.WorkerSettings.cron_jobs
    assert job.coroutine is worker.followup_cron
    assert job.name == "followup_automatico"
    assert job.minute == set(range(0, 60, 5))
    assert job.run_at_startup is False
    assert job.unique is True


async def test_followup_cron_usa_o_hook_do_ctx_sem_abrir_banco() -> None:
    chamadas: list[int] = []

    async def hook() -> int:
        chamadas.append(1)
        return 3

    ctx: dict[str, Any] = {"followup": hook}
    assert await worker.followup_cron(ctx) == 3
    assert chamadas == [1]
    assert "engine" not in ctx


async def test_followup_cron_monta_o_executor_real_na_primeira_rodada(monkeypatch: Any) -> None:
    montados: list[dict[str, Any]] = []

    async def executor() -> int:
        return 0

    def falso(factory: Any, **kw: Any) -> Any:
        montados.append({"factory": factory, **kw})
        return executor

    monkeypatch.setattr(worker, "criar_followups", falso)
    ctx: dict[str, Any] = {"redis": object()}
    try:
        assert await worker.followup_cron(ctx) == 0
        assert await worker.followup_cron(ctx) == 0
        assert len(montados) == 1  # montado uma vez e reaproveitado
        assert montados[0]["redis"] is ctx["redis"]
    finally:
        await worker.encerrar(ctx)
