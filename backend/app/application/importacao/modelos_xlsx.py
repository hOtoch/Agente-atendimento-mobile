"""Geracao dos modelos de planilha (vazios) que a loja baixa, preenche e importa."""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Any, Final

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.domain.aparelho import MODELOS_IPHONE

TIPOS: Final[tuple[str, ...]] = ("troca", "taxas", "estoque")

CABECALHO_TROCA: Final[tuple[str, ...]] = (
    "Modelo",
    "Capacidade (GB)",
    "Valor sem detalhes (R$)",
    "Desconto tela (R$)",
    "Desconto traseira (R$)",
    "Desconto carcaça (R$)",
    "Desconto bateria (R$)",
    "Bateria abaixo de (%)",
)
CABECALHO_ESTOQUE: Final[tuple[str, ...]] = (
    "SKU",
    "Modelo",
    "Capacidade",
    "Cor",
    "Condição (novo/seminovo)",
    "Preço Pix (R$)",
    "Quantidade",
    "Bateria (%)",
)
BANDEIRAS: Final[tuple[str, ...]] = ("Mastercard", "Visa", "Elo", "Hipercard", "Amex")
PERGUNTAS_REGRAS: Final[tuple[str, ...]] = (
    "Máximo de parcelas no cartão",
    "Repassa a taxa da maquininha ao cliente? (sim/não)",
    "Desconto Pix/dinheiro (% ou R$)",
    "Desconto máximo por cliente (R$)",
    "Degrau do desconto (R$)",
    "Oportunidade única ativa? (sim/não)",
    "Oportunidade única: dias mínimos até a compra",
    "Oportunidade única: valor (R$)",
    "Aceita entrada + cartão? (sim/não)",
)

_CAPACIDADES_BASE: Final[tuple[int, ...]] = (64, 128, 256)
_CAPACIDADES_IPHONE: Final[dict[str, tuple[int, ...]]] = {
    "iPhone XS Max": (64, 256, 512),
    "iPhone 11 Pro": (64, 256, 512),
    "iPhone 11 Pro Max": (64, 256, 512),
    "iPhone 12 Pro": (128, 256, 512),
    "iPhone 12 Pro Max": (128, 256, 512),
    "iPhone 13 mini": (128, 256, 512),
    "iPhone 13": (128, 256, 512),
    "iPhone 13 Pro": (128, 256, 512, 1024),
    "iPhone 13 Pro Max": (128, 256, 512, 1024),
    "iPhone 14": (128, 256, 512),
    "iPhone 14 Plus": (128, 256, 512),
    "iPhone 14 Pro": (128, 256, 512, 1024),
    "iPhone 14 Pro Max": (128, 256, 512, 1024),
    "iPhone 15": (128, 256, 512),
    "iPhone 15 Plus": (128, 256, 512),
    "iPhone 15 Pro": (128, 256, 512, 1024),
    "iPhone 15 Pro Max": (256, 512, 1024),
    "iPhone 16e": (128, 256, 512),
    "iPhone 16": (128, 256, 512),
    "iPhone 16 Plus": (128, 256, 512),
    "iPhone 16 Pro": (128, 256, 512, 1024),
    "iPhone 16 Pro Max": (256, 512, 1024),
    "iPhone 17": (256, 512),
    "iPhone Air": (256, 512, 1024),
    "iPhone 17 Pro": (256, 512, 1024),
    "iPhone 17 Pro Max": (256, 512, 1024, 2048),
}

_CABECALHO_ESTILO = Font(bold=True)
_CABECALHO_FUNDO = PatternFill("solid", start_color="E8EEF4")


def _aba_com_cabecalho(
    wb: Workbook, titulo: str, cabecalho: Sequence[str], larguras: Sequence[int]
) -> Worksheet:
    ws = wb.create_sheet(titulo)
    ws.append(list(cabecalho))
    for celula in ws[1]:
        celula.font = _CABECALHO_ESTILO
        celula.fill = _CABECALHO_FUNDO
        celula.alignment = Alignment(wrap_text=True, vertical="center")
    for i, largura in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largura
    ws.freeze_panes = "A2"
    return ws


def _como_preencher(wb: Workbook, linhas: Sequence[str]) -> None:
    ws = wb.create_sheet("Como preencher")
    ws.column_dimensions["A"].width = 110
    for i, linha in enumerate(linhas, start=1):
        celula = ws.cell(row=i, column=1, value=linha)
        celula.alignment = Alignment(wrap_text=True, vertical="top")
        if i == 1:
            celula.font = Font(bold=True, size=13)


