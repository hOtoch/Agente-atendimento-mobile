"""`scripts/popular_metricas_demo.py`: argumentos e travas de seguranca (sem banco)."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

import pytest

from tests.unit.scripts.carregar import BACKEND


def carregar_popular() -> ModuleType:
    if "popular_metricas_demo" in sys.modules:
        return sys.modules["popular_metricas_demo"]
    spec = importlib.util.spec_from_file_location(
        "popular_metricas_demo", BACKEND / "scripts" / "popular_metricas_demo.py"
    )
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["popular_metricas_demo"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


demo = carregar_popular()

LOJA = "00000000-0000-4000-8000-00000000de30"
URL_DEV = "postgresql+asyncpg://atendimento:atendimento@localhost:5432/atendimento"
URL_TESTE = "postgresql+asyncpg://teste:teste@localhost:5433/teste"


def test_sem_loja_recusa_com_erro_de_uso() -> None:
    with pytest.raises(SystemExit) as saida:
        demo.main(["--dias", "30", "--database-url", URL_DEV])
    assert saida.value.code == 2


def test_loja_precisa_ser_uuid() -> None:
    with pytest.raises(SystemExit) as saida:
        demo.main(["--loja", "nao-e-uuid", "--database-url", URL_DEV])
    assert saida.value.code == 2


@pytest.mark.parametrize(
    "url",
    [
        URL_TESTE,
        "postgresql+asyncpg://u:p@db.interno:5433/qualquer",
        "postgresql+asyncpg://u:p@localhost:5432/teste_ab12cd34",
    ],
)
def test_recusa_banco_de_teste_fora_do_modo_de_teste(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert demo.main(["--loja", LOJA, "--database-url", url]) == 2
    assert "teste" in capsys.readouterr().err.lower()


def test_remover_tambem_recusa_banco_de_teste(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main(["--loja", LOJA, "--remover", "--database-url", URL_TESTE]) == 2
    assert capsys.readouterr().err


def test_banco_de_dev_passa_na_trava() -> None:
    demo.verificar_banco(URL_DEV, permitir_teste=False)


def test_modo_de_teste_libera_o_banco_de_teste() -> None:
    demo.verificar_banco(URL_TESTE, permitir_teste=True)


def test_dias_precisa_ser_positivo() -> None:
    with pytest.raises(SystemExit) as saida:
        demo.main(["--loja", LOJA, "--dias", "0", "--database-url", URL_DEV])
    assert saida.value.code == 2
