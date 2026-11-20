"""Leitura de planilhas xlsx da loja e producao dos comandos de `application.config.entradas`.

Cada leitura devolve as entradas, a celula de origem de cada campo (para mapear erros de
negocio de volta a planilha) e os erros de leitura, com referencia de celula (`troca!D7`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell import Cell
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.application.config.entradas import (
    EntradaLinhaEstoque,
    EntradaLinhaTroca,
    EntradaPreco,
    EntradaTaxa,
)
from app.application.config.modelos import ErroCampo
from app.application.importacao.celulas import (
    CelulaInvalida,
    eh_igual,
    eh_sem,
    normalizar,
    para_bool,
    para_capacidade,
    para_decimal,
    para_int,
    texto,
    vazio,
)
from app.domain.bandeira import Bandeira
from app.domain.pagamento import DEBITO

LINHA = "_linha"
"""Chave de `origens` com a celula inicial da linha (usada quando o campo nao tem celula)."""

_FALHA: Any = object()
_MARCA_APPLE = "Apple"


@dataclass(frozen=True, slots=True)
class Leitura[T]:
    entradas: list[T]
    origens: list[dict[str, str]]
    erros: list[ErroCampo]


@dataclass(frozen=True, slots=True)
class LeituraPreco:
    entrada: EntradaPreco | None
    origens: dict[str, str]
    erros: list[ErroCampo] = field(default_factory=list)


# --- infraestrutura ---------------------------------------------------------------------------


def _abrir(conteudo: bytes) -> Workbook | None:
    try:
        return load_workbook(BytesIO(conteudo), data_only=True)
    except Exception:  # openpyxl levanta tipos variados para arquivo corrompido ou nao-xlsx
        return None


_ERRO_ARQUIVO = ErroCampo("arquivo", "O arquivo não é uma planilha .xlsx válida.")


def _aba(wb: Workbook, *trechos: str) -> Worksheet | None:
    for ws in wb.worksheets:
        titulo = normalizar(ws.title)
        if any(t in titulo for t in trechos):
            return ws
    return None


def _ref(chave: str, celula: Cell) -> str:
    return f"{chave}!{celula.coordinate}"


def _linha_vazia(ws: Worksheet, linha: int) -> bool:
    return all(vazio(c.value) for c in ws[linha])


def _colunas(
    ws: Worksheet,
    chave: str,
    classificar: Callable[[str], str | None],
    obrigatorias: tuple[str, ...],
    erros: list[ErroCampo],
) -> dict[str, int]:
    achadas: dict[str, int] = {}
    for celula in ws[1]:
        if vazio(celula.value):
            continue
        campo = classificar(normalizar(celula.value))
        if campo is not None and campo not in achadas:
            achadas[campo] = celula.column
    faltam = [c for c in obrigatorias if c not in achadas]
    if faltam:
        erros.append(
            ErroCampo(chave, "Colunas ausentes no cabeçalho: " + ", ".join(sorted(faltam)) + ".")
        )
    return achadas


def _ler[R](
    celula: Cell,
    chave: str,
    erros: list[ErroCampo],
    converter: Callable[[Any], R],
    *,
    obrigatorio: str | None = None,
) -> R | None:
    """Converte a celula. Vazio vira None (ou erro, se `obrigatorio`); invalido vira erro."""
    if vazio(celula.value):
        if obrigatorio is not None:
            erros.append(ErroCampo(_ref(chave, celula), obrigatorio))
            return _FALHA  # type: ignore[no-any-return]
        return None
    try:
        return converter(celula.value)
    except CelulaInvalida as exc:
        erros.append(ErroCampo(_ref(chave, celula), str(exc)))
        return _FALHA  # type: ignore[no-any-return]


# --- troca ------------------------------------------------------------------------------------


def _classificar_troca(h: str) -> str | None:
    if "marca" in h:
        return "marca"
    if "modelo" in h:
        return "modelo"
    if "capacidade" in h:
        return "capacidade_gb"
    if "valor" in h:
        return "valor_sem_detalhes"
    if "abaixo" in h or "limite" in h:
        return "limite_bateria_pct"
    if "tela" in h or "frontal" in h:
        return "desconto_tela"
    if "traseira" in h:
        return "desconto_traseira"
    if "carcaca" in h:
        return "desconto_carcaca"
    if "bateria" in h:
        return "desconto_bateria"
    return None


_OBRIGATORIAS_TROCA = (
    "modelo",
    "capacidade_gb",
    "valor_sem_detalhes",
    "desconto_tela",
    "desconto_traseira",
    "desconto_carcaca",
    "desconto_bateria",
    "limite_bateria_pct",
)


def _desconto(valor: Any) -> tuple[Decimal | None, bool]:
    if eh_sem(valor):
        return None, True
    return para_decimal(valor), False


def _ler_aba_troca(ws: Worksheet, chave: str, com_marca: bool) -> Leitura[EntradaLinhaTroca]:
    erros: list[ErroCampo] = []
    cols = _colunas(
        ws,
        chave,
        _classificar_troca,
        (*_OBRIGATORIAS_TROCA, *(("marca",) if com_marca else ())),
        erros,
    )
    entradas: list[EntradaLinhaTroca] = []
    origens: list[dict[str, str]] = []
    if erros:
        return Leitura(entradas, origens, erros)
    for linha in range(2, ws.max_row + 1):
        if _linha_vazia(ws, linha):
            continue
        cel = {campo: ws.cell(row=linha, column=col) for campo, col in cols.items()}
        if vazio(cel["valor_sem_detalhes"].value):
            continue  # a loja nao pega esse modelo na troca
        antes = len(erros)
        marca = (
            _ler(cel["marca"], chave, erros, texto, obrigatorio="Informe a marca.")
            if com_marca
            else _MARCA_APPLE
        )
        modelo = texto(cel["modelo"].value)
        capacidade = _ler(
            cel["capacidade_gb"], chave, erros, para_capacidade, obrigatorio="Informe a capacidade."
        )
        valor = _ler(cel["valor_sem_detalhes"], chave, erros, para_decimal)
        descontos = {
            campo: _ler(cel[campo], chave, erros, _desconto)
            for campo in (
                "desconto_tela",
                "desconto_traseira",
                "desconto_carcaca",
                "desconto_bateria",
            )
        }
        limite = _ler(
            cel["limite_bateria_pct"],
            chave,
            erros,
            lambda v: para_int(v, "percentual inteiro, como 80"),
            obrigatorio="Informe o limite de bateria (%).",
        )
        if len(erros) > antes:
            continue
        pares = {c: (d if d is not None else (None, False)) for c, d in descontos.items()}
        entradas.append(
            EntradaLinhaTroca(
                marca=marca,  # type: ignore[arg-type]
                modelo=modelo,
                capacidade_gb=capacidade,  # type: ignore[arg-type]
                valor_sem_detalhes=valor,  # type: ignore[arg-type]
                desconto_tela=pares["desconto_tela"][0],
                desconto_tela_sem=pares["desconto_tela"][1],
                desconto_traseira=pares["desconto_traseira"][0],
                desconto_traseira_sem=pares["desconto_traseira"][1],
                desconto_carcaca=pares["desconto_carcaca"][0],
                desconto_carcaca_sem=pares["desconto_carcaca"][1],
                desconto_bateria=pares["desconto_bateria"][0],
                desconto_bateria_sem=pares["desconto_bateria"][1],
                limite_bateria_pct=limite,  # type: ignore[arg-type]
            )
        )
        origem = {campo: _ref(chave, c) for campo, c in cel.items()}
        origem[LINHA] = f"{chave}!A{linha}"
        origens.append(origem)
    return Leitura(entradas, origens, erros)


def ler_troca(conteudo: bytes) -> Leitura[EntradaLinhaTroca]:
    wb = _abrir(conteudo)
    if wb is None:
        return Leitura([], [], [_ERRO_ARQUIVO])
    principal = _aba(wb, "troca")
    if principal is None:
        return Leitura([], [], [ErroCampo("arquivo", "Aba 'Tabela de troca' não encontrada.")])
    leitura = _ler_aba_troca(principal, "troca", com_marca=False)
    outras_ws = _aba(wb, "outras")
    if outras_ws is None:
        return leitura
    outras = _ler_aba_troca(outras_ws, "outras_marcas", com_marca=True)
    return Leitura(
        [*leitura.entradas, *outras.entradas],
        [*leitura.origens, *outras.origens],
        [*leitura.erros, *outras.erros],
    )


# --- taxas e regras de preco ------------------------------------------------------------------


def _chave_taxa(valor: Any) -> int | str:
    if isinstance(valor, bool):
        raise CelulaInvalida("Parcelas inválidas.")
    if isinstance(valor, (int, float)) and valor == int(valor):
        return int(valor)
    chave = normalizar(valor)
    if chave == DEBITO:
        return DEBITO
    m = re.fullmatch(r"(\d+) ?x?", chave)
    if m is None:
        raise CelulaInvalida(f"Parcelas inválidas: {texto(valor)!r}. Use 1 a 21 ou Débito.")
    return int(m.group(1))


def _taxa(valor: Any) -> Decimal | None:
    return None if eh_igual(valor) else para_decimal(valor)


def _ler_aba_taxas(ws: Worksheet, chave: str) -> Leitura[EntradaTaxa]:
    erros: list[ErroCampo] = []
    bandeiras: dict[int, Bandeira] = {}
    for celula in list(ws[1])[1:]:
        if vazio(celula.value):
            continue
        try:
            bandeiras[celula.column] = Bandeira.parse(texto(celula.value))
        except ValueError:
            erros.append(
                ErroCampo(_ref(chave, celula), f"Bandeira desconhecida: {texto(celula.value)!r}.")
            )
    entradas: list[EntradaTaxa] = []
    origens: list[dict[str, str]] = []
    for linha in range(2, ws.max_row + 1):
        if _linha_vazia(ws, linha):
            continue
        cel_chave = ws.cell(row=linha, column=1)
        antes = len(erros)
        parcelas = _ler(cel_chave, chave, erros, _chave_taxa, obrigatorio="Informe as parcelas.")
        for coluna, bandeira in bandeiras.items():
            cel = ws.cell(row=linha, column=coluna)
            if vazio(cel.value):
                continue
            taxa = _ler(cel, chave, erros, _taxa)
            if len(erros) > antes:
                continue
            entradas.append(EntradaTaxa(parcelas, bandeira.value, taxa))  # type: ignore[arg-type]
            origens.append(
                {
                    "chave": _ref(chave, cel_chave),
                    "bandeira": _ref(chave, ws.cell(row=1, column=coluna)),
                    "taxa_pct": _ref(chave, cel),
                    LINHA: _ref(chave, cel_chave),
                }
            )
    return Leitura(entradas, origens, erros)


def _classificar_regra(p: str) -> str | None:
    if "oportunidade" in p:
        if "dias" in p:
            return "oportunidade_dias_minimos"
        if "valor" in p:
            return "oportunidade_valor"
        return "oportunidade_ativa"
    if "parcelas" in p:
        return "max_parcelas"
    if "repassa" in p or "repasse" in p:
        return "repassa_taxa"
    if "pix" in p:
        return "desconto_pix"
    if "degrau" in p:
        return "desconto_degrau"
    if "maximo" in p or "teto" in p:
        return "desconto_teto"
    if "entrada" in p:
        return "aceita_entrada_mais_cartao"
    return None


_NENHUM_PIX = {"nenhum", "nao", "sem", "nada", "0", "a vista", "preco a vista ja e o pix"}


def _pix(valor: Any) -> tuple[str, Decimal | None]:
    """5% e 5 = percentual; 'R$ 100' = valor em reais; vazio/nenhum/'já é o Pix' = nenhum."""
    chave = normalizar(valor)
    if chave in _NENHUM_PIX or "ja e" in chave:
        return "nenhum", None
    numero = para_decimal(valor)
    if numero == 0:
        return "nenhum", None
    if isinstance(valor, str) and "r$" in valor.lower():
        return "valor", numero
    return "percentual", numero


_OBRIGATORIAS_REGRAS = {
    "max_parcelas": "Máximo de parcelas",
    "repassa_taxa": "Repassa taxa",
    "desconto_teto": "Desconto máximo",
    "desconto_degrau": "Degrau do desconto",
    "aceita_entrada_mais_cartao": "Aceita entrada + cartão",
}


def _ler_regras(ws: Worksheet, chave: str) -> LeituraPreco:
    erros: list[ErroCampo] = []
    respostas: dict[str, Cell] = {}
    for linha in range(2, ws.max_row + 1):
        campo = _classificar_regra(normalizar(ws.cell(row=linha, column=1).value or ""))
        if campo is not None and campo not in respostas:
            respostas[campo] = ws.cell(row=linha, column=2)
    for campo, rotulo in _OBRIGATORIAS_REGRAS.items():
        if campo not in respostas:
            erros.append(ErroCampo(chave, f"Pergunta não encontrada: {rotulo}."))
    if erros:
        return LeituraPreco(None, {}, erros)

    def obter(
        campo: str, conv: Callable[[Any], Any], obrigatorio: str | None, padrao: Any = None
    ) -> Any:
        cel = respostas.get(campo)
        if cel is None:
            return padrao
        valor = _ler(cel, chave, erros, conv, obrigatorio=obrigatorio)
        return padrao if valor is None else valor

    inteiro = lambda v: para_int(v, "número inteiro")  # noqa: E731
    pix = obter("desconto_pix", _pix, None, ("nenhum", None))
    ativa = obter("oportunidade_ativa", para_bool, None, False)
    exigir = "Informe a resposta." if ativa is True else None
    valores = {
        "max_parcelas": obter("max_parcelas", inteiro, "Informe a resposta."),
        "repassa_taxa": obter("repassa_taxa", para_bool, "Responda sim ou não."),
        "desconto_teto": obter("desconto_teto", para_decimal, "Informe o valor."),
        "desconto_degrau": obter("desconto_degrau", para_decimal, "Informe o valor."),
        "aceita": obter("aceita_entrada_mais_cartao", para_bool, "Responda sim ou não."),
        "dias": obter("oportunidade_dias_minimos", inteiro, exigir, 0),
        "valor": obter("oportunidade_valor", para_decimal, exigir, Decimal(0)),
    }
    origens = {campo: _ref(chave, cel) for campo, cel in respostas.items()}
    origens["desconto_pix_tipo"] = origens["desconto_pix_valor"] = origens.get("desconto_pix", "")
    if erros:
        return LeituraPreco(None, origens, erros)
    entrada = EntradaPreco(
        max_parcelas=valores["max_parcelas"],
        repassa_taxa=valores["repassa_taxa"],
        desconto_pix_tipo=pix[0],
        desconto_pix_valor=pix[1],
        aceita_entrada_mais_cartao=valores["aceita"],
        desconto_teto=valores["desconto_teto"],
        desconto_degrau=valores["desconto_degrau"],
        oportunidade_ativa=ativa,
        oportunidade_dias_minimos=valores["dias"],
        oportunidade_valor=valores["valor"],
        oportunidade_conta_no_teto=False,
    )
    return LeituraPreco(entrada, origens, erros)


def ler_taxas(conteudo: bytes) -> tuple[Leitura[EntradaTaxa], LeituraPreco]:
    wb = _abrir(conteudo)
    if wb is None:
        return Leitura([], [], [_ERRO_ARQUIVO]), LeituraPreco(None, {})
    ws_taxas = _aba(wb, "taxas")
    ws_regras = _aba(wb, "regras", "preco")
    taxas = (
        _ler_aba_taxas(ws_taxas, "taxas")
        if ws_taxas is not None
        else Leitura([], [], [ErroCampo("arquivo", "Aba 'Taxas' não encontrada.")])
    )
    regras = (
        _ler_regras(ws_regras, "regras")
        if ws_regras is not None
        else LeituraPreco(None, {}, [ErroCampo("arquivo", "Aba 'Regras de preço' não encontrada.")])
    )
    return taxas, regras


# --- estoque ----------------------------------------------------------------------------------


def _classificar_estoque(h: str) -> str | None:
    if "sku" in h:
        return "sku"
    if "marca" in h:
        return "marca"
    if "modelo" in h:
        return "modelo"
    if "capacidade" in h:
        return "capacidade_gb"
    if h == "cor" or h.startswith("cor "):
        return "cor"
    if "condicao" in h:
        return "condicao"
    if "preco" in h or "pix" in h:
        return "preco_pix"
    if "quantidade" in h or "qtd" in h:
        return "quantidade"
    if "bateria" in h:
        return "bateria_pct"
    return None


def _condicao(valor: Any) -> str:
    return normalizar(valor).replace(" ", "")


def ler_estoque(conteudo: bytes) -> Leitura[EntradaLinhaEstoque]:
    wb = _abrir(conteudo)
    if wb is None:
        return Leitura([], [], [_ERRO_ARQUIVO])
    ws = _aba(wb, "estoque")
    if ws is None:
        return Leitura([], [], [ErroCampo("arquivo", "Aba 'Estoque' não encontrada.")])
    chave = "estoque"
    erros: list[ErroCampo] = []
    obrigatorias = ("sku", "modelo", "capacidade_gb", "cor", "condicao", "preco_pix", "quantidade")
    cols = _colunas(ws, chave, _classificar_estoque, obrigatorias, erros)
    entradas: list[EntradaLinhaEstoque] = []
    origens: list[dict[str, str]] = []
    if erros:
        return Leitura(entradas, origens, erros)
    for linha in range(2, ws.max_row + 1):
        if _linha_vazia(ws, linha):
            continue
        cel = {campo: ws.cell(row=linha, column=col) for campo, col in cols.items()}
        antes = len(erros)
        capacidade = _ler(
            cel["capacidade_gb"], chave, erros, para_capacidade, obrigatorio="Informe a capacidade."
        )
        preco = _ler(
            cel["preco_pix"], chave, erros, para_decimal, obrigatorio="Informe o preço Pix."
        )
        quantidade = _ler(
            cel["quantidade"],
            chave,
            erros,
            lambda v: para_int(v, "número inteiro"),
            obrigatorio="Informe a quantidade.",
        )
        bateria = (
            _ler(cel["bateria_pct"], chave, erros, lambda v: para_int(v, "percentual inteiro"))
            if "bateria_pct" in cel
            else None
        )
        if len(erros) > antes:
            continue
        entradas.append(
            EntradaLinhaEstoque(
                sku=texto(cel["sku"].value),
                marca=(texto(cel["marca"].value) if "marca" in cel else "") or _MARCA_APPLE,
                modelo=texto(cel["modelo"].value),
                capacidade_gb=capacidade,  # type: ignore[arg-type]
                cor=texto(cel["cor"].value),
                condicao=_condicao(cel["condicao"].value),
                preco_pix=preco,  # type: ignore[arg-type]
                quantidade=quantidade,  # type: ignore[arg-type]
                bateria_pct=bateria,
            )
        )
        origem = {campo: _ref(chave, c) for campo, c in cel.items()}
        origem[LINHA] = f"{chave}!A{linha}"
        origens.append(origem)
    return Leitura(entradas, origens, erros)
