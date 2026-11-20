"""Planilhas fixture geradas em memoria com openpyxl (nada de arquivo real)."""

from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

from openpyxl import Workbook

CAB_TROCA = [
    "Modelo",
    "Capacidade (GB)",
    "Valor sem detalhes (R$)",
    "Desconto tela (R$)",
    "Desconto traseira (R$)",
    "Desconto carcaça (R$)",
    "Desconto bateria (R$)",
    "Bateria abaixo de (%)",
]
CAB_OUTRAS = ["Marca", *CAB_TROCA]
CAB_ESTOQUE = [
    "SKU",
    "Modelo",
    "Capacidade",
    "Cor",
    "Condição (novo/seminovo)",
    "Preço Pix (R$)",
    "Quantidade",
    "Bateria (%)",
]
CAB_TAXAS = ["Parcelas", "Mastercard", "Visa", "Elo", "Hipercard", "Amex"]
CAB_REGRAS = ["Pergunta", "Resposta"]

REGRAS_OK: list[list[Any]] = [
    ["Máximo de parcelas no cartão", 18],
    ["Repassa a taxa da maquininha ao cliente? (sim/não)", "sim"],
    ["Desconto Pix/dinheiro (% ou R$)", "5%"],
    ["Desconto máximo por cliente (R$)", 100],
    ["Degrau do desconto (R$)", 50],
    ["Oportunidade única ativa? (sim/não)", "s"],
    ["Oportunidade única: dias mínimos até a compra", 14],
    ["Oportunidade única: valor (R$)", "R$ 100"],
    ["Aceita entrada + cartão? (sim/não)", "não"],
]


def xlsx(abas: Mapping[str, Sequence[Sequence[Any]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for linha in linhas:
            ws.append(list(linha))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def troca_xlsx(linhas: Sequence[Sequence[Any]], outras: Sequence[Sequence[Any]] = ()) -> bytes:
    abas: dict[str, Sequence[Sequence[Any]]] = {"Tabela de troca": [CAB_TROCA, *linhas]}
    if outras:
        abas["Outras marcas"] = [CAB_OUTRAS, *outras]
    return xlsx(abas)


def estoque_xlsx(linhas: Sequence[Sequence[Any]]) -> bytes:
    return xlsx({"Estoque": [CAB_ESTOQUE, *linhas]})


def taxas_xlsx(
    taxas: Sequence[Sequence[Any]], regras: Sequence[Sequence[Any]] | None = None
) -> bytes:
    regras = REGRAS_OK if regras is None else regras
    return xlsx({"Regras de preço": [CAB_REGRAS, *regras], "Taxas": [CAB_TAXAS, *taxas]})


def regras_com(**respostas: Any) -> list[list[Any]]:
    """REGRAS_OK trocando a resposta das perguntas que comecam com o texto dado (`_` = espaco)."""
    trocas = {k.replace("_", " "): v for k, v in respostas.items()}
    return [[p, next((v for k, v in trocas.items() if p.startswith(k)), r)] for p, r in REGRAS_OK]
