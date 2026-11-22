"""`scripts/mercadophone_smoke.py`: argumentos, resumo impresso e garantia de so leitura.

Usa o servidor MCP falso (`tests/mercadophone_falso.py`) por injecao do cliente; nunca a rede.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from types import ModuleType

import pytest

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.application.relogio import RelogioFalso
from app.infra.mercadophone import MercadoPhoneNaoConfigurado
from tests.mercadophone_falso import CHAVE, URL, McpFalso, item
from tests.unit.scripts.carregar import BACKEND

CAMINHO = BACKEND / "scripts" / "mercadophone_smoke.py"


def _carregar() -> ModuleType:
    if "mercadophone_smoke" in sys.modules:
        return sys.modules["mercadophone_smoke"]
    spec = importlib.util.spec_from_file_location("mercadophone_smoke", CAMINHO)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["mercadophone_smoke"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


smoke = _carregar()


def _cliente(mcp: McpFalso) -> ClienteMercadoPhone:
    return ClienteMercadoPhone(mcp.cliente_http(), URL, CHAVE, relogio=RelogioFalso())


def _mcp() -> McpFalso:
    return McpFalso(
        {
            4: [
                item(1, sku="TESTE-A1", obs="Loja A"),
                item(2, sku="TESTE-A2", obs="Loja A | vitrine"),
                item(3, sku="TESTE-B1", obs="Loja B"),
                item(4, sku="TESTE-A3", obs="Loja A", preco=0.01),
                item(5, sku="TESTE-A4", obs="Loja A", tipo="Acessório"),
                item(6, sku="TESTE-A5", obs="Loja A", quantidade=0),
            ],
            9: [item(100, sku="OUTRA-1")],
        },
        lojas_da_chave=[4, 9],
    )


# --- argumentos ----------------------------------------------------------------------------


def test_argumentos_padrao() -> None:
    args = smoke.montar_parser().parse_args([])
    assert args.unidade is None
    assert args.filtro_loja == []
    assert args.conferir == 0


def test_argumentos_filtro_repetivel_unidade_e_conferir() -> None:
    args = smoke.montar_parser().parse_args(
        ["--unidade", "4", "--filtro-loja", "Loja A", "--filtro-loja", "Loja B", "--conferir", "2"]
    )
    assert args.unidade == 4
    assert args.filtro_loja == ["Loja A", "Loja B"]
    assert args.conferir == 2


# --- resumo --------------------------------------------------------------------------------


async def test_resumo_por_filtro_com_lidos_importados_outra_loja_e_descartes() -> None:
    mcp = _mcp()
    linhas: list[str] = []
    codigo = await smoke.executar(
        _cliente(mcp), unidade=4, filtros=["Loja A", "Loja B"], conferir=0, saida=linhas.append
    )
    texto = "\n".join(linhas)

    assert codigo == 0
    assert "Unidade 4" in texto
    assert "Loja A" in texto and "Loja B" in texto
    # Loja A: 6 lidos, 2 importados, 1 da B (outra loja), descartes: sem_preco, nao_e_celular,
    # sem_quantidade (1 de cada).
    bloco_a = texto.split("Loja B", 1)[0]
    assert re.search(r"lidos:\s*6", bloco_a)
    assert re.search(r"importados:\s*2", bloco_a)
    assert re.search(r"outra loja:\s*1", bloco_a)
    assert re.search(r"sem_preco:\s*1", bloco_a)
    assert re.search(r"nao_e_celular:\s*1", bloco_a)
    assert re.search(r"sem_quantidade:\s*1", bloco_a)
    assert re.search(r"dura[cç][aã]o.*\d", texto, re.IGNORECASE)


async def test_le_a_unidade_uma_vez_para_varios_filtros() -> None:
    mcp = _mcp()
    await smoke.executar(
        _cliente(mcp), unidade=4, filtros=["Loja A", "Loja B"], conferir=0, saida=lambda _: None
    )
    assert mcp.leituras_do_inventario() == 1


async def test_sem_filtro_imprime_um_resumo_sem_filtro() -> None:
    mcp = _mcp()
    linhas: list[str] = []
    codigo = await smoke.executar(
        _cliente(mcp), unidade=4, filtros=[], conferir=0, saida=linhas.append
    )
    texto = "\n".join(linhas)
    assert codigo == 0
    assert "sem filtro" in texto
    assert re.search(r"lidos:\s*6", texto)
    assert re.search(r"outra loja:\s*0", texto)


async def test_unidade_padrao_e_a_primeira_de_list_my_stores() -> None:
    mcp = _mcp()
    linhas: list[str] = []
    await smoke.executar(_cliente(mcp), unidade=None, filtros=[], conferir=0, saida=linhas.append)
    assert "Unidade 4" in "\n".join(linhas)
    assert all(a.get("system_unit_id") == 4 for a in mcp.chamadas_de("list_inventory"))


async def test_unidade_fora_da_chave_falha_com_exit_1_e_nao_le_estoque() -> None:
    mcp = _mcp()
    linhas: list[str] = []
    erros: list[str] = []
    codigo = await smoke.executar(
        _cliente(mcp),
        unidade=77,
        filtros=[],
        conferir=0,
        saida=linhas.append,
        erro=erros.append,
    )
    assert codigo == 1
    assert "77" in "\n".join(erros)
    assert mcp.chamadas_de("list_inventory") == []


async def test_chave_sem_lojas_falha_com_exit_1() -> None:
    mcp = McpFalso({4: [item(1)]}, lojas_da_chave=[])
    erros: list[str] = []
    codigo = await smoke.executar(
        _cliente(mcp), unidade=None, filtros=[], conferir=0, saida=lambda _: None, erro=erros.append
    )
    assert codigo == 1
    assert erros


# --- conferencia ao vivo -------------------------------------------------------------------


async def test_conferir_n_confere_os_n_primeiros_importados_e_nao_grava() -> None:
    mcp = _mcp()
    linhas: list[str] = []
    codigo = await smoke.executar(
        _cliente(mcp), unidade=4, filtros=["Loja A"], conferir=2, saida=linhas.append
    )
    texto = "\n".join(linhas)
    assert codigo == 0
    conferidos = [a["sku"] for a in mcp.chamadas_de("list_inventory") if "sku" in a]
    assert conferidos == ["TESTE-A1", "TESTE-A2"]
    assert texto.count("disponivel") >= 2


# --- so leitura ----------------------------------------------------------------------------


async def test_so_chama_ferramentas_de_leitura_mesmo_com_conferencia() -> None:
    mcp = _mcp()
    await smoke.executar(
        _cliente(mcp), unidade=None, filtros=["Loja A", "Loja B"], conferir=3, saida=lambda _: None
    )
    nomes = {n for n, _ in mcp.chamadas}
    assert nomes
    assert all(n.startswith("list_") for n in nomes), nomes


def test_codigo_do_script_nao_menciona_ferramenta_de_escrita() -> None:
    arvore = ast.parse(CAMINHO.read_text(encoding="utf-8"))
    textos = [
        n.value
        for n in ast.walk(arvore)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    ferramentas = [t for t in textos if re.fullmatch(r"[a-z]+(_[a-z]+)+", t)]
    escrita = [t for t in ferramentas if t.split("_")[0] in {"create", "update", "delete", "set"}]
    assert escrita == []
    usadas = [t for t in ferramentas if t.startswith("list_")]
    assert usadas, "o script deveria usar ferramentas list_*"


# --- main / chave --------------------------------------------------------------------------


def _sem_chave() -> ClienteMercadoPhone:
    raise MercadoPhoneNaoConfigurado("MERCADOPHONE_API_KEY nao configurada")


def test_sem_chave_mensagem_clara_e_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = smoke.main([], cliente_factory=_sem_chave)
    saida = capsys.readouterr()
    assert codigo == 2
    assert "MERCADOPHONE_API_KEY" in saida.err
    assert ".env" in saida.err


def test_main_com_cliente_injetado_imprime_resumo(capsys: pytest.CaptureFixture[str]) -> None:
    mcp = _mcp()
    codigo = smoke.main(
        ["--unidade", "4", "--filtro-loja", "Loja A"], cliente_factory=lambda: _cliente(mcp)
    )
    saida = capsys.readouterr()
    assert codigo == 0
    assert "Loja A" in saida.out
    assert CHAVE not in saida.out and CHAVE not in saida.err


def test_main_erro_do_erp_vira_exit_1_sem_vazar_a_chave(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import httpx

    mcp = McpFalso(
        {4: [item(1)]},
        falha_ferramentas={"list_my_stores": httpx.Response(401, text="nao")},
    )
    codigo = smoke.main([], cliente_factory=lambda: _cliente(mcp))
    saida = capsys.readouterr()
    assert codigo == 1
    assert CHAVE not in saida.out and CHAVE not in saida.err
    assert saida.err
