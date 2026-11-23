"""Ferramentas do agente: registro, estoque, usado, compra, desconto e handoff."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from app.application.agente.estado import EstadoAtendimento
from app.application.agente.ferramentas import ResultadoFerramenta
from app.application.config.modelos import LinhaEstoqueLocal
from app.domain.desconto import EstadoDesconto
from app.domain.estoque import Condicao, ItemEstoque
from app.domain.ficha import TipoPagamento, UsadoInformado
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    HOJE,
    INTERESSE_16,
    ITENS_16_VARIOS,
    ITENS_PADRAO,
    USADO_EXEMPLO,
    Ambiente,
    EstoqueFora,
    criar_ambiente,
    item,
    sem_valores,
)

VAZIO = EstadoAtendimento()


# --- geral -------------------------------------------------------------------------------


async def test_ferramenta_desconhecida_e_erro_sem_excecao() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("inventar_preco", {}, VAZIO)
    assert r.erro
    assert r.estado == VAZIO
    assert "inventar_preco" in json.dumps(r.conteudo, ensure_ascii=False)


async def test_entrada_invalida_e_erro_sem_excecao() -> None:
    amb = await criar_ambiente()
    for nome, entrada in [
        ("registrar_interesse", {}),
        ("registrar_interesse", {"modelo": 123}),
        ("confirmar_item", {"sku": None}),
        ("chamar_vendedor", {"motivo": ""}),
        ("registrar_usado", {"modelo": "iPhone 12"}),
    ]:
        r = await amb.rodar(nome, entrada, VAZIO)  # type: ignore[arg-type]
        assert r.erro, (nome, entrada)
        assert r.estado == VAZIO


async def test_cada_execucao_gera_evento_de_ferramenta() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_interesse", INTERESSE_16, VAZIO)
    assert len(r.eventos) == 1
    ev = r.eventos[0]
    assert ev["tipo"] == "ferramenta"
    assert ev["nome"] == "registrar_interesse"
    assert ev["entrada"] == INTERESSE_16
    assert isinstance(ev["resultado_resumido"], str)
    json.dumps(ev)
    erro = await amb.rodar("nao_existe", {"x": 1}, VAZIO)
    assert erro.eventos[0]["nome"] == "nao_existe"


async def test_estado_original_nao_e_mutado() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_interesse", INTERESSE_16, VAZIO)
    assert VAZIO.ficha.interesse.modelo is None
    assert r.estado.ficha.interesse.modelo == ModeloAparelho.de("iPhone 16")


# --- registrar_interesse -----------------------------------------------------------------


async def test_registrar_interesse_grava_na_ficha() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "iphone16", "capacidade": "128 gb", "cor": "Preto"}, VAZIO
    )
    assert not r.erro
    i = r.estado.ficha.interesse
    assert i.modelo == ModeloAparelho.de("iPhone 16")
    assert i.capacidade == Capacidade(128)
    assert i.cor == "Preto"
    assert "estoque" in json.dumps(r.conteudo, ensure_ascii=False).lower()


async def test_registrar_interesse_aceita_informacao_parcial() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", {"modelo": "iPhone 16", "capacidade": None, "cor": None}),
        ("registrar_interesse", {"modelo": "iPhone 16", "capacidade": "256GB", "cor": None}),
    )
    assert estado.ficha.interesse.capacidade == Capacidade(256)


async def test_modelo_desconhecido_informa_o_que_a_loja_trabalha() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "Galaxy S24", "capacidade": None, "cor": None}, VAZIO
    )
    assert r.erro
    assert r.estado == VAZIO
    texto = json.dumps(r.conteudo, ensure_ascii=False)
    assert "iPhone" in texto
    assert "iPhone 16" in texto  # modelo que existe no estoque


def _de_outra_marca(sku: str, modelo: str, marca: str, gb: int = 128) -> ItemEstoque:
    return ItemEstoque(
        sku=sku,
        modelo=ModeloAparelho.de(modelo, marca),
        capacidade=Capacidade(gb),
        cor="Preto",
        condicao=Condicao.NOVO,
        preco_pix=Dinheiro(Decimal(900)),
        quantidade=1,
    )


MULTIMARCA = [
    *ITENS_PADRAO,
    _de_outra_marca("SS-A07", "Galaxy A07 4G", "Samsung"),
    _de_outra_marca("SS-S23", "Galaxy S23", "Samsung", 256),
]


async def _ambiente_multimarca() -> Ambiente:
    """Mesmo estoque na porta do agente e no estoque local da loja (de onde vem o catalogo)."""
    amb = await criar_ambiente(MULTIMARCA)
    linhas = [
        LinhaEstoqueLocal(
            i.sku, i.modelo, i.capacidade, i.cor or "", i.condicao, i.preco_pix, i.quantidade, None
        )
        for i in MULTIMARCA
    ]
    await amb.casos.estoque.substituir(amb.loja_id, linhas)
    return amb


async def test_outra_marca_do_estoque_e_aceita_como_interesse() -> None:
    amb = await _ambiente_multimarca()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "galaxy a07", "capacidade": None, "cor": None}, VAZIO
    )
    assert not r.erro, r.conteudo
    assert r.estado.ficha.interesse.modelo == ModeloAparelho.de("Galaxy A07 4G", "Samsung")


async def test_consultar_estoque_encontra_outra_marca() -> None:
    amb = await _ambiente_multimarca()
    r = await amb.rodar(
        "consultar_estoque",
        {"modelo": "Samsung Galaxy A07", "capacidade": None, "cor": None},
        VAZIO,
    )
    assert not r.erro, r.conteudo
    assert r.conteudo["total_opcoes"] == 1
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "SS-A07"


async def test_modelo_ambiguo_pede_para_escolher_entre_os_do_estoque() -> None:
    amb = await _ambiente_multimarca()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "galaxy", "capacidade": None, "cor": None}, VAZIO
    )
    assert r.erro
    assert r.estado == VAZIO
    texto = json.dumps(r.conteudo, ensure_ascii=False)
    assert "Galaxy A07 4G" in texto and "Galaxy S23" in texto
    assert "trabalha com iPhone" not in texto


async def test_iphone_conhecido_continua_aceito_mesmo_sem_estoque() -> None:
    amb = await _ambiente_multimarca()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "iPhone 17 Pro", "capacidade": None, "cor": None}, VAZIO
    )
    assert not r.erro
    assert r.estado.ficha.interesse.modelo == ModeloAparelho.de("iPhone 17 Pro")


async def test_capacidade_invalida_e_erro_amigavel() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "iPhone 16", "capacidade": "muito", "cor": None}, VAZIO
    )
    assert r.erro
    assert r.estado == VAZIO


async def test_mudar_de_aparelho_desfaz_a_confirmacao_do_item() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(VAZIO, ("registrar_interesse", INTERESSE_16))
    estado, _ = await amb.seq(estado, ("consultar_estoque", INTERESSE_16))
    assert estado.ficha.interesse.sku_estoque_confirmado == "IP16-128-PRETO"
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "iPhone 15", "capacidade": "128GB", "cor": None}, estado
    )
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None
    assert not r.estado.estoque_consultado


# --- consultar_estoque -------------------------------------------------------------------


async def test_consultar_estoque_nunca_devolve_preco() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 15", "capacidade": None, "cor": None}, VAZIO
    )
    assert not r.erro
    texto = json.dumps(r.conteudo, ensure_ascii=False)
    assert "R$" not in texto
    assert "preco" not in texto.lower() and "preço" not in texto.lower()
    for preco in ("4199", "4.199", "4830"):
        assert preco not in texto
    # iPhone 15 so tem 128GB: pula direto para as cores dessa capacidade
    assert r.conteudo["etapa"] == "cores"
    assert {c["cor"] for c in r.conteudo["cores"]} == {"Rosa", "Preto"}
    assert r.estado.estoque_consultado


async def test_consultar_estoque_nunca_devolve_preco_em_nenhuma_etapa() -> None:
    amb = await criar_ambiente(ITENS_16_VARIOS)
    for cap, cor in [(None, None), ("128GB", None), ("128GB", "Preto"), ("256GB", "Rosa")]:
        r = await amb.rodar(
            "consultar_estoque", {"modelo": "iPhone 16", "capacidade": cap, "cor": cor}, VAZIO
        )
        assert not r.erro
        texto = json.dumps(r.conteudo, ensure_ascii=False).lower()
        assert "r$" not in texto and "preco" not in texto and "preço" not in texto
        for preco in ("7230", "4830", "4130", "5430"):
            assert preco not in texto


async def test_consultar_estoque_com_varias_opcoes_nao_confirma() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 15", "capacidade": "128GB", "cor": None}, VAZIO
    )
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None
    assert r.conteudo["confirmado"] is False
    assert r.conteudo["etapa"] == "cores"


async def test_consultar_estoque_com_uma_opcao_confirma_o_sku() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 16", "capacidade": "128GB", "cor": None}, VAZIO
    )
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "IP16-128-PRETO"
    assert r.conteudo["confirmado"] is True
    assert r.estado.ficha.interesse.modelo == ModeloAparelho.de("iPhone 16")


async def test_consultar_usa_o_interesse_ja_registrado() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(VAZIO, ("registrar_interesse", INTERESSE_16))
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 16", "capacidade": None, "cor": None}, estado
    )
    # capacidade veio do interesse: so o 128GB (um item so, confirmado)
    assert r.conteudo["sku_confirmado"] == "IP16-128-PRETO"


async def test_seminovo_mostra_bateria_e_esgotado_nao_aparece() -> None:
    amb = await criar_ambiente()
    r13 = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 13", "capacidade": None, "cor": None}, VAZIO
    )
    assert r13.conteudo["sku_confirmado"] == "IP13-128-AZUL"
    assert r13.conteudo["opcoes"][0]["bateria_pct"] == 88
    r14 = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 14", "capacidade": None, "cor": None}, VAZIO
    )
    assert r14.conteudo["opcoes"] == []
    assert r14.estado.ficha.interesse.sku_estoque_confirmado is None


async def test_estoque_indisponivel_e_resposta_tipada_sem_mudar_estado() -> None:
    amb = await criar_ambiente(estoque=EstoqueFora())
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 16", "capacidade": None, "cor": None}, VAZIO
    )
    assert r.erro
    assert r.conteudo["status"] == "estoque_indisponivel"
    assert "agora" in r.conteudo["mensagem"]
    assert r.estado == VAZIO
    assert not r.estado.estoque_consultado


async def test_consultar_modelo_desconhecido_e_erro() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "Moto G", "capacidade": None, "cor": None}, VAZIO
    )
    assert r.erro
    assert "iPhone" in json.dumps(r.conteudo, ensure_ascii=False)


# --- consultar_estoque em etapas: capacidades, depois cores -----------------------------------


async def _consulta_16_bruto(
    cap: str | None,
    cor: str | None = None,
    estado: EstadoAtendimento = VAZIO,
    condicao: str | None = None,
) -> tuple[Ambiente, ResultadoFerramenta]:
    amb = await criar_ambiente(ITENS_16_VARIOS)
    entrada = {"modelo": "iPhone 16", "capacidade": cap, "cor": cor, "condicao": condicao}
    return amb, await amb.rodar("consultar_estoque", entrada, estado)


async def _consulta_16(
    cap: str | None,
    cor: str | None = None,
    estado: EstadoAtendimento = VAZIO,
    condicao: str | None = None,
) -> tuple[Ambiente, ResultadoFerramenta]:
    amb, r = await _consulta_16_bruto(cap, cor, estado, condicao)
    assert not r.erro, r.conteudo
    return amb, r


async def test_cliente_pede_novo_e_a_consulta_traz_so_novos() -> None:
    _, r = await _consulta_16("128GB", condicao="novo")
    cores = r.conteudo["cores"]
    assert {c["condicao"] for c in cores} == {"novo"}
    assert {c["cor"] for c in cores} == {"Preto", "Branco"}
    assert r.estado.ficha.interesse.condicao is Condicao.NOVO


async def test_novo_na_cor_escolhida_confirma_o_item_novo() -> None:
    _, r = await _consulta_16("128GB", "Preto", condicao="novo")
    assert r.conteudo["confirmado"] is True
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "IP16-128-PRETO"


async def test_condicao_registrada_vale_nas_consultas_seguintes() -> None:
    amb = await criar_ambiente(ITENS_16_VARIOS)
    estado, (_, r) = await amb.seq(
        VAZIO,
        ("registrar_interesse", {"modelo": "iPhone 16", "capacidade": "128GB", "condicao": "novo"}),
        ("consultar_estoque", {"modelo": "iPhone 16", "capacidade": None, "cor": "Preto"}),
    )
    assert estado.ficha.interesse.sku_estoque_confirmado == "IP16-128-PRETO"
    assert all(o["condicao"] == "novo" for o in r.conteudo.get("opcoes", []))


async def test_condicao_sem_estoque_avisa_e_mostra_o_que_existe() -> None:
    _, r = await _consulta_16("256GB", condicao="seminovo")
    assert r.conteudo["etapa"] == "capacidades"
    assert "seminovo" in r.conteudo["mensagem"]
    assert r.estado.ficha.interesse.condicao is None


async def test_mudar_a_condicao_desfaz_a_confirmacao_do_item() -> None:
    amb = await criar_ambiente(ITENS_16_VARIOS)
    estado, _ = await amb.seq(
        VAZIO,
        (
            "consultar_estoque",
            {"modelo": "iPhone 16", "capacidade": "128GB", "cor": "Preto", "condicao": "novo"},
        ),
        ("registrar_interesse", {"modelo": "iPhone 16", "condicao": "seminovo"}),
    )
    assert estado.ficha.interesse.sku_estoque_confirmado is None
    assert estado.ficha.interesse.condicao is Condicao.SEMINOVO


async def test_novos_iguais_em_skus_diferentes_confirma_sem_perguntar() -> None:
    itens = [
        item("A-1", "iPhone 16", 128, "Branco", 4830, qtd=1),
        item("A-2", "iPhone 16", 128, "Branco", 4830, qtd=1),
        item(
            "A-3", "iPhone 16", 128, "Branco", 4130, qtd=1, condicao=Condicao.SEMINOVO, bateria=88
        ),
    ]
    amb = await criar_ambiente(itens)
    r = await amb.rodar(
        "consultar_estoque",
        {"modelo": "iPhone 16", "capacidade": "128GB", "cor": "Branco", "condicao": "novo"},
        VAZIO,
    )
    assert r.conteudo["confirmado"] is True
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "A-1"


async def test_condicao_invalida_e_erro_amigavel() -> None:
    _, r = await _consulta_16_bruto("128GB", condicao="usado")
    assert r.erro


async def test_sem_capacidade_lista_todas_em_ordem_crescente() -> None:
    _, r = await _consulta_16(None)
    c = r.conteudo
    assert c["etapa"] == "capacidades"
    assert [x["capacidade"] for x in c["capacidades"]] == ["128GB", "256GB", "512GB"]
    assert "capacidade" in c["mensagem"].lower() and "pergunte" in c["mensagem"].lower()
    assert c["confirmado"] is False
    assert "opcoes" not in c
    ficha = r.estado.ficha.interesse
    assert ficha.sku_estoque_confirmado is None and ficha.capacidade is None
    assert r.estado.estoque_consultado


async def test_capacidades_trazem_condicoes_e_unidades() -> None:
    _, r = await _consulta_16(None)
    por_cap = {x["capacidade"]: x["condicoes"] for x in r.conteudo["capacidades"]}
    assert por_cap["128GB"] == [
        {"condicao": "novo", "unidades": 3},
        {"condicao": "seminovo", "unidades": 1},
    ]
    assert por_cap["256GB"] == [
        {"condicao": "novo", "unidades": 4}
    ]  # Preto 2 + Rosa 2; o esgotado nao conta
    assert por_cap["512GB"] == [{"condicao": "novo", "unidades": 3}]


async def test_com_capacidade_sem_cor_lista_so_as_cores_dela() -> None:
    _, r = await _consulta_16("256GB")
    c = r.conteudo
    assert c["etapa"] == "cores"
    assert c["capacidade"] == "256GB"
    assert {x["cor"] for x in c["cores"]} == {"Preto", "Rosa"}  # Azul esgotado; Branco e 128GB
    assert "cor" in c["mensagem"].lower() and "pergunte" in c["mensagem"].lower()
    assert c["confirmado"] is False
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None
    assert r.estado.ficha.interesse.capacidade == Capacidade(256)


async def test_cores_mostram_a_condicao_e_as_unidades() -> None:
    _, r = await _consulta_16("128GB")
    assert r.conteudo["cores"] == [
        {"cor": "Preto", "condicao": "novo", "unidades": 2},
        {"cor": "Branco", "condicao": "novo", "unidades": 1},
        {"cor": "Preto", "condicao": "seminovo", "unidades": 1},
    ]


async def test_com_capacidade_e_cor_varios_itens_pede_escolha_com_bateria() -> None:
    _, r = await _consulta_16("128GB", "Preto")
    c = r.conteudo
    assert c["etapa"] == "opcoes"
    assert {o["sku"] for o in c["opcoes"]} == {"IP16-128-PRETO", "IP16-128-PRETO-SEMI"}
    semi = next(o for o in c["opcoes"] if o["condicao"] == "seminovo")
    assert semi["bateria_pct"] == 91
    assert "confirmar_item" in c["mensagem"]
    assert c["confirmado"] is False
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None


async def test_com_capacidade_e_cor_item_unico_e_confirmado() -> None:
    _, r = await _consulta_16("128GB", "Branco")
    assert r.conteudo["confirmado"] is True
    assert r.conteudo["sku_confirmado"] == "IP16-128-BRANCO"
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "IP16-128-BRANCO"


async def test_cor_aceita_variacao_de_caixa_e_acento() -> None:
    _, r = await _consulta_16("256GB", "rosa")
    assert r.estado.ficha.interesse.sku_estoque_confirmado == "IP16-256-ROSA"


async def test_capacidade_inexistente_diz_quais_existem_e_nao_grava() -> None:
    _, r = await _consulta_16("64GB")
    c = r.conteudo
    assert c["etapa"] == "capacidades"
    assert [x["capacidade"] for x in c["capacidades"]] == ["128GB", "256GB", "512GB"]
    assert "64GB" in c["mensagem"]
    assert r.estado.ficha.interesse.capacidade is None
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None


async def test_cor_inexistente_na_capacidade_lista_as_cores_dela() -> None:
    _, r = await _consulta_16("256GB", "Verde")
    c = r.conteudo
    assert c["etapa"] == "cores"
    assert {x["cor"] for x in c["cores"]} == {"Preto", "Rosa"}
    assert "Verde" in c["mensagem"]
    assert r.estado.ficha.interesse.cor is None
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None


async def test_capacidade_unica_no_modelo_vai_direto_para_as_cores() -> None:
    amb = await criar_ambiente(
        [
            item("A-128-PRETO", "iPhone 13", 128, "Preto", 2399),
            item("A-128-AZUL", "iPhone 13", 128, "Azul", 2399),
        ]
    )
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 13", "capacidade": None, "cor": None}, VAZIO
    )
    assert r.conteudo["etapa"] == "cores"
    assert r.conteudo["capacidade"] == "128GB"
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None


async def test_cor_de_condicoes_diferentes_sem_outras_cores_mostra_as_opcoes() -> None:
    amb = await criar_ambiente(
        [
            item("A-128-PRETO", "iPhone 13", 128, "Preto", 2399),
            item(
                "A-128-PRETO-S",
                "iPhone 13",
                128,
                "Preto",
                1999,
                condicao=Condicao.SEMINOVO,
                bateria=85,
            ),
        ]
    )
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 13", "capacidade": "128GB", "cor": None}, VAZIO
    )
    assert r.conteudo["etapa"] == "opcoes"
    assert len(r.conteudo["opcoes"]) == 2


async def test_capacidade_do_interesse_registrado_segue_para_as_cores() -> None:
    amb = await criar_ambiente(ITENS_16_VARIOS)
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", {"modelo": "iPhone 16", "capacidade": "256GB", "cor": None}),
    )
    r = await amb.rodar(
        "consultar_estoque", {"modelo": "iPhone 16", "capacidade": None, "cor": None}, estado
    )
    assert r.conteudo["etapa"] == "cores"
    assert r.conteudo["capacidade"] == "256GB"


async def test_fluxo_completo_capacidade_depois_cor_depois_confirma() -> None:
    amb = await criar_ambiente(ITENS_16_VARIOS)
    estado, (r1, r2, r3) = await amb.seq(
        VAZIO,
        ("consultar_estoque", {"modelo": "iPhone 16", "capacidade": None, "cor": None}),
        ("consultar_estoque", {"modelo": "iPhone 16", "capacidade": "128GB", "cor": None}),
        ("consultar_estoque", {"modelo": "iPhone 16", "capacidade": "128GB", "cor": "Preto"}),
    )
    assert [r1.conteudo["etapa"], r2.conteudo["etapa"], r3.conteudo["etapa"]] == [
        "capacidades",
        "cores",
        "opcoes",
    ]
    r4 = await amb.rodar("confirmar_item", {"sku": "IP16-128-PRETO"}, estado)
    assert r4.estado.ficha.interesse.sku_estoque_confirmado == "IP16-128-PRETO"


# --- confirmar_item ----------------------------------------------------------------------


async def test_confirmar_item_valido() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("confirmar_item", {"sku": "IP15-128-ROSA"}, VAZIO)
    assert not r.erro
    i = r.estado.ficha.interesse
    assert i.sku_estoque_confirmado == "IP15-128-ROSA"
    assert i.modelo == ModeloAparelho.de("iPhone 15")
    assert i.capacidade == Capacidade(128)
    assert i.cor == "Rosa"
    assert r.estado.estoque_consultado
    sem_preco = json.dumps(r.conteudo, ensure_ascii=False)
    assert "R$" not in sem_preco and "4199" not in sem_preco


async def test_confirmar_item_sku_inventado_e_recusado() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("confirmar_item", {"sku": "SKU-FANTASMA"}, VAZIO)
    assert r.erro
    assert r.estado == VAZIO


async def test_confirmar_item_esgotado_e_recusado() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("confirmar_item", {"sku": "IP14-256-ROXO"}, VAZIO)
    assert r.erro
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None


async def test_confirmar_item_com_estoque_fora() -> None:
    amb = await criar_ambiente(estoque=EstoqueFora())
    r = await amb.rodar("confirmar_item", {"sku": "X"}, VAZIO)
    assert r.erro
    assert r.conteudo["status"] == "estoque_indisponivel"
    assert r.estado == VAZIO


# --- registrar_usado ---------------------------------------------------------------------


async def test_registrar_usado_completo() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_usado", USADO_EXEMPLO, VAZIO)
    assert not r.erro
    f = r.estado.ficha
    assert f.tem_troca is True
    assert f.usado.modelo == ModeloAparelho.de("iPhone 16")
    assert f.usado.capacidade == Capacidade(128)
    assert f.usado.tela_danificada is True
    assert f.usado.bateria_pct == 79
    assert f.usado.outros_defeitos == ()
    assert f.usado.peca_trocada is False


def _usado_nulo(**campos: object) -> dict[str, object]:
    base: dict[str, object] = {k: None for k in USADO_EXEMPLO if k != "tem_troca"} | {
        "tem_troca": True
    }
    return base | campos


async def test_registrar_usado_parcial_vai_se_completando() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_usado", _usado_nulo(modelo="iPhone 12")),
        ("registrar_usado", _usado_nulo(capacidade="128GB", tela_danificada=False)),
        ("registrar_usado", _usado_nulo(bateria_pct=85)),
    )
    u = estado.ficha.usado
    assert u.modelo == ModeloAparelho.de("iPhone 12")
    assert u.capacidade == Capacidade(128)
    assert u.tela_danificada is False
    assert u.bateria_pct == 85
    assert u.traseira_danificada is None  # nao informado continua pendente


async def test_sem_troca_limpa_o_usado() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_usado", _usado_nulo(tem_troca=False)),
    )
    assert estado.ficha.tem_troca is False
    assert estado.ficha.usado.modelo is None


async def test_bateria_fora_de_0_a_100_e_erro_e_nao_grava() -> None:
    amb = await criar_ambiente()
    for ruim in (101, -1, "cem", 79.5, True):
        r = await amb.rodar("registrar_usado", _usado_nulo(bateria_pct=ruim), VAZIO)  # type: ignore[arg-type]
        assert r.erro, ruim
        assert r.estado == VAZIO


def _recusado(r: ResultadoFerramenta, aparelho: str) -> None:
    """Fora da tabela de troca: a loja nao aceita, a ficha segue sem troca e a conversa avanca."""
    assert not r.erro
    assert r.estado.ficha.tem_troca is False
    assert r.estado.ficha.usado == UsadoInformado()
    troca = r.conteudo["troca"]
    assert troca["status"] == "nao_aceito"
    assert troca["aparelho"] == aparelho
    assert "não aceita" in troca["mensagem"] and aparelho in troca["mensagem"]
    assert "avaliad" not in json.dumps(troca, ensure_ascii=False)
    assert not [f for f in r.conteudo["faltam"] if "usado" in f or "troca" in f]
    assert "data prevista da compra" in r.conteudo["faltam"]


async def test_usado_de_outra_marca_fora_da_tabela_nao_e_aceito() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_usado", _usado_nulo(modelo="Samsung S21"), VAZIO)
    _recusado(r, "Samsung S21")


async def test_modelo_fora_da_tabela_de_troca_nao_e_aceito_e_segue_para_a_compra() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_usado", _usado_nulo(modelo="iPhone XR"), VAZIO)
    _recusado(r, "iPhone XR")


async def test_capacidade_fora_da_tabela_nao_e_aceita() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_usado", _usado_nulo(modelo="iPhone 12", capacidade="32GB"), VAZIO
    )
    _recusado(r, "iPhone 12 32GB")


async def test_modelo_da_tabela_segue_com_as_perguntas_de_estado() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_usado", _usado_nulo(modelo="iPhone 12"), VAZIO)
    assert r.estado.ficha.tem_troca is True
    assert r.estado.ficha.usado.avaliacao_na_loja is False
    assert "troca" not in r.conteudo
    assert "capacidade do aparelho usado" in r.conteudo["faltam"]


async def test_depois_da_recusa_outro_aparelho_da_tabela_entra_na_troca() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_usado", _usado_nulo(modelo="iPhone XR")),
        ("registrar_usado", _usado_nulo(modelo="iPhone 12")),
    )
    assert estado.ficha.tem_troca is True
    assert estado.ficha.usado.modelo == ModeloAparelho.de("iPhone 12")
    assert estado.ficha.usado.avaliacao_na_loja is False


async def test_avaliacao_do_usado_nao_pergunta_camera_defeitos_nem_peca() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_usado",
        _usado_nulo(
            modelo="iPhone 16",
            capacidade="128GB",
            tela_danificada=False,
            traseira_danificada=False,
            carcaca_marcada=False,
        ),
        VAZIO,
    )
    assert [f for f in r.conteudo["faltam"] if "usado" in f] == ["saúde da bateria do usado"]


async def _proposta_com_usado(amb: Ambiente, usado: dict[str, object]) -> ResultadoFerramenta:
    _, resultados = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", usado),
        ("registrar_compra", COMPRA_HOJE_12X),
        ("calcular_proposta", {}),
    )
    return resultados[-1]


async def test_proposta_com_usado_fora_da_tabela_sai_sem_troca() -> None:
    amb = await criar_ambiente()
    r = await _proposta_com_usado(amb, _usado_nulo(modelo="iPhone XR"))
    assert r.conteudo["bloqueado"] is False
    assert r.conteudo["troca"]["status"] == "sem_troca"


async def test_proposta_desconta_o_usado_avaliado_so_com_as_quatro_perguntas() -> None:
    amb = await criar_ambiente()
    usado = _usado_nulo(
        modelo="iPhone 12",
        capacidade="128GB",
        tela_danificada=False,
        traseira_danificada=True,
        carcaca_marcada=False,
        bateria_pct=88,
    )
    r = await _proposta_com_usado(amb, usado)
    assert r.conteudo["bloqueado"] is False
    assert r.conteudo["troca"]["status"] == "avaliada"


# --- registrar_compra --------------------------------------------------------------------


def _compra_nula(**campos: object) -> dict[str, object]:
    base: dict[str, object] = dict.fromkeys(COMPRA_HOJE_12X)
    return base | campos


async def test_registrar_compra_grava_pagamento() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_compra", COMPRA_HOJE_12X, VAZIO)
    assert not r.erro
    f = r.estado.ficha
    assert f.data_prevista_compra == HOJE
    assert f.pagamento.tipo is TipoPagamento.CREDITO
    assert f.pagamento.parcelas == 12
    assert f.pagamento.bandeira is Bandeira.MASTERCARD


async def test_data_no_passado_e_recusada() -> None:
    amb = await criar_ambiente()
    ontem = (HOJE - timedelta(days=1)).isoformat()
    r = await amb.rodar("registrar_compra", _compra_nula(data_prevista=ontem), VAZIO)
    assert r.erro
    assert r.estado == VAZIO


async def test_data_invalida_e_recusada() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_compra", _compra_nula(data_prevista="semana que vem"), VAZIO)
    assert r.erro


async def test_parcelas_acima_do_maximo_da_loja() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_compra", _compra_nula(tipo_pagamento="credito", parcelas=19), VAZIO
    )
    assert r.erro  # a loja demo aceita ate 18x
    assert r.estado == VAZIO
    ok = await amb.rodar(
        "registrar_compra", _compra_nula(tipo_pagamento="credito", parcelas=18), VAZIO
    )
    assert not ok.erro


async def test_parcelas_zero_ou_negativa_e_recusada() -> None:
    amb = await criar_ambiente()
    for ruim in (0, -3, "doze"):
        r = await amb.rodar("registrar_compra", _compra_nula(parcelas=ruim), VAZIO)
        assert r.erro, ruim


async def test_bandeira_desconhecida_e_recusada() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_compra", _compra_nula(bandeira="Banco Imaginario"), VAZIO)
    assert r.erro


async def test_tipo_de_pagamento_invalido() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_compra", _compra_nula(tipo_pagamento="fiado"), VAZIO)
    assert r.erro


async def test_entrada_mais_credito_aceita_quando_a_loja_aceita() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_compra",
        _compra_nula(
            tipo_pagamento="entrada_mais_credito",
            parcelas=10,
            bandeira="Visa",
            entrada="R$ 1.000,00",
        ),
        VAZIO,
    )
    assert not r.erro
    assert r.estado.ficha.pagamento.entrada == Dinheiro(Decimal(1000))


async def test_entrada_mais_credito_recusada_quando_a_loja_nao_aceita() -> None:
    amb = await criar_ambiente()
    preco = await amb.casos.obter_preco(amb.loja_id)
    assert preco is not None
    from dataclasses import replace

    from app.application.config.entradas import EntradaPreco

    r_ = preco.regras
    await amb.casos.atualizar_preco(
        amb.loja_id,
        EntradaPreco(
            max_parcelas=r_.max_parcelas,
            repassa_taxa=True,
            desconto_pix_tipo="nenhum",
            desconto_pix_valor=None,
            aceita_entrada_mais_cartao=False,
            desconto_teto=Decimal(100),
            desconto_degrau=Decimal(50),
            oportunidade_ativa=True,
            oportunidade_dias_minimos=14,
            oportunidade_valor=Decimal(100),
            oportunidade_conta_no_teto=False,
        ),
    )
    assert replace  # silencia import
    r = await amb.rodar(
        "registrar_compra",
        _compra_nula(
            tipo_pagamento="entrada_mais_credito", parcelas=10, bandeira="Visa", entrada="500"
        ),
        VAZIO,
    )
    assert r.erro


async def test_entrada_invalida() -> None:
    amb = await criar_ambiente()
    for ruim in ("muito", "-100"):
        r = await amb.rodar("registrar_compra", _compra_nula(entrada=ruim), VAZIO)
        assert r.erro, ruim


async def test_trocar_para_pix_descarta_parcelas_e_bandeira() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_compra", COMPRA_HOJE_12X),
        ("registrar_compra", _compra_nula(tipo_pagamento="pix")),
    )
    p = estado.ficha.pagamento
    assert (p.tipo, p.parcelas, p.bandeira) == (TipoPagamento.PIX, None, None)


async def test_registrar_compra_informa_o_que_falta() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_compra", COMPRA_HOJE_12X, VAZIO)
    assert "faltam" in r.conteudo
    assert r.conteudo["faltam"]  # ainda falta aparelho etc.


# --- liberar_desconto --------------------------------------------------------------------


async def _com_proposta(amb):  # type: ignore[no-untyped-def]
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", COMPRA_HOJE_12X),
        ("calcular_proposta", {}),
    )
    return estado


async def test_proposta_com_pagamento_escolhido_manda_fechar_e_enviar_o_endereco() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    r = await amb.rodar("calcular_proposta", {}, estado)
    passo = r.conteudo["proximo_passo"]
    assert "fechar_acordo" in passo
    assert "endereço" in passo
    assert "desconto" in passo  # diz para NAO oferecer desconto


async def test_liberar_desconto_antes_da_proposta_e_bloqueado() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("liberar_desconto", {"motivo": "cliente pediu desconto"}, VAZIO)
    assert r.conteudo["bloqueado"] is True
    assert r.estado.desconto == EstadoDesconto()
    sem_valores(r.conteudo)


async def test_liberar_desconto_libera_degrau_e_recalcula() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    r = await amb.rodar("liberar_desconto", {"motivo": "pediu desconto"}, estado)
    assert not r.erro
    assert r.estado.desconto.liberado == Dinheiro(Decimal(50))
    assert r.conteudo["proposta"]["desconto"]["negociado"] == "R$ 50,00"
    assert r.conteudo["proposta"]["bloqueado"] is False
    assert r.estado.ultima_proposta == r.conteudo["proposta"]


async def test_desconto_nunca_passa_do_teto() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    teto = (await amb.casos.obter_preco(amb.loja_id)).politica.teto  # type: ignore[union-attr]
    ultimo = None
    for _ in range(6):
        r = await amb.rodar("liberar_desconto", {"motivo": "mais um"}, estado)
        estado = r.estado
        ultimo = r
        assert estado.desconto.liberado <= teto
    assert ultimo is not None
    assert estado.desconto.liberado == teto
    assert ultimo.conteudo["teto_atingido"] is True
    assert "melhor" in json.dumps(ultimo.conteudo, ensure_ascii=False).lower()


async def test_liberar_desconto_se_estoque_cai_nao_libera() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    amb.ctx = type(amb.ctx)(
        loja_id=amb.ctx.loja_id,
        lead_id=amb.ctx.lead_id,
        estoque=EstoqueFora(),
        config=amb.ctx.config,
        hoje=amb.ctx.hoje,
    )
    r = await amb.rodar("liberar_desconto", {"motivo": "x"}, estado)
    assert r.erro
    assert r.estado.desconto == EstadoDesconto()


async def test_liberar_desconto_exige_motivo() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    r = await amb.rodar("liberar_desconto", {"motivo": "  "}, estado)
    assert r.erro


# --- chamar_vendedor ---------------------------------------------------------------------


async def test_chamar_vendedor_marca_handoff() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("chamar_vendedor", {"motivo": "quer fechar a compra"}, VAZIO)
    assert not r.erro
    assert r.estado.handoff_solicitado
    assert r.estado.motivo_handoff == "quer fechar a compra"
    assert r.eventos[0]["nome"] == "chamar_vendedor"


async def test_chamar_vendedor_repetido_mantem_o_primeiro_motivo() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("chamar_vendedor", {"motivo": "primeiro"}),
        ("chamar_vendedor", {"motivo": "segundo"}),
    )
    assert estado.motivo_handoff == "primeiro"


async def test_registrar_interesse_que_manda_consultar_o_estoque_nao_sugere_pergunta() -> None:
    """A pergunta vem do consultar_estoque; duas fontes fazem o modelo perguntar duas vezes."""
    amb = await criar_ambiente()
    r = await amb.rodar(
        "registrar_interesse", {"modelo": "iPhone 16", "capacidade": None, "cor": None}, VAZIO
    )
    assert "consultar_estoque" in r.conteudo["proximo_passo"]
    assert "proxima_pergunta" not in r.conteudo
    assert r.conteudo["faltam"]  # as pendencias continuam
