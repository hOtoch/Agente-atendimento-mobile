"""Parser heuristico PURO de descricao de produto do ERP ("IPH 15 PRO 256 TIT NAT").

Serve de fallback do adaptador (so com confianca ALTA) e de sugestao de mapeamento no
onboarding. Nunca decide sozinho com confianca baixa.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.domain.estoque import Condicao
from app.domain.valores import Capacidade, ModeloAparelho


class Confianca(StrEnum):
    ALTA = "alta"
    BAIXA = "baixa"


@dataclass(frozen=True, slots=True)
class SugestaoMapeamento:
    modelo: ModeloAparelho
    capacidade: Capacidade | None
    cor: str | None
    condicao: Condicao
    bateria_pct: int | None
    confianca: Confianca


_ACESSORIOS: Final = frozenset(
    [
        "CAPA",
        "CAPINHA",
        "CASE",
        "CARREGADOR",
        "CABO",
        "PELICULA",
        "FONTE",
        "FONE",
        "FONES",
        "ADAPTADOR",
        "SUPORTE",
        "PROTETOR",
        "AIRPODS",
        "WATCH",
        "PULSEIRA",
        "POWERBANK",
    ]
)
_PREFIXO: Final = re.compile(r"\b(?:APPLE\s+)?(?:IPHONE|IPH|IP)\s+(.+)$")
_MODELO: Final = re.compile(
    r"^(?:(?P<num>\d{1,2}E?|X[RS]?)(?:\s+(?P<suf>AIR|PRO\s*MAX|PM|PLUS|PRO|MAX|MINI))?"
    r"|(?P<air>AIR))\b"
)
_BAT: Final = re.compile(r"\bBAT\s*(\d{1,3})\b")
_CAPACIDADE: Final = re.compile(r"\b(\d{1,4})\s*(GB|TB|G|T)?\b")
_CAPACIDADES_VALIDAS: Final = frozenset({16, 32, 64, 128, 256, 512, 1024})
_SUFIXOS: Final = {
    "PM": "Pro Max",
    "PROMAX": "Pro Max",
    "MAX": "Max",
    "PRO": "Pro",
    "PLUS": "Plus",
    "MINI": "mini",
    "": "",
}

# (regex, nome canonico); mais especificas primeiro.
_CORES: Final[tuple[tuple[str, str], ...]] = (
    (r"TIT(?:ANIO)?\s+NAT(?:URAL)?", "Titânio Natural"),
    (r"TIT(?:ANIO)?\s+AZUL", "Titânio Azul"),
    (r"TIT(?:ANIO)?\s+PRETO", "Titânio Preto"),
    (r"TIT(?:ANIO)?\s+BRANCO", "Titânio Branco"),
    (r"TIT(?:ANIO)?\s+DESERTO", "Titânio Deserto"),
    (r"PRETO\s+ESPACIAL", "Preto Espacial"),
    (r"MEIA[\s-]?NOITE", "Meia-Noite"),
    (r"VERDE[\s-]?AZULADO", "Verde-Azulado"),
    (r"AZUL\s+NEBLINA", "Azul Neblina"),
    (r"DOURADO\s+NUVEM", "Dourado Nuvem"),
    (r"LARANJA\s+COSMICO", "Laranja Cósmico"),
    (r"AZUL\s+PROF(?:UNDO)?", "Azul Profundo"),
    (r"PRETO", "Preto"),
    (r"BRANCO", "Branco"),
    (r"AZUL", "Azul"),
    (r"ROXO", "Roxo"),
    (r"ROSA", "Rosa"),
    (r"VERDE", "Verde"),
    (r"VERMELHO", "Vermelho"),
    (r"AMARELO", "Amarelo"),
    (r"ESTELAR", "Estelar"),
    (r"ULTRAMARINO", "Ultramarino"),
    (r"LAVANDA", "Lavanda"),
    (r"PRATA", "Prata"),
    (r"DOURADO", "Dourado"),
    (r"LARANJA", "Laranja"),
)
_CORES_RE: Final = tuple((re.compile(rf"\b{r}\b"), nome) for r, nome in _CORES)


def _normalizar(texto: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(ascii_.upper().replace("/", " ").split())


def _palavras(texto: str) -> set[str]:
    return set(re.split(r"[^A-Z0-9]+", texto))


def extrair_bateria(descricao: str) -> int | None:
    """Percentual de bateria do marcador `BAT NN` (0 a 100), ou None."""
    casou = _BAT.search(_normalizar(descricao))
    if casou is None:
        return None
    pct = int(casou.group(1))
    return pct if 0 <= pct <= 100 else None


def _nome_modelo(casou: re.Match[str]) -> str:
    if casou.group("air"):
        return "iPhone Air"
    num = casou.group("num").lower()
    suf = (casou.group("suf") or "").replace(" ", "")
    if suf == "AIR":
        return "iPhone Air"
    numero = num.upper() if num.startswith("x") else num
    return f"iPhone {numero} {_SUFIXOS[suf]}".strip()


def _capacidade(texto: str) -> Capacidade | None:
    for casou in _CAPACIDADE.finditer(texto):
        numero, unidade = int(casou.group(1)), casou.group(2)
        gb = numero * 1024 if unidade in ("TB", "T") else numero
        if gb in _CAPACIDADES_VALIDAS:
            return Capacidade(gb)
    return None


def _cor(texto: str) -> str | None:
    for padrao, nome in _CORES_RE:
        if padrao.search(texto):
            return nome
    return None


def interpretar_descricao(descricao: str) -> SugestaoMapeamento | None:
    """Interpreta a descricao de um produto; None se nao for um iPhone (ex.: acessorio)."""
    texto = _normalizar(descricao)
    if not texto or _ACESSORIOS & _palavras(texto):
        return None
    prefixo = _PREFIXO.search(texto)
    if prefixo is None:
        return None
    resto = prefixo.group(1)
    casou = _MODELO.match(resto)
    if casou is None:
        return None
    modelo = ModeloAparelho.de(_nome_modelo(casou))
    resto = resto[casou.end() :]

    condicao = Condicao.SEMINOVO if _palavras(texto) & {"SEMINOVO", "SN"} else Condicao.NOVO
    bateria = extrair_bateria(texto) if condicao is Condicao.SEMINOVO else None
    sem_bateria = _BAT.sub(" ", resto)

    capacidade = _capacidade(sem_bateria)
    cor = _cor(sem_bateria)
    alta = modelo.conhecido and capacidade is not None and cor is not None
    return SugestaoMapeamento(
        modelo=modelo,
        capacidade=capacidade,
        cor=cor,
        condicao=condicao,
        bateria_pct=bateria,
        confianca=Confianca.ALTA if alta else Confianca.BAIXA,
    )
