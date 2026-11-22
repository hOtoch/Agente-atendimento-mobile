"""Mapeamento puro do item cru de `list_inventory` (Mercado Phone) para o estoque local.

Todos os dados sao sinteticos.
"""

from decimal import Decimal
from typing import Any

import pytest

from app.adapters.outbound.mercadophone.mapear import (
    Descarte,
    ForaDaLoja,
    LinhaErp,
    mapa_de_marcas,
    mapear_inventario,
    mapear_item,
)
from app.domain.estoque import Condicao
from app.domain.oferta import MotivoDescarte
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

MARCAS = {501: "Apple", 502: "Samsung"}


def bruto(**mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 9001,
        "sku": "TESTE-0001",
        "aparelhoDescricao": "IPHONE 15 PRO",
        "descricao": "9001 - IPHONE 15 PRO - PRETO - 256gb -  Estado: SEMINOVO -  SKU: TESTE-0001",
        "quantidade": 1.0,
        "disponibilidade": "Disponível para venda",
        "produtoDisponibilidadeId": 1,
        "marcaId": 501,
        "tipoProdutoId": "77",
        "tipoProdutoDescricao": "Celular",
        "gbId": 90,
        "gbDescricao": "256gb",
        "corId": 134,
        "corDescricao": "PRETO",
        "estadoProdutoId": 24037,
        "estadoProdutoDescricao": "SEMINOVO",
        "saudeBateria": None,
        "valorCusto": 3000,
        "valorVenda": 4200,
        "valorVenda2": 0,
        "valorVenda3": 0,
        "obs": "Loja A",
        "snAcessorio": 0,
        "snPeca": 0,
        "snServico": 0,
        "dataEntrada": "2026-10-01",
        "imei": None,
    }
    return base | mudancas


def linha(**mudancas: Any) -> Any:
    resultado = mapear_item(bruto(**mudancas), MARCAS)
    assert isinstance(resultado, LinhaErp), resultado
    return resultado


def descarte(**mudancas: Any) -> Descarte:
    resultado = mapear_item(bruto(**mudancas), MARCAS)
    assert isinstance(resultado, Descarte), resultado
    return resultado


def test_item_completo_vira_linha_de_estoque_local() -> None:
    r = linha()
    assert r.erp_produto_id == 9001
    assert r.linha.sku == "TESTE-0001"
    assert r.linha.modelo == ModeloAparelho.de("iPhone 15 Pro")
    assert r.linha.capacidade == Capacidade(256)
    assert r.linha.cor == "Preto"
    assert r.linha.condicao is Condicao.SEMINOVO
    assert r.linha.preco_pix == Dinheiro.de(Decimal("4200"))
    assert r.linha.quantidade == 1
    assert r.linha.bateria_pct is None


@pytest.mark.parametrize(
    ("estado", "esperado"),
    [
        ("LACRADO", Condicao.NOVO),
        ("NOVO", Condicao.NOVO),
        ("novo", Condicao.NOVO),
        ("SEMINOVO", Condicao.SEMINOVO),
        ("SEMI NOVO", Condicao.SEMINOVO),
        ("Semi-Novo", Condicao.SEMINOVO),
        ("  SEMINOVO ", Condicao.SEMINOVO),
    ],
)
def test_estado_do_erp_vira_condicao(estado: str, esperado: Condicao) -> None:
    assert linha(estadoProdutoDescricao=estado).linha.condicao is esperado


@pytest.mark.parametrize("estado", [None, "", "  ", "NÃO INFORMADO", "DEFEITO"])
def test_estado_ausente_ou_desconhecido_e_descartado(estado: str | None) -> None:
    assert descarte(estadoProdutoDescricao=estado).motivo is MotivoDescarte.ESTADO_NAO_INFORMADO


def test_estado_ausente_da_chave_e_descartado() -> None:
    item = bruto()
    del item["estadoProdutoDescricao"]
    r = mapear_item(item, MARCAS)
    assert isinstance(r, Descarte)
    assert r.motivo is MotivoDescarte.ESTADO_NAO_INFORMADO


@pytest.mark.parametrize(
    ("saude", "esperado"),
    [(0.86, 86), (0.855, 86), (1.0, 100), (86, 86), (86.4, 86), (Decimal("0.9"), 90)],
)
def test_bateria_do_seminovo_vira_percentual_inteiro(saude: Any, esperado: int) -> None:
    r = linha(estadoProdutoDescricao="SEMINOVO", saudeBateria=saude)
    assert r.linha.bateria_pct == esperado


@pytest.mark.parametrize("saude", [None, 0, 0.0, -1, 250, "abc", True])
def test_bateria_vazia_ou_invalida_vira_none(saude: Any) -> None:
    assert linha(saudeBateria=saude).linha.bateria_pct is None


