"""Modelos de planilha gerados: estrutura e leitura de volta pelo proprio parser."""

from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.application.importacao.leitor import ler_estoque, ler_taxas, ler_troca
from app.application.importacao.modelos_xlsx import TIPOS, gerar_modelo
from app.domain.aparelho import MODELOS_IPHONE


def _abas(tipo: str) -> dict[str, list[list[object]]]:
    wb = load_workbook(BytesIO(gerar_modelo(tipo)))  # type: ignore[arg-type]
    return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}


def test_tipos() -> None:
    assert set(TIPOS) == {"troca", "taxas", "estoque"}
    with pytest.raises(KeyError):
        gerar_modelo("outro")


def test_modelo_troca() -> None:
    abas = _abas("troca")
    assert {"Tabela de troca", "Outras marcas", "Como preencher"} <= set(abas)
    linhas = abas["Tabela de troca"]
    assert linhas[0][:3] == ["Modelo", "Capacidade (GB)", "Valor sem detalhes (R$)"]
    modelos = {r[0] for r in linhas[1:]}
    assert modelos == set(MODELOS_IPHONE)
    assert all(r[2] is None for r in linhas[1:])  # valores vazios
    assert abas["Outras marcas"][0][0] == "Marca"
    leitura = ler_troca(gerar_modelo("troca"))
    assert leitura.entradas == [] and leitura.erros == []


def test_modelo_taxas() -> None:
    abas = _abas("taxas")
    assert abas["Taxas"][0] == ["Parcelas", "Mastercard", "Visa", "Elo", "Hipercard", "Amex"]
    assert [r[0] for r in abas["Taxas"][1:]] == [*range(1, 22), "Débito"]
    assert abas["Regras de preço"][0] == ["Pergunta", "Resposta"]
    taxas, regras = ler_taxas(gerar_modelo("taxas"))
    assert taxas.entradas == []
    # respostas vazias: o modelo vazio acusa as perguntas obrigatorias nas celulas certas
    assert regras.entrada is None and regras.erros


def test_modelo_estoque() -> None:
    abas = _abas("estoque")
    assert abas["Estoque"][0] == [
        "SKU",
        "Modelo",
        "Capacidade",
        "Cor",
        "Condição (novo/seminovo)",
        "Preço Pix (R$)",
        "Quantidade",
        "Bateria (%)",
    ]
    assert ler_estoque(gerar_modelo("estoque")).entradas == []
