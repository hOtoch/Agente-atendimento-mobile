"""Fabrica do cliente do Mercado Phone: sem chave, a integracao fica desligada."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.infra import mercadophone
from app.infra.mercadophone import MercadoPhoneNaoConfigurado, get_cliente_mercadophone
from app.infra.settings import Settings


@pytest.fixture(autouse=True)
def _limpar_cache() -> Iterator[None]:
    get_cliente_mercadophone.cache_clear()
    yield
    get_cliente_mercadophone.cache_clear()


def test_sem_chave_levanta_nao_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mercadophone, "get_settings", lambda: Settings(_env_file=None, mercadophone_api_key=None)
    )
    with pytest.raises(MercadoPhoneNaoConfigurado):
        get_cliente_mercadophone()


def test_com_chave_cria_um_cliente_reaproveitado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mercadophone,
        "get_settings",
        lambda: Settings(_env_file=None, mercadophone_api_key="chave-de-teste"),
    )
    cliente = get_cliente_mercadophone()
    assert isinstance(cliente, ClienteMercadoPhone)
    assert get_cliente_mercadophone() is cliente
    assert "chave-de-teste" not in repr(cliente)
