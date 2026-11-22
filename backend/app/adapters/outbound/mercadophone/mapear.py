"""Mapeamento puro (sem IO) do item cru de `list_inventory` do Mercado Phone.

Traduz o item do ERP para `LinhaEstoqueLocal` + id do produto no ERP, ou para um `Descarte`
tipado quando o item nao e ofertavel (a regra de oferta vive em `app.domain.oferta`).
Itens de outra loja (`filtro_loja`) viram `ForaDaLoja` e nao contam como descarte de qualidade.

Decisoes:
- `valorVenda` e o preco base (`preco_pix`); `valorVenda2/3` e `valorCusto` sao ignorados.
- LACRADO/NOVO -> novo; SEMINOVO/"SEMI NOVO" -> seminovo; qualquer outro valor -> descarte.
- `saudeBateria` aceita fracao (0..1) ou percentual (>1, ate 100); so vale para seminovo.
- Marca: pelo mapa `marcaId -> nome` (de `list_brands`); sem marca resolvida, nome que
  comeca com IPHONE e inferido como Apple; senao o item e descartado.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

from app.application.config.modelos import LinhaEstoqueLocal
from app.domain.estoque import Condicao
from app.domain.oferta import MotivoDescarte, motivo_nao_ofertavel
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

COR_NAO_INFORMADA: Final = "não informada"
_DISPONIVEL: Final = "disponivel para venda"
_CONDICAO_POR_ESTADO: Final[dict[str, Condicao]] = {
    "lacrado": Condicao.NOVO,
    "novo": Condicao.NOVO,
    "seminovo": Condicao.SEMINOVO,
}


@dataclass(frozen=True, slots=True)
class LinhaErp:
    """Linha pronta para o estoque local, com o id do produto no ERP."""

    linha: LinhaEstoqueLocal
    erp_produto_id: int


@dataclass(frozen=True, slots=True)
class Descarte:
    """Item do ERP que nao pode ser ofertado."""

    sku: str
    motivo: MotivoDescarte
    erp_produto_id: int | None = None


@dataclass(frozen=True, slots=True)
class ForaDaLoja:
    """Item de outra loja (pelo `filtro_loja`): ignorado, nao e descarte de qualidade."""

    sku: str


@dataclass(frozen=True, slots=True)
class RelatorioMapeamento:
    lidos: int
    importados: int
    outra_loja: int
    por_motivo: Mapping[MotivoDescarte, int] = field(default_factory=dict)

    @property
    def descartados(self) -> int:
        return sum(self.por_motivo.values())


@dataclass(frozen=True, slots=True)
class ResultadoMapeamento:
    linhas: tuple[LinhaErp, ...]
    descartes: tuple[Descarte, ...]
    relatorio: RelatorioMapeamento


# --- helpers de leitura tolerante ---


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _norm(texto: Any) -> str:
    """Minusculas, sem acento, espacos colapsados; '' se nao for texto."""
    if not isinstance(texto, str):
        return ""
    return " ".join(_sem_acento(texto).lower().split())


def _texto(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    limpo = " ".join(valor.split())
    return limpo or None


def _inteiro(valor: Any) -> int | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    return None


def _decimal(valor: Any) -> Decimal | None:
    """Numero do JSON (int/float/Decimal/str numerica) como Decimal exato; None se invalido."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor).strip())
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None


def _dinheiro(valor: Any) -> Dinheiro | None:
    numero = _decimal(valor)
    return None if numero is None else Dinheiro.de(numero)


def _quantidade(valor: Any) -> int:
    numero = _decimal(valor)
    return 0 if numero is None else int(numero)


def _condicao(item: Mapping[str, Any]) -> Condicao | None:
    estado = _norm(item.get("estadoProdutoDescricao")).replace("-", "").replace(" ", "")
    return _CONDICAO_POR_ESTADO.get(estado)


def _capacidade(item: Mapping[str, Any]) -> Capacidade | None:
    texto = _texto(item.get("gbDescricao"))
    if texto is None:
        return None
    try:
        return Capacidade(texto)
    except ValueError:
        return None


