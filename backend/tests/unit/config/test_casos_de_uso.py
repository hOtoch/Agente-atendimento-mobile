"""Casos de uso da configuracao da loja, com repositorios em memoria."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.entradas import (
    EntradaLinhaEstoque,
    EntradaLinhaMapeamento,
    EntradaLinhaTroca,
    EntradaPreco,
    EntradaTaxa,
)
from app.application.config.memoria import MemoriaIntegracaoEstoque, criar_casos_em_memoria
from app.application.config.modelos import (
    ErrosDeValidacao,
    ItemChecklist,
    LojaNaoEncontrada,
    PerfilLoja,
)
from app.domain.bandeira import Bandeira
from app.domain.pagamento import DescontoPixPercentual, DescontoPixValor
from app.domain.troca import SEM
from app.domain.valores import Dinheiro

D = Decimal


def preco_valido(**sobre: object) -> EntradaPreco:
    base: dict[str, object] = {
        "max_parcelas": 18,
        "repassa_taxa": True,
        "desconto_pix_tipo": "percentual",
        "desconto_pix_valor": D("5"),
        "aceita_entrada_mais_cartao": True,
        "desconto_teto": D("100"),
        "desconto_degrau": D("50"),
        "oportunidade_ativa": True,
        "oportunidade_dias_minimos": 14,
        "oportunidade_valor": D("100"),
        "oportunidade_conta_no_teto": False,
    }
    base.update(sobre)
    return EntradaPreco(**base)  # type: ignore[arg-type]


def linha_troca(**sobre: object) -> EntradaLinhaTroca:
    base: dict[str, object] = {
        "marca": "Apple",
        "modelo": "iphone 16",
        "capacidade_gb": 128,
        "valor_sem_detalhes": D("3100"),
        "desconto_tela": D("600"),
        "desconto_tela_sem": False,
        "desconto_traseira": D("300"),
        "desconto_traseira_sem": False,
        "desconto_carcaca": D("0"),
        "desconto_carcaca_sem": False,
        "desconto_bateria": D("190"),
        "desconto_bateria_sem": False,
        "limite_bateria_pct": 80,
    }
    base.update(sobre)
    return EntradaLinhaTroca(**base)  # type: ignore[arg-type]


def linha_estoque(**sobre: object) -> EntradaLinhaEstoque:
    base: dict[str, object] = {
        "sku": "IP16-128-PT",
        "marca": "Apple",
        "modelo": "iPhone 16",
        "capacidade_gb": 128,
        "cor": "Preto",
        "condicao": "novo",
        "preco_pix": D("4500"),
        "quantidade": 3,
        "bateria_pct": None,
    }
    base.update(sobre)
    return EntradaLinhaEstoque(**base)  # type: ignore[arg-type]


def perfil_valido() -> PerfilLoja:
    return PerfilLoja(
        nome_exibicao="Loja Centro",
        tom_de_voz="Simpatico e direto",
        endereco="Rua A, 10",
        horarios={"seg-sex": "09:00-18:00"},
        whatsapp_contato="5511999990000",
    )


@pytest.fixture
def casos() -> CasosDeUsoConfig:
    return criar_casos_em_memoria()


async def nova_loja(casos: CasosDeUsoConfig) -> UUID:
    return await casos.criar_loja("Loja Teste")


def caminhos(exc: pytest.ExceptionInfo[ErrosDeValidacao]) -> dict[str, str]:
    return {e.caminho: e.mensagem for e in exc.value.erros}


# --- loja -------------------------------------------------------------------------------------


async def test_loja_inexistente_levanta_nao_encontrada(casos: CasosDeUsoConfig) -> None:
    with pytest.raises(LojaNaoEncontrada):
        await casos.obter_perfil(uuid4())


async def test_criar_loja_exige_nome(casos: CasosDeUsoConfig) -> None:
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.criar_loja("   ")
    assert "nome" in caminhos(exc)


# --- perfil -----------------------------------------------------------------------------------


async def test_perfil_ida_e_volta(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    assert await casos.obter_perfil(loja) is None
    await casos.atualizar_perfil(loja, perfil_valido())
    assert await casos.obter_perfil(loja) == perfil_valido()


async def test_perfil_invalido(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    ruim = PerfilLoja("", "", "", {}, "123")
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_perfil(loja, ruim)
    assert {"nome_exibicao", "whatsapp_contato"} <= set(caminhos(exc))


# --- preco ------------------------------------------------------------------------------------


async def test_preco_ida_e_volta(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    assert await casos.obter_preco(loja) is None
    salvo = await casos.atualizar_preco(loja, preco_valido())
    assert await casos.obter_preco(loja) == salvo
    assert salvo.regras.max_parcelas == 18
    assert salvo.regras.desconto_pix == DescontoPixPercentual(D("5"))
    assert salvo.politica.teto == Dinheiro.de("100")
    assert salvo.oportunidade.valor == Dinheiro.de("100")


async def test_preco_com_desconto_pix_em_valor(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    salvo = await casos.atualizar_preco(
        loja, preco_valido(desconto_pix_tipo="valor", desconto_pix_valor=D("80"))
    )
    assert salvo.regras.desconto_pix == DescontoPixValor(Dinheiro.de("80"))


@pytest.mark.parametrize("parcelas", [0, 22, -1])
async def test_preco_max_parcelas_fora_de_1_a_21(casos: CasosDeUsoConfig, parcelas: int) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_preco(loja, preco_valido(max_parcelas=parcelas))
    assert "max_parcelas" in caminhos(exc)


@pytest.mark.parametrize("pct", [D("-1"), D("100.01")])
async def test_preco_percentual_pix_fora_de_0_a_100(casos: CasosDeUsoConfig, pct: Decimal) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_preco(loja, preco_valido(desconto_pix_valor=pct))
    assert "desconto_pix_valor" in caminhos(exc)


async def test_preco_varios_erros_de_uma_vez(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    ruim = preco_valido(
        max_parcelas=30,
        desconto_pix_tipo="xyz",
        desconto_teto=D("-1"),
        desconto_degrau=D("0"),
        oportunidade_dias_minimos=-3,
        oportunidade_valor=D("-5"),
    )
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_preco(loja, ruim)
    assert {
        "max_parcelas",
        "desconto_pix_tipo",
        "desconto_teto",
        "desconto_degrau",
        "oportunidade_dias_minimos",
        "oportunidade_valor",
    } <= set(caminhos(exc))


async def test_preco_invalido_nao_grava(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_preco(loja, preco_valido())
    with pytest.raises(ErrosDeValidacao):
        await casos.atualizar_preco(loja, preco_valido(max_parcelas=99))
    atual = await casos.obter_preco(loja)
    assert atual is not None
    assert atual.regras.max_parcelas == 18


# --- taxas ------------------------------------------------------------------------------------


async def test_taxas_ida_e_volta_preserva_igual(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_taxas(
        loja,
        [
            EntradaTaxa(chave=12, bandeira="mastercard", taxa_pct=D("10.54")),
            EntradaTaxa(chave=12, bandeira="visa", taxa_pct=None),
            EntradaTaxa(chave="debito", bandeira="elo", taxa_pct=D("1.5")),
        ],
    )
    tabela = await casos.obter_taxas(loja)
    assert tabela.taxas == {
        (12, Bandeira.MASTERCARD): D("10.54"),
        (12, Bandeira.VISA): None,
        ("debito", Bandeira.ELO): D("1.5"),
    }
    assert tabela.taxa(12, Bandeira.VISA) == D("10.54")


async def test_taxas_aceita_bandeira_em_texto_livre_e_chave_textual(
    casos: CasosDeUsoConfig,
) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_taxas(loja, [EntradaTaxa(chave="3", bandeira="Master", taxa_pct=D("4"))])
    assert (3, Bandeira.MASTERCARD) in (await casos.obter_taxas(loja)).taxas


async def test_taxas_invalidas_com_caminho_por_celula(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_taxas(
            loja,
            [
                EntradaTaxa(chave=1, bandeira="visa", taxa_pct=D("2")),
                EntradaTaxa(chave=2, bandeira="visa", taxa_pct=D("-0.5")),
                EntradaTaxa(chave=22, bandeira="visa", taxa_pct=D("2")),
                EntradaTaxa(chave=2, bandeira="bandeiranova", taxa_pct=D("2")),
            ],
        )
    erros = caminhos(exc)
    assert "taxas[1].taxa_pct" in erros
    assert "taxas[2].chave" in erros
    assert "taxas[3].bandeira" in erros


async def test_taxas_duplicadas(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_taxas(
            loja,
            [
                EntradaTaxa(chave=1, bandeira="visa", taxa_pct=D("2")),
                EntradaTaxa(chave=1, bandeira="visa", taxa_pct=D("3")),
            ],
        )
    assert "taxas[1].bandeira" in caminhos(exc)


# --- troca ------------------------------------------------------------------------------------


async def test_troca_ida_e_volta_com_sem(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_troca(
        loja,
        [
            linha_troca(),
            linha_troca(
                modelo="iPhone 15",
                desconto_tela=None,
                desconto_tela_sem=True,
                desconto_bateria=None,
                desconto_bateria_sem=True,
            ),
            linha_troca(marca="Samsung", modelo="Galaxy S23"),
        ],
    )
    tabela = await casos.obter_troca(loja)
    assert len(tabela.linhas_apple) == 2
    assert len(tabela.linhas_outras_marcas) == 1
    iphone16, iphone15 = tabela.linhas_apple
    assert iphone16.modelo.nome == "iPhone 16"
    assert iphone16.desconto_tela == Dinheiro.de("600")
    assert iphone16.desconto_carcaca == Dinheiro.zero()
    assert iphone15.desconto_tela is SEM
    assert iphone15.desconto_bateria is SEM
    assert iphone15.desconto_traseira == Dinheiro.de("300")


async def test_troca_desconto_maior_que_valor_base(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_troca(
            loja,
            [
                linha_troca(),
                linha_troca(modelo="iPhone 15"),
                linha_troca(modelo="iPhone 14"),
                linha_troca(modelo="iPhone 13", desconto_tela=D("3100.01")),
            ],
        )
    erros = caminhos(exc)
    assert list(erros) == ["tabela_troca[3].desconto_tela"]
    assert "maior que o valor base" in erros["tabela_troca[3].desconto_tela"]


async def test_troca_outros_erros_de_campo(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_troca(
            loja,
            [
                linha_troca(modelo="  "),
                linha_troca(capacidade_gb=0),
                linha_troca(valor_sem_detalhes=D("-1")),
                linha_troca(desconto_traseira=D("-5")),
                linha_troca(desconto_carcaca=None),
                linha_troca(desconto_tela=D("10"), desconto_tela_sem=True),
                linha_troca(limite_bateria_pct=101),
            ],
        )
    erros = caminhos(exc)
    assert "tabela_troca[0].modelo" in erros
    assert "tabela_troca[1].capacidade_gb" in erros
    assert "tabela_troca[2].valor_sem_detalhes" in erros
    assert "tabela_troca[3].desconto_traseira" in erros
    assert "tabela_troca[4].desconto_carcaca" in erros
    assert "tabela_troca[5].desconto_tela" in erros
    assert "tabela_troca[6].limite_bateria_pct" in erros


async def test_troca_linha_duplicada(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_troca(loja, [linha_troca(), linha_troca(modelo="IPHONE 16")])
    assert "tabela_troca[1].modelo" in caminhos(exc)


async def test_troca_vazia_limpa_a_tabela(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_troca(loja, [linha_troca()])
    await casos.atualizar_troca(loja, [])
    tabela = await casos.obter_troca(loja)
    assert tabela.linhas_apple == ()
    assert tabela.linhas_outras_marcas == ()


# --- estoque e mapeamento ---------------------------------------------------------------------


async def test_estoque_ida_e_volta(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_estoque(
        loja,
        [linha_estoque(), linha_estoque(sku="IP13-SEMI", condicao="seminovo", bateria_pct=88)],
    )
    linhas = await casos.obter_estoque(loja)
    assert [x.sku for x in linhas] == ["IP16-128-PT", "IP13-SEMI"]
    assert linhas[0].preco_pix == Dinheiro.de("4500")
    assert linhas[0].bateria_pct is None
    assert linhas[1].bateria_pct == 88
    assert linhas[1].condicao == "seminovo"


async def test_estoque_invalido(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_estoque(
            loja,
            [
                linha_estoque(sku=""),
                linha_estoque(sku="A", condicao="usado"),
                linha_estoque(sku="B", quantidade=-1),
                linha_estoque(sku="C", preco_pix=D("-1")),
                linha_estoque(sku="D", bateria_pct=120),
                linha_estoque(sku="D"),
            ],
        )
    erros = caminhos(exc)
    assert {
        "estoque[0].sku",
        "estoque[1].condicao",
        "estoque[2].quantidade",
        "estoque[3].preco_pix",
        "estoque[4].bateria_pct",
        "estoque[5].sku",
    } <= set(erros)


async def test_mapeamento_ida_e_volta_e_erros(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    ok = EntradaLinhaMapeamento(
        sku_externo="ERP-1",
        marca="Apple",
        modelo="iphone 16 pro",
        capacidade_gb=256,
        cor="Titanio",
        condicao="novo",
    )
    await casos.atualizar_mapeamento(loja, [ok])
    (linha,) = await casos.obter_mapeamento(loja)
    assert linha.sku_externo == "ERP-1"
    assert linha.modelo.nome == "iPhone 16 Pro"
    assert linha.capacidade == 256

    ruim = EntradaLinhaMapeamento("", "Apple", "", 0, "x", "usado")
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_mapeamento(loja, [ruim, ok, ok])
    erros = caminhos(exc)
    assert {
        "mapeamento_sku[0].sku_externo",
        "mapeamento_sku[0].modelo",
        "mapeamento_sku[0].capacidade_gb",
        "mapeamento_sku[0].condicao",
        "mapeamento_sku[2].sku_externo",
    } <= set(erros)


# --- checklist --------------------------------------------------------------------------------


def estado(itens: list[ItemChecklist]) -> dict[str, bool]:
    return {i.chave: i.completo for i in itens}


CHAVES = [
    "perfil",
    "vendedores",
    "regras_preco",
    "taxas",
    "tabela_troca",
    "estoque",
    "mapeamento_sku",
]


async def test_checklist_loja_vazia(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    itens = await casos.checklist(loja)
    assert [i.chave for i in itens] == CHAVES
    assert all(i.rotulo_ptbr and i.detalhe for i in itens)
    esperado = {c: False for c in CHAVES}
    esperado["mapeamento_sku"] = True  # sem ERP, nada pendente
    assert estado(itens) == esperado


async def test_checklist_reflete_cada_bloco(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_perfil(loja, perfil_valido())
    assert estado(await casos.checklist(loja))["perfil"] is True

    await casos.atualizar_preco(loja, preco_valido(max_parcelas=3))
    assert estado(await casos.checklist(loja))["regras_preco"] is True

    await casos.atualizar_troca(loja, [linha_troca()])
    assert estado(await casos.checklist(loja))["tabela_troca"] is True

    await casos.atualizar_estoque(loja, [linha_estoque()])
    assert estado(await casos.checklist(loja))["estoque"] is True


async def test_checklist_taxas_exigem_mastercard_ate_max_parcelas(
    casos: CasosDeUsoConfig,
) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_preco(loja, preco_valido(max_parcelas=3))
    await casos.atualizar_taxas(
        loja,
        [EntradaTaxa(chave=n, bandeira="mastercard", taxa_pct=D(n)) for n in (1, 2)],
    )
    item = next(i for i in await casos.checklist(loja) if i.chave == "taxas")
    assert item.completo is False
    assert "3" in item.detalhe

    await casos.atualizar_taxas(
        loja,
        [EntradaTaxa(chave=n, bandeira="mastercard", taxa_pct=D(n)) for n in (1, 2, 3)],
    )
    assert estado(await casos.checklist(loja))["taxas"] is True


async def test_checklist_taxas_mastercard_igual_nao_conta(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_preco(loja, preco_valido(max_parcelas=1))
    await casos.atualizar_taxas(loja, [EntradaTaxa(chave=1, bandeira="mastercard", taxa_pct=None)])
    assert estado(await casos.checklist(loja))["taxas"] is False


async def test_checklist_taxas_sem_regras_de_preco(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    await casos.atualizar_taxas(loja, [EntradaTaxa(chave=1, bandeira="mastercard", taxa_pct=D(2))])
    assert estado(await casos.checklist(loja))["taxas"] is False


async def test_checklist_vendedores_somam_100(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    casos.vendedores.definir(loja, [D("60"), D("30")])  # type: ignore[attr-defined]
    item = next(i for i in await casos.checklist(loja) if i.chave == "vendedores")
    assert item.completo is False
    assert "90" in item.detalhe

    casos.vendedores.definir(loja, [D("60"), D("40")])  # type: ignore[attr-defined]
    assert estado(await casos.checklist(loja))["vendedores"] is True


async def test_checklist_estoque_ou_erp_configurado(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    integracao = casos.integracao
    assert isinstance(integracao, MemoriaIntegracaoEstoque)
    integracao.erp_ativo = True
    assert estado(await casos.checklist(loja))["estoque"] is True


async def test_checklist_mapeamento_avisa_sku_externo_pendente(casos: CasosDeUsoConfig) -> None:
    loja = await nova_loja(casos)
    integracao = casos.integracao
    assert isinstance(integracao, MemoriaIntegracaoEstoque)
    integracao.pendentes = ["ERP-9", "ERP-10"]
    item = next(i for i in await casos.checklist(loja) if i.chave == "mapeamento_sku")
    assert item.completo is False
    assert "2" in item.detalhe
