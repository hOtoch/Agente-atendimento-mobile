from fastapi.testclient import TestClient

from app.main import app


def test_health_retorna_ok() -> None:
    resposta = TestClient(app).get("/health")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["versao"]
