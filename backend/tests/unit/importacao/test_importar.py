"""Caso de uso ImportarPlanilha com repositorios em memoria."""

from uuid import UUID, uuid4

import pytest

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.memoria import criar_casos_em_memoria
from app.application.config.modelos import LojaNaoEncontrada
from app.application.importacao.importar import ImportarPlanilha
from tests.unit.importacao.planilhas import estoque_xlsx, regras_com, taxas_xlsx, troca_xlsx

TROCA_OK = [
    ["iPhone 16", 128, 3100, 600, 300, 0, 190, 80],
    ["iPhone 15", 256, 2800, 500, 250, 0, 150, 80],
]
ESTOQUE_OK = [
    ["A1", "iPhone 15 Pro", 256, "Titânio", "novo", 7500, 2, None],
    ["A2", "iPhone 13", 128, "Preto", "seminovo", 3200, 1, 91],
]

Ctx = tuple[CasosDeUsoConfig, ImportarPlanilha, UUID]


@pytest.fixture
async def ctx() -> Ctx:
    casos = criar_casos_em_memoria()
    loja = await casos.criar_loja("Loja")
    return casos, ImportarPlanilha(casos), loja


async def test_validar_nao_grava(ctx: Ctx) -> None:
    casos, imp, loja = ctx
    r = await imp.executar(loja, "troca", troca_xlsx(TROCA_OK), "validar")
    assert r.ok and r.erros == [] and r.resumo["linhas"] == 2
    assert (await casos.obter_troca(loja)).linhas_apple == ()


async def test_aplicar_troca(ctx: Ctx) -> None:
    casos, imp, loja = ctx
    r = await imp.executar(loja, "troca", troca_xlsx(TROCA_OK), "aplicar")
    assert r.ok
    assert len((await casos.obter_troca(loja)).linhas_apple) == 2


async def test_aplicar_com_erro_nao_grava_nada(ctx: Ctx) -> None:
    casos, imp, loja = ctx
    await imp.executar(loja, "troca", troca_xlsx(TROCA_OK), "aplicar")
    ruim = troca_xlsx(
        [["iPhone 16", 128, 3100, 600, 300, 0, 190, 80], ["iPhone 15", "x", 1, 0, 0, 0, 0, 80]]
    )
    r = await imp.executar(loja, "troca", ruim, "aplicar")
    assert not r.ok and r.erros[0].caminho == "troca!B3"
    assert len((await casos.obter_troca(loja)).linhas_apple) == 2  # tabela anterior intacta


async def test_erro_de_negocio_mapeado_para_celula(ctx: Ctx) -> None:
    _, imp, loja = ctx
    # desconto de tela (D3) maior que o valor base
    planilha = troca_xlsx(
        [["iPhone 16", 128, 3100, 0, 0, 0, 0, 80], ["iPhone 15", 128, 500, 900, 0, 0, 0, 80]]
    )
    r = await imp.executar(loja, "troca", planilha, "aplicar")
    assert not r.ok
    assert [e.caminho for e in r.erros] == ["troca!D3"]


async def test_linha_repetida_aponta_celula_do_modelo(ctx: Ctx) -> None:
    _, imp, loja = ctx
    linha = ["iPhone 16", 128, 3100, 0, 0, 0, 0, 80]
    r = await imp.executar(loja, "troca", troca_xlsx([linha, linha]), "validar")
    assert [e.caminho for e in r.erros] == ["troca!A3"]


async def test_planilha_vazia_e_erro(ctx: Ctx) -> None:
    _, imp, loja = ctx
    r = await imp.executar(loja, "troca", troca_xlsx([[None] * 8]), "aplicar")
    assert not r.ok and r.erros[0].caminho == "troca"


async def test_estoque_aplicar(ctx: Ctx) -> None:
    casos, imp, loja = ctx
    r = await imp.executar(loja, "estoque", estoque_xlsx(ESTOQUE_OK), "aplicar")
    assert r.ok and r.resumo["linhas"] == 2
    assert [x.sku for x in await casos.obter_estoque(loja)] == ["A1", "A2"]


async def test_taxas_aplicar_grava_preco_e_taxas(ctx: Ctx) -> None:
    casos, imp, loja = ctx
    planilha = taxas_xlsx([[1, 1.99, "igual", None, None, None]])
    r = await imp.executar(loja, "taxas", planilha, "aplicar")
    assert r.ok
    preco = await casos.obter_preco(loja)
    assert preco is not None and preco.regras.max_parcelas == 18
    assert len((await casos.obter_taxas(loja)).taxas) == 2


async def test_taxas_com_regra_invalida_nao_grava_taxas(ctx: Ctx) -> None:
    casos, imp, loja = ctx
    planilha = taxas_xlsx(
        [[1, 1.99, None, None, None, None]],
        regras_com(**{"Máximo_de_parcelas": 99}),
    )
    r = await imp.executar(loja, "taxas", planilha, "aplicar")
    assert not r.ok
    assert "regras!B2" in [e.caminho for e in r.erros]
    assert (await casos.obter_taxas(loja)).taxas == {}


async def test_loja_inexistente(ctx: Ctx) -> None:
    _, imp, _ = ctx
    with pytest.raises(LojaNaoEncontrada):
        await imp.executar(uuid4(), "troca", troca_xlsx(TROCA_OK), "validar")


async def test_commit_e_rollback_chamados() -> None:
    casos = criar_casos_em_memoria()
    loja = await casos.criar_loja("L")
    eventos: list[str] = []

    async def commit() -> None:
        eventos.append("commit")

    async def rollback() -> None:
        eventos.append("rollback")

    imp = ImportarPlanilha(casos, commit=commit, rollback=rollback)
    await imp.executar(loja, "troca", troca_xlsx(TROCA_OK), "validar")
    assert eventos == []
    await imp.executar(loja, "troca", troca_xlsx(TROCA_OK), "aplicar")
    assert eventos == ["commit"]

    async def quebra(*_: object) -> None:
        raise RuntimeError("falha no banco")

    casos.atualizar_troca = quebra  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await imp.executar(loja, "troca", troca_xlsx(TROCA_OK), "aplicar")
    assert eventos == ["commit", "rollback"]
