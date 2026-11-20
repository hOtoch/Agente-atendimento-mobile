import random
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import AUTH, SleepFalso


def test_erro_100_sempre_500(fazer_client: Callable[..., TestClient]) -> None:
    client = fazer_client(erro_pct=100)
    for _ in range(30):
        assert client.get("/produtos", headers=AUTH).status_code == 500
    assert client.get("/produtos/APL-000001", headers=AUTH).status_code == 500


def test_erro_0_nunca_500(fazer_client: Callable[..., TestClient]) -> None:
    client = fazer_client(erro_pct=0)
    for _ in range(200):
        assert client.get("/produtos", headers=AUTH).status_code == 200


def test_erro_parcial_com_seed_e_deterministico(
    fazer_client: Callable[..., TestClient],
) -> None:
    def rodar() -> list[int]:
        client = fazer_client(erro_pct=50, seed=42)
        return [client.get("/produtos", headers=AUTH).status_code for _ in range(40)]

    a, b = rodar(), rodar()
    assert a == b
    assert 500 in a
    assert 200 in a


def test_auth_vem_antes_do_erro(fazer_client: Callable[..., TestClient]) -> None:
    client = fazer_client(erro_pct=100)
    assert client.get("/produtos").status_code == 401


def test_latencia_usa_sleep_injetado(
    fazer_client: Callable[..., TestClient], sleep_falso: SleepFalso
) -> None:
    client = fazer_client(latencia_ms=250)
    assert client.get("/produtos", headers=AUTH).status_code == 200
    assert sleep_falso.chamadas == [0.25]


def test_latencia_zero_nao_dorme(
    fazer_client: Callable[..., TestClient], sleep_falso: SleepFalso
) -> None:
    client = fazer_client()
    client.get("/produtos", headers=AUTH)
    assert sleep_falso.chamadas == []


def test_latencia_nao_se_aplica_sem_auth(
    fazer_client: Callable[..., TestClient], sleep_falso: SleepFalso
) -> None:
    client = fazer_client(latencia_ms=250)
    client.get("/produtos")
    assert sleep_falso.chamadas == []


def test_latencia_acontece_antes_do_erro(
    fazer_client: Callable[..., TestClient], sleep_falso: SleepFalso
) -> None:
    client = fazer_client(latencia_ms=100, erro_pct=100)
    assert client.get("/produtos", headers=AUTH).status_code == 500
    assert sleep_falso.chamadas == [0.1]


def test_settings_le_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERP_MOCK_LATENCIA_MS", "120")
    monkeypatch.setenv("ERP_MOCK_ERRO_PCT", "30")
    monkeypatch.setenv("ERP_MOCK_SEED", "7")
    s = Settings()
    assert (s.latencia_ms, s.erro_pct, s.seed) == (120, 30, 7)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("TOKEN", "LATENCIA_MS", "ERRO_PCT", "SEED"):
        monkeypatch.delenv(f"ERP_MOCK_{nome}", raising=False)
    s = Settings()
    assert (s.latencia_ms, s.erro_pct, s.seed) == (0, 0.0, None)


def test_erro_pct_fora_da_faixa_rejeitado() -> None:
    with pytest.raises(ValueError):
        Settings(erro_pct=101)
    with pytest.raises(ValueError):
        Settings(erro_pct=-1)


def test_rng_injetado_decide_o_erro() -> None:
    class RngFixo(random.Random):
        def random(self) -> float:
            return 0.0

    app = create_app(Settings(token="t", erro_pct=1), rng=RngFixo())
    resp = TestClient(app).get("/produtos", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 500
