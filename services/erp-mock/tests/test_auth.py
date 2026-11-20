import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from tests.conftest import AUTH


@pytest.mark.parametrize("caminho", ["/produtos", "/produtos/APL-000001"])
def test_sem_token_401(client: TestClient, caminho: str) -> None:
    assert client.get(caminho).status_code == 401


@pytest.mark.parametrize(
    "header",
    ["Bearer errado", "token-teste", "Basic token-teste", "Bearer ", "Bearer"],
)
def test_token_invalido_401(client: TestClient, header: str) -> None:
    resp = client.get("/produtos", headers={"Authorization": header})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_token_correto_200(client: TestClient) -> None:
    assert client.get("/produtos", headers=AUTH).status_code == 200


def test_token_default_e_token_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ERP_MOCK_TOKEN", raising=False)
    assert Settings().token == "token-dev"


def test_token_vem_do_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERP_MOCK_TOKEN", "outro")
    assert Settings().token == "outro"