@pytest.mark.parametrize("estado", ["NOVO", "LACRADO"])
def test_novo_nunca_leva_bateria(estado: str) -> None:
    r = linha(estadoProdutoDescricao=estado, saudeBateria=0.86)
    assert r.linha.condicao is Condicao.NOVO
    assert r.linha.bateria_pct is None


@pytest.mark.parametrize(
    ("gb", "esperado"),
    [("128gb", 128), ("64gb", 64), ("1TB", 1024), ("8GB", 8), (" 256GB ", 256)],
)
def test_capacidade_do_erp(gb: str, esperado: int) -> None:
    assert linha(gbDescricao=gb).linha.capacidade == Capacidade(esperado)


@pytest.mark.parametrize("gb", [None, "", "  ", "grande", "0gb"])
def test_capacidade_ausente_ou_invalida_e_descartada(gb: str | None) -> None:
    assert descarte(gbDescricao=gb).motivo is MotivoDescarte.SEM_CAPACIDADE


@pytest.mark.parametrize("cor", [None, "", "   "])
def test_cor_vazia_vira_nao_informada(cor: str | None) -> None:
    assert linha(corDescricao=cor).linha.cor == "não informada"


def test_cor_e_normalizada_em_title_case() -> None:
    assert linha(corDescricao="TITÂNIO  NATURAL").linha.cor == "Titânio Natural"


@pytest.mark.parametrize("valor", [None, 0, 0.0, 0.01, "0.01", -3])
def test_sem_preco(valor: Any) -> None:
    assert descarte(valorVenda=valor).motivo is MotivoDescarte.SEM_PRECO


def test_preco_vem_de_valor_venda_e_ignora_as_outras_tabelas_e_o_custo() -> None:
    r = linha(valorVenda=4199.9, valorVenda2=3900, valorVenda3=3800, valorCusto=100)
    assert r.linha.preco_pix == Dinheiro.de(Decimal("4199.90"))


def test_preco_nunca_usa_float_binario() -> None:
    assert linha(valorVenda=0.1 + 0.2 + 1000).linha.preco_pix.valor == Decimal("1000.30")


@pytest.mark.parametrize("quantidade", [0, 0.0, -1.0, None, 0.4])
def test_sem_quantidade(quantidade: Any) -> None:
    assert descarte(quantidade=quantidade).motivo is MotivoDescarte.SEM_QUANTIDADE


def test_quantidade_float_vira_inteiro() -> None:
    assert linha(quantidade=3.0).linha.quantidade == 3


@pytest.mark.parametrize("disponibilidade", ["Laboratório", "Reservado", None, ""])
def test_indisponivel(disponibilidade: str | None) -> None:
    assert descarte(disponibilidade=disponibilidade).motivo is MotivoDescarte.INDISPONIVEL


def test_disponivel_para_venda_tolera_caixa_e_acento() -> None:
    assert isinstance(mapear_item(bruto(disponibilidade="DISPONIVEL PARA VENDA"), MARCAS), LinhaErp)


@pytest.mark.parametrize(
    "tipo",
    ["Tablet", "Áudio", "TV e vídeo", "Games", "Relógio", "Informática e internet", "Acessorios"],
)
def test_categoria_que_nao_e_celular(tipo: str) -> None:
    assert descarte(tipoProdutoDescricao=tipo).motivo is MotivoDescarte.NAO_E_CELULAR


def test_flags_de_acessorio_peca_e_servico_nao_sao_celular() -> None:
    assert descarte(snAcessorio=1).motivo is MotivoDescarte.NAO_E_CELULAR
    assert descarte(snPeca=1).motivo is MotivoDescarte.NAO_E_CELULAR
    assert descarte(snServico=1).motivo is MotivoDescarte.NAO_E_CELULAR


def test_tipo_celular_tolera_caixa() -> None:
    assert isinstance(mapear_item(bruto(tipoProdutoDescricao="CELULAR"), MARCAS), LinhaErp)


@pytest.mark.parametrize("modelo", [None, "", "   "])
def test_modelo_vazio(modelo: str | None) -> None:
    assert descarte(aparelhoDescricao=modelo, marcaId=None).motivo is MotivoDescarte.SEM_MODELO


def test_modelo_com_erro_de_digitacao_passa_normalizado_sem_virar_canonico() -> None:
    r = linha(aparelhoDescricao="IPHONE 15 PRO MAXX")
    assert r.linha.modelo.conhecido is False
    assert r.linha.modelo.nome == "Iphone 15 Pro Maxx"


def test_marca_resolvida_pelo_mapa_do_erp() -> None:
    r = linha(aparelhoDescricao="GALAXY S24", marcaId=502)
    assert r.linha.modelo.marca == "Samsung"
    assert r.linha.modelo.nome == "Galaxy S24"


def test_sem_marca_e_nome_de_iphone_infere_apple() -> None:
    r = linha(marcaId=999)
    assert r.linha.modelo == ModeloAparelho.de("iPhone 15 Pro", "Apple")
    assert linha(marcaId=None).linha.modelo.marca == "Apple"


