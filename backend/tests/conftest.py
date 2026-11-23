"""Configuracao compartilhada dos testes."""

import os
from collections.abc import Iterator

import pytest

# Testes nunca chamam APIs pagas (CLAUDE.md, regra 6). As settings leem o `.env` real da maquina,
# que pode ter chaves e `LLM_PROVIDER=openai`; variavel de ambiente vence o `.env`, entao zerar aqui
# (antes de qualquer `get_settings()`) vale para a suite inteira e para os subprocessos dos scripts.
os.environ["LLM_PROVIDER"] = "anthropic"
# os modelos tambem: um modelo local sem preco na tabela zeraria os custos esperados nos testes
os.environ["LLM_MODEL"] = "claude-sonnet-5-5"
os.environ["LLM_FALLBACK_MODEL"] = "claude-haiku-5-5"
for _chave in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MERCADOPHONE_API_KEY"):
    os.environ[_chave] = ""

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def _loja_autorizada_liberada(request: pytest.FixtureRequest) -> Iterator[None]:
    """Testes de rota da loja nao precisam logar: a autorizacao e liberada por override.

    Quem testa a autorizacao de verdade marca `@pytest.mark.autenticacao_real` (ou
    `pytestmark = pytest.mark.autenticacao_real`) e usa `get_sessoes` com cookie.
    """
    from app.infra.dependencias import loja_autorizada
    from app.main import app

    if request.node.get_closest_marker("autenticacao_real"):
        yield
        return
    app.dependency_overrides[loja_autorizada] = lambda: None
    yield
    app.dependency_overrides.pop(loja_autorizada, None)