def _vazio() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def _modelo_troca() -> Workbook:
    wb = _vazio()
    ws = _aba_com_cabecalho(
        wb, "Tabela de troca", CABECALHO_TROCA, (30, 14, 20, 16, 18, 18, 18, 18)
    )
    for modelo in MODELOS_IPHONE:
        for capacidade in _CAPACIDADES_IPHONE.get(modelo, _CAPACIDADES_BASE):
            ws.append([modelo, capacidade])
    outras = _aba_com_cabecalho(
        wb, "Outras marcas", ("Marca", *CABECALHO_TROCA), (16, 30, 14, 20, 16, 18, 18, 18, 18)
    )
    del outras
    _como_preencher(
        wb,
        (
            "Modelo — Tabela de troca: como preencher",
            "Uma linha por modelo e capacidade. Preencha o valor sem detalhes (aparelho perfeito) "
            "e, ao lado, quanto descontar de cada problema.",
            "Modelo com o valor sem detalhes em branco é ignorado: a loja não pega esse modelo na "
            "troca. Linhas totalmente em branco também são ignoradas.",
            "Descontos: um valor em reais, 0 (o problema não desconta) ou SEM (a loja não avalia "
            "esse problema pelo WhatsApp; o cliente é chamado para avaliação na loja).",
            "Bateria abaixo de (%): o desconto de bateria só vale se a saúde da bateria estiver "
            "abaixo desse percentual. Exemplo: 80.",
            "Capacidade em GB (128) ou com unidade (256GB, 1TB). Valores aceitam vírgula "
            "(2.500,50) e o prefixo R$.",
            "Outras marcas: use a aba 'Outras marcas', informando Marca e Modelo em cada linha.",
            "Camera e outros defeitos não têm coluna: sempre vão para avaliação na loja.",
        ),
    )
    return wb


def _modelo_taxas() -> Workbook:
    wb = _vazio()
    regras = _aba_com_cabecalho(wb, "Regras de preço", ("Pergunta", "Resposta"), (60, 24))
    for pergunta in PERGUNTAS_REGRAS:
        regras.append([pergunta])
    taxas = _aba_com_cabecalho(wb, "Taxas", ("Parcelas", *BANDEIRAS), (14, 14, 14, 14, 14, 14))
    for parcelas in range(1, 22):
        taxas.append([parcelas])
    taxas.append(["Débito"])
    _como_preencher(
        wb,
        (
            "Modelo — Taxas e regras de preço: como preencher",
            "Regras de preço: responda cada pergunta na coluna Resposta. Sim/não aceita sim, não, "
            "s ou n.",
            "Desconto Pix: use 5% (percentual), R$ 100 (valor em reais) ou deixe em branco "
            "quando o preço à vista já é o Pix. Um número sem R$ é tratado como percentual.",
            "Desconto máximo por cliente e degrau: valores em reais (ex.: máximo 100, degrau 50).",
            "Oportunidade única: se ativa, informe os dias mínimos até a compra e o valor.",
            "Taxas: percentual cobrado pela maquininha por número de parcelas (1 a 21) e por "
            "bandeira. Use vírgula decimal (10,54).",
            "Escreva igual numa bandeira para usar a taxa da Mastercard. Deixe em branco o que "
            "não se aplica. Preencha ao menos a Mastercard até o máximo de parcelas.",
        ),
    )
    return wb


def _modelo_estoque() -> Workbook:
    wb = _vazio()
    _aba_com_cabecalho(wb, "Estoque", CABECALHO_ESTOQUE, (18, 28, 12, 20, 22, 16, 12, 12))
    _como_preencher(
        wb,
        (
            "Modelo — Estoque: como preencher",
            "Uma linha por SKU (cada SKU aparece uma vez). Ao importar, o estoque da loja é "
            "substituído pelo conteúdo da planilha.",
            "Condição: novo ou seminovo. Bateria (%) só para seminovo; deixe em branco no novo.",
            "Capacidade em GB (128) ou com unidade (256GB, 1TB). Preço Pix aceita vírgula e R$.",
            "Quantidade 0 mantém o item cadastrado, mas indisponível.",
            "Linhas totalmente em branco são ignoradas.",
        ),
    )
    return wb


_CONSTRUTORES: Final[dict[str, Any]] = {
    "troca": _modelo_troca,
    "taxas": _modelo_taxas,
    "estoque": _modelo_estoque,
}


def gerar_modelo(tipo: str) -> bytes:
    """Bytes do .xlsx modelo vazio. `KeyError` se o tipo nao existir."""
    wb = _CONSTRUTORES[tipo]()
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