def test_sem_marca_e_nome_que_nao_e_iphone_e_descartado() -> None:
    d = descarte(aparelhoDescricao="GALAXY S24", marcaId=999)
    assert d.motivo is MotivoDescarte.MARCA_NAO_IDENTIFICADA


def test_sku_do_erp_e_preservado_e_sem_sku_usa_mp_id() -> None:
    assert linha(sku="  ABC-1 ").linha.sku == "ABC-1"
    assert linha(sku=None, id=77).linha.sku == "MP-77"
    assert linha(sku="  ", id=78).linha.sku == "MP-78"


def test_descarte_carrega_sku_e_id_do_erp() -> None:
    d = descarte(valorVenda=0.01)
    assert (d.sku, d.erp_produto_id) == ("TESTE-0001", 9001)
    assert descarte(sku=None, id=55, valorVenda=0).sku == "MP-55"


@pytest.mark.parametrize("id_", [None, "abc", True])
def test_item_sem_id_valido_e_descartado_como_malformado(id_: Any) -> None:
    d = descarte(id=id_)
    assert d.motivo is MotivoDescarte.ITEM_MALFORMADO
    assert d.erp_produto_id is None


def test_item_que_nao_e_objeto_e_malformado() -> None:
    r = mapear_item("lixo", MARCAS)  # type: ignore[arg-type]
    assert isinstance(r, Descarte)
    assert r.motivo is MotivoDescarte.ITEM_MALFORMADO


# --- filtro da loja ---


@pytest.mark.parametrize(
    ("obs", "filtro", "casa"),
    [
        ("Loja A", "Loja A", True),
        ("loja a", "Loja A", True),
        ("Loja A | Outra anotação", "Loja A", True),
        ("Loja A - vitrine", "Loja A", True),
        ("Loja B", "Loja A", False),
        ("Loja B | Loja A", "Loja A", False),
        ("Loja AB", "Loja A", False),
        (None, "Loja A", False),
        ("", "Loja A", False),
    ],
)
def test_filtro_loja_casa_com_o_comeco_do_obs_antes_do_separador(
    obs: str | None, filtro: str, casa: bool
) -> None:
    r = mapear_item(bruto(obs=obs), MARCAS, filtro_loja=filtro)
    assert isinstance(r, LinhaErp) is casa
    if not casa:
        assert isinstance(r, ForaDaLoja)


def test_sem_filtro_todas_as_lojas_entram() -> None:
    assert isinstance(mapear_item(bruto(obs="Loja B"), MARCAS), LinhaErp)
    assert isinstance(mapear_item(bruto(obs="Loja B"), MARCAS, filtro_loja="  "), LinhaErp)


def test_item_de_outra_loja_e_ignorado_antes_das_regras_de_qualidade() -> None:
    r = mapear_item(bruto(obs="Loja B", valorVenda=0), MARCAS, filtro_loja="Loja A")
    assert isinstance(r, ForaDaLoja)
    assert r.sku == "TESTE-0001"


# --- inventario e relatorio ---


def test_relatorio_conta_lidos_importados_descartes_e_outra_loja() -> None:
    itens = [
        bruto(id=1, sku="A"),
        bruto(id=2, sku="B", quantidade=5.0),
        bruto(id=3, sku="C", valorVenda=0.01),
        bruto(id=4, sku="D", valorVenda=None),
        bruto(id=5, sku="E", disponibilidade="Laboratório"),
        bruto(id=6, sku="F", tipoProdutoDescricao="Áudio"),
        bruto(id=7, sku="G", obs="Loja B"),
        bruto(id=8, sku="H", obs="Loja B | x", valorVenda=0),
    ]
    res = mapear_inventario(itens, MARCAS, filtro_loja="Loja A")
    assert [x.linha.sku for x in res.linhas] == ["A", "B"]
    assert [d.sku for d in res.descartes] == ["C", "D", "E", "F"]
    rel = res.relatorio
    assert rel.lidos == 8
    assert rel.importados == 2
    assert rel.outra_loja == 2
    assert rel.descartados == 4
    assert rel.por_motivo == {
        MotivoDescarte.SEM_PRECO: 2,
        MotivoDescarte.INDISPONIVEL: 1,
        MotivoDescarte.NAO_E_CELULAR: 1,
    }
    assert rel.lidos == rel.importados + rel.descartados + rel.outra_loja


def test_inventario_vazio() -> None:
    res = mapear_inventario([], MARCAS)
    assert res.linhas == ()
    assert res.relatorio.lidos == 0
    assert res.relatorio.por_motivo == {}


def test_mapa_de_marcas_a_partir_do_list_brands() -> None:
    brands = [{"id": 501, "name": "Apple"}, {"id": 502, "name": " Samsung "}, {"id": 1}, "x"]
    assert mapa_de_marcas(brands) == {501: "Apple", 502: "Samsung"}  # type: ignore[arg-type]
