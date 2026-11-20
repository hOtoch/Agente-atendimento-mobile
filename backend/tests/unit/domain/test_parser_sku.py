"""Parser heuristico de descricao de SKU, validado contra TODO o seed do erp-mock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.estoque import Condicao
from app.domain.parser_sku import Confianca, extrair_bateria, interpretar_descricao

SEED = Path(__file__).resolve().parents[4] / "services/erp-mock/app/dados/produtos.json"
DESCRICOES = {p["sku"]: p["descricao"] for p in json.loads(SEED.read_text(encoding="utf-8"))}

N, S = Condicao.NOVO, Condicao.SEMINOVO

# sku -> (modelo, capacidade_gb, cor, condicao, bateria)
ESPERADO: dict[str, tuple[str, int, str, Condicao, int | None]] = {
    "APL-000001": ("iPhone 11", 64, "Preto", S, 82),
    "APL-000002": ("iPhone 11", 128, "Branco", S, 85),
    "APL-000003": ("iPhone 12", 64, "Azul", S, 84),
    "APL-000004": ("iPhone 12", 128, "Preto", S, 80),
    "APL-000005": ("iPhone 13", 128, "Azul", S, 87),
    "APL-000006": ("iPhone 13", 256, "Estelar", S, 89),
    "APL-000007": ("iPhone 13", 128, "Meia-Noite", N, None),
    "APL-000008": ("iPhone 14", 128, "Roxo", S, None),
    "APL-000009": ("iPhone 14 Plus", 128, "Azul", S, 90),
    "APL-000010": ("iPhone 14 Pro Max", 512, "Roxo", S, None),
    "APL-000011": ("iPhone 14 Pro", 256, "Preto Espacial", N, None),
    "APL-000012": ("iPhone 15", 128, "Rosa", N, None),
    "APL-000013": ("iPhone 15 Plus", 256, "Azul", N, None),
    "APL-000014": ("iPhone 15 Pro", 256, "Titânio Natural", N, None),
    "APL-000015": ("iPhone 15 Pro", 128, "Titânio Azul", S, 91),
    "APL-000016": ("iPhone 15 Pro Max", 256, "Titânio Preto", N, None),
    "APL-000017": ("iPhone 15 Pro Max", 512, "Titânio Branco", S, 93),
    "APL-000018": ("iPhone 16e", 128, "Branco", N, None),
    "APL-000019": ("iPhone 16e", 256, "Preto", N, None),
    "APL-000020": ("iPhone 16", 128, "Ultramarino", N, None),
    "APL-000021": ("iPhone 16", 256, "Rosa", N, None),
    "APL-000022": ("iPhone 16 Plus", 128, "Verde-Azulado", N, None),
    "APL-000023": ("iPhone 16 Pro", 128, "Titânio Deserto", N, None),
    "APL-000024": ("iPhone 16 Pro", 256, "Titânio Natural", S, 95),
    "APL-000025": ("iPhone 16 Pro", 512, "Titânio Preto", N, None),
    "APL-000026": ("iPhone 16 Pro Max", 256, "Titânio Deserto", N, None),
    "APL-000027": ("iPhone 16 Pro Max", 512, "Titânio Natural", N, None),
    "APL-000028": ("iPhone 16 Pro Max", 1024, "Titânio Branco", S, 96),
    "APL-000029": ("iPhone 17", 256, "Lavanda", N, None),
    "APL-000030": ("iPhone 17", 256, "Preto", N, None),
    "APL-000031": ("iPhone 17", 512, "Azul Neblina", N, None),
    "APL-000032": ("iPhone Air", 256, "Preto Espacial", N, None),
    "APL-000033": ("iPhone Air", 512, "Dourado Nuvem", N, None),
    "APL-000034": ("iPhone 17 Pro", 256, "Laranja Cósmico", N, None),
    "APL-000035": ("iPhone 17 Pro", 512, "Azul Profundo", N, None),
    "APL-000036": ("iPhone 17 Pro", 256, "Prata", S, 98),
    "APL-000037": ("iPhone 17 Pro Max", 256, "Azul Profundo", N, None),
    "APL-000038": ("iPhone 17 Pro Max", 512, "Prata", N, None),
    "APL-000039": ("iPhone 17 Pro Max", 1024, "Laranja Cósmico", N, None),
}
ACESSORIOS = ["APL-000040", "APL-000041", "APL-000042"]


def test_seed_tem_39_celulares_e_3_acessorios() -> None:
    assert len(ESPERADO) == 39
    assert set(DESCRICOES) == set(ESPERADO) | set(ACESSORIOS)


@pytest.mark.parametrize("sku", sorted(ESPERADO))
def test_celular_do_seed(sku: str) -> None:
    modelo, capacidade, cor, condicao, bateria = ESPERADO[sku]
    sugestao = interpretar_descricao(DESCRICOES[sku])
    assert sugestao is not None, DESCRICOES[sku]
    assert sugestao.modelo.nome == modelo
    assert sugestao.modelo.conhecido
    assert sugestao.capacidade == capacidade
    assert sugestao.cor == cor
    assert sugestao.condicao is condicao
    assert sugestao.bateria_pct == bateria
    assert sugestao.confianca is Confianca.ALTA


@pytest.mark.parametrize("sku", ACESSORIOS)
def test_acessorio_do_seed_nao_e_celular(sku: str) -> None:
    assert interpretar_descricao(DESCRICOES[sku]) is None


@pytest.mark.parametrize(
    "descricao",
    [
        "CAPA TRANSPARENTE IPHONE 15 PRO MAX",
        "PELÍCULA 3D IPHONE 14",
        "Carregador iPhone 20W",
        "CABO LIGHTNING P/ IPHONE 11",
    ],
)
def test_acessorio_que_cita_iphone_vira_none(descricao: str) -> None:
    assert interpretar_descricao(descricao) is None


@pytest.mark.parametrize(
    ("descricao", "modelo", "capacidade", "cor"),
    [
        ("iphone 15 pro max 256gb titanio natural", "iPhone 15 Pro Max", 256, "Titânio Natural"),
        ("Apple iPhone 14 Plus 128 GB Azul", "iPhone 14 Plus", 128, "Azul"),
        ("IP 17 PRO 1 TB PRATA", "iPhone 17 Pro", 1024, "Prata"),
        ("IPH 16 PRO MAX 256 LARANJA COSMICO", "iPhone 16 Pro Max", 256, "Laranja Cósmico"),
        ("IPHONE 17 AIR 256 PRETO ESPACIAL", "iPhone Air", 256, "Preto Espacial"),
    ],
)
def test_variacoes_de_escrita(descricao: str, modelo: str, capacidade: int, cor: str) -> None:
    sugestao = interpretar_descricao(descricao)
    assert sugestao is not None
    assert (sugestao.modelo.nome, sugestao.capacidade, sugestao.cor) == (modelo, capacidade, cor)


def test_sem_cor_ou_capacidade_tem_confianca_baixa() -> None:
    sem_cor = interpretar_descricao("IPH 15 128")
    assert sem_cor is not None
    assert sem_cor.cor is None
    assert sem_cor.confianca is Confianca.BAIXA
    sem_cap = interpretar_descricao("IPH 15 PRETO")
    assert sem_cap is not None
    assert sem_cap.capacidade is None
    assert sem_cap.confianca is Confianca.BAIXA


def test_modelo_desconhecido_nao_tem_confianca_alta() -> None:
    sugestao = interpretar_descricao("IPH 99 256 PRETO")
    assert sugestao is None or sugestao.confianca is Confianca.BAIXA


def test_texto_sem_iphone_e_none() -> None:
    assert interpretar_descricao("GALAXY S24 256 PRETO") is None
    assert interpretar_descricao("") is None


def test_extrair_bateria() -> None:
    assert extrair_bateria("QUALQUER COISA BAT 87") == 87
    assert extrair_bateria("sem marcador") is None
    assert extrair_bateria("BAT 150") is None