def _bateria_pct(valor: Any) -> int | None:
    """Fracao 0..1 (0.86) ou percentual (86) -> % inteiro; vazio/zero/invalido -> None."""
    numero = _decimal(valor)
    if numero is None or numero <= 0:
        return None
    pct = numero * 100 if numero <= 1 else numero
    if pct > 100:
        return None
    return int(pct.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _e_celular(item: Mapping[str, Any]) -> bool:
    if any(item.get(flag) in (1, True, "1") for flag in ("snAcessorio", "snPeca", "snServico")):
        return False
    return _norm(item.get("tipoProdutoDescricao")) == "celular"


def _marca(item: Mapping[str, Any], marcas: Mapping[int, str], modelo: str | None) -> str | None:
    marca_id = _inteiro(item.get("marcaId"))
    if marca_id is not None and (nome := marcas.get(marca_id)):
        return nome
    if modelo is not None and _norm(modelo).startswith("iphone"):
        return "Apple"
    return None


def _sku(item: Mapping[str, Any], erp_id: int | None) -> str:
    sku = _texto(item.get("sku"))
    if sku is not None:
        return sku
    return f"MP-{erp_id}" if erp_id is not None else "<sem id>"


def _da_loja(item: Mapping[str, Any], filtro_loja: str) -> bool:
    """Casa o comeco do `obs` (antes de '|') com o filtro, respeitando limite de palavra."""
    obs = item.get("obs")
    if not isinstance(obs, str):
        return False
    inicio = _norm(obs.split("|", 1)[0])
    alvo = _norm(filtro_loja)
    if not inicio.startswith(alvo):
        return False
    return len(inicio) == len(alvo) or not inicio[len(alvo)].isalnum()


# --- API publica ---


def mapa_de_marcas(brands: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """`list_brands` (`[{"id": 501, "name": "Apple"}]`) -> `{501: "Apple"}`; ignora lixo."""
    mapa: dict[int, str] = {}
    for brand in brands:
        if not isinstance(brand, Mapping):
            continue
        marca_id = _inteiro(brand.get("id"))
        nome = _texto(brand.get("name"))
        if marca_id is not None and nome is not None:
            mapa[marca_id] = nome
    return mapa


def mapear_item(
    item: Mapping[str, Any],
    marcas: Mapping[int, str],
    filtro_loja: str | None = None,
) -> LinhaErp | Descarte | ForaDaLoja:
    """Traduz um item cru de `list_inventory`; nunca levanta por dado sujo."""
    if not isinstance(item, Mapping):
        return Descarte("<invalido>", MotivoDescarte.ITEM_MALFORMADO)
    erp_id = _inteiro(item.get("id"))
    sku = _sku(item, erp_id)
    if filtro_loja is not None and filtro_loja.strip() and not _da_loja(item, filtro_loja):
        return ForaDaLoja(sku)
    if erp_id is None:
        return Descarte(sku, MotivoDescarte.ITEM_MALFORMADO)

    modelo_txt = _texto(item.get("aparelhoDescricao"))
    marca = _marca(item, marcas, modelo_txt)
    capacidade = _capacidade(item)
    condicao = _condicao(item)
    preco = _dinheiro(item.get("valorVenda"))
    motivo = motivo_nao_ofertavel(
        e_celular=_e_celular(item),
        disponivel=_norm(item.get("disponibilidade")) == _DISPONIVEL,
        quantidade=_quantidade(item.get("quantidade")),
        modelo=modelo_txt,
        marca=marca,
        capacidade=capacidade,
        condicao=condicao,
        preco=preco,
    )
    if motivo is not None:
        return Descarte(sku, motivo, erp_id)
    # motivo None garante os campos presentes (o mypy nao sabe)
    assert modelo_txt is not None and marca is not None
    assert capacidade is not None and condicao is not None and preco is not None
    cor = _texto(item.get("corDescricao"))
    linha = LinhaEstoqueLocal(
        sku=sku,
        modelo=ModeloAparelho.de(modelo_txt, marca),
        capacidade=capacidade,
        cor=cor.title() if cor else COR_NAO_INFORMADA,
        condicao=condicao,
        preco_pix=preco,
        quantidade=_quantidade(item.get("quantidade")),
        bateria_pct=(
            _bateria_pct(item.get("saudeBateria")) if condicao is Condicao.SEMINOVO else None
        ),
    )
    return LinhaErp(linha, erp_id)


def mapear_inventario(
    itens: Iterable[Mapping[str, Any]],
    marcas: Mapping[int, str],
    filtro_loja: str | None = None,
) -> ResultadoMapeamento:
    """Mapeia o inventario inteiro e monta o relatorio (lidos, importados, descartes por motivo)."""
    linhas: list[LinhaErp] = []
    descartes: list[Descarte] = []
    lidos = outra_loja = 0
    for item in itens:
        lidos += 1
        resultado = mapear_item(item, marcas, filtro_loja)
        if isinstance(resultado, LinhaErp):
            linhas.append(resultado)
        elif isinstance(resultado, Descarte):
            descartes.append(resultado)
        else:
            outra_loja += 1
    contagem = Counter(d.motivo for d in descartes)
    relatorio = RelatorioMapeamento(
        lidos=lidos,
        importados=len(linhas),
        outra_loja=outra_loja,
        por_motivo=dict(contagem),
    )
    return ResultadoMapeamento(tuple(linhas), tuple(descartes), relatorio)
