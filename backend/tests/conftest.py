"""Configuracao compartilhada dos testes."""

import os

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
