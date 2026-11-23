"""Tipos neutros de provedor do LLMPort (sem SDK)."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from app.application.llm import (
    BlocoImagem,
    BlocoTexto,
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ErroLLM,
    LLMIndisponivel,
    LLMRecusou,
    MensagemLLM,
    ResultadoFerramenta,
    UsoTokens,
)


def test_uso_tokens_soma_campo_a_campo() -> None:
    a = UsoTokens("claude-sonnet-5-5", entrada=10, saida=5, cache_leitura=100, cache_escrita=0)
    b = UsoTokens("claude-sonnet-5-5", entrada=1, saida=2, cache_leitura=50, cache_escrita=30)
    assert a + b == UsoTokens(
        "claude-sonnet-5-5", entrada=11, saida=7, cache_leitura=150, cache_escrita=30
    )


def test_uso_tokens_de_modelos_diferentes_vira_misto() -> None:
    total = UsoTokens("claude-sonnet-5-5", 10, 5, 0, 0) + UsoTokens("claude-haiku-5-5", 1, 1, 0, 0)
    assert total.modelo == "misto"
    assert (total.entrada, total.saida) == (11, 6)


def test_uso_tokens_funciona_com_sum_da_biblioteca_padrao() -> None:
    usos = [UsoTokens("m", 1, 2, 3, 4), UsoTokens("m", 10, 20, 30, 40)]
    assert sum(usos, UsoTokens.vazio("m")) == UsoTokens("m", 11, 22, 33, 44)
    assert sum(usos) == UsoTokens("m", 11, 22, 33, 44)  # radd com 0


def test_uso_tokens_vazio_e_elemento_neutro() -> None:
    a = UsoTokens("m", 1, 2, 3, 4)
    assert UsoTokens.vazio() + a == a
    assert UsoTokens.vazio("m") + a == a


def test_uso_tokens_e_imutavel() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        UsoTokens("m", 1, 2, 3, 4).entrada = 9  # type: ignore[misc]


def test_resultado_ferramenta_nao_e_erro_por_padrao() -> None:
    assert ResultadoFerramenta(id_chamada="t1", conteudo="ok").erro is False


def test_mensagem_de_sistema_aceita_so_texto() -> None:
    ok = MensagemLLM("system", [BlocoTexto("estado da ficha")])
    assert ok.bruto is None
    with pytest.raises(ValueError, match="sistema"):
        MensagemLLM("system", [BlocoImagem("image/png", "AAAA")])
    with pytest.raises(ValueError, match="sistema"):
        MensagemLLM("system", [ChamadaFerramenta("t1", "buscar", {})])


def test_papel_invalido_e_rejeitado() -> None:
    with pytest.raises(ValueError, match="papel"):
        MensagemLLM("tool", [BlocoTexto("x")])  # type: ignore[arg-type]


def test_definicao_ferramenta_e_estrita_por_padrao() -> None:
    assert DefinicaoFerramenta("buscar", "Busca", {"type": "object"}).estrita is True


def test_hierarquia_de_erros() -> None:
    assert issubclass(LLMIndisponivel, ErroLLM)
    assert issubclass(LLMRecusou, ErroLLM)
    assert LLMRecusou("cyber").categoria == "cyber"
    assert LLMRecusou(None).categoria is None


def test_erro_llm_leva_status_e_modelo_opcionais() -> None:
    assert ErroLLM("x").status is None and ErroLLM("x").modelo is None
    erro = LLMIndisponivel("fora", status=529, modelo="claude-x")
    assert (erro.status, erro.modelo) == (529, "claude-x")
    assert LLMRecusou("cyber", modelo="claude-x").modelo == "claude-x"


def test_modulo_nao_importa_o_sdk() -> None:
    codigo = "import sys, app.application.llm; sys.exit(1 if 'anthropic' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", codigo], check=False).returncode == 0
