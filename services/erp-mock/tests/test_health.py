from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import SleepFalso


def test_health_sem_auth(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ignora_erro_e_latencia(
    fazer_client: Callable[..., TestClient], sleep_falso: SleepFalso
) -> None:
    client = fazer_client(erro_pct=100, latencia_ms=500)
    assert client.get("/health").status_code == 200
    assert sleep_falso.chamadas == []
