import pytest

from app.domain.valores import MODELOS_IPHONE, ModeloAparelho

SE = "iPhone SE (2ª ou 3ª geração)"

# (canônico, variações que devem normalizar para ele)
TABELA: list[tuple[str, list[str]]] = [
    ("iPhone 8", ["8", "iphone 8", "IPHONE8"]),
    ("iPhone 8 Plus", ["8 plus", "iPhone 8 Plus", "iphone8plus", "8+"]),
    ("iPhone X", ["x", "iPhone X", "iphone x"]),
    ("iPhone XR", ["xr", "iPhone XR", "IPHONEXR"]),
    ("iPhone XS", ["xs", "iPhone XS"]),
    ("iPhone XS Max", ["xs max", "iPhone XS Max", "iphone xsmax"]),
    (SE, ["se", "se 2", "se 3", "iphone se 3a geracao", "iPhone SE 2ª geração", SE, "iPhone SE"]),
    ("iPhone 11", ["11", "iphone 11", "IPhone11"]),
    ("iPhone 11 Pro", ["11 pro", "iphone 11 pro", "iPhone11Pro"]),
    ("iPhone 11 Pro Max", ["11 pro max", "iphone 11 pro max", "11promax"]),
    ("iPhone 12 mini", ["12 mini", "iPhone 12 Mini", "iphone12mini"]),
    ("iPhone 12", ["12", "iPhone 12"]),
    ("iPhone 12 Pro", ["12 pro", "iPhone 12 PRO"]),
    ("iPhone 12 Pro Max", ["12 pro max", "iPhone12ProMax"]),
    ("iPhone 13 mini", ["13 mini", "iPhone 13 Mini"]),
    ("iPhone 13", ["13", "iphone 13"]),
    ("iPhone 13 Pro", ["13 pro", "iPhone 13 Pro"]),
    ("iPhone 13 Pro Max", ["13 pro max", "iphone 13 pro max"]),
    ("iPhone 14", ["14", "iphone 14"]),
    ("iPhone 14 Plus", ["14 plus", "iPhone 14 Plus", "14+"]),
    ("iPhone 14 Pro", ["14 pro", "iPhone 14 Pro"]),
    ("iPhone 14 Pro Max", ["14 pro max", "iphone 14 pro max"]),
    ("iPhone 15", ["15", "iphone 15"]),
    ("iPhone 15 Plus", ["15 plus", "iPhone 15 Plus"]),
    ("iPhone 15 Pro", ["15 pro", "iphone 15 pro"]),
    (
        "iPhone 15 Pro Max",
        ["15 pro max", "iphone 15 pro max", "IPhone15 Pro Max", "iPhone 15 Pro Max"],
    ),
    ("iPhone 16e", ["16e", "16 e", "iphone 16e", "iPhone 16E"]),
    ("iPhone 16", ["16", "iphone 16"]),
    ("iPhone 16 Plus", ["16 plus", "iPhone 16 Plus"]),
    ("iPhone 16 Pro", ["16 pro", "iphone 16 pro"]),
    ("iPhone 16 Pro Max", ["16 pro max", "iPhone 16 Pro Max"]),
    ("iPhone 17", ["17", "iphone 17"]),
    ("iPhone Air", ["air", "Air", "iphone air", "iPhone Air"]),
    ("iPhone 17 Pro", ["17 pro", "iPhone 17 Pro"]),
    ("iPhone 17 Pro Max", ["17 pro max", "iPhone 17 Pro Max", "  iphone   17  pro   max "]),
]


def test_tabela_cobre_todos_os_modelos() -> None:
    assert [c for c, _ in TABELA] == list(MODELOS_IPHONE)
    assert len(MODELOS_IPHONE) == 35
    assert len(set(MODELOS_IPHONE)) == 35


@pytest.mark.parametrize(
    ("canonico", "variacao"),
    [(c, v) for c, vs in TABELA for v in vs],
)
def test_normalizacao_tolerante(canonico: str, variacao: str) -> None:
    m = ModeloAparelho.de(variacao)
    assert m.nome == canonico
    assert m.marca == "Apple"
    assert m.conhecido
    assert m == ModeloAparelho.de(canonico)


def test_exemplos_da_issue() -> None:
    nomes = {ModeloAparelho.de(t).nome for t in ("iphone 15 pro max", "IPhone15 Pro Max")}
    assert nomes == {"iPhone 15 Pro Max"}
    assert ModeloAparelho.de("se 2") == ModeloAparelho.de("iphone se 3a geracao")


def test_modelos_distintos_nao_colidem() -> None:
    assert ModeloAparelho.de("13") != ModeloAparelho.de("13 mini")
    assert ModeloAparelho.de("11 pro") != ModeloAparelho.de("11 pro max")
    assert ModeloAparelho.de("x") != ModeloAparelho.de("xr")


def test_apple_desconhecido_mantem_title_case_com_grafia_iphone() -> None:
    m = ModeloAparelho.de("iphone 99 ultra")
    assert not m.conhecido
    assert m.marca == "Apple"
    assert m.nome == "iPhone 99 Ultra"


def test_outras_marcas() -> None:
    m = ModeloAparelho.de("galaxy  s23 ULTRA", marca="samsung")
    assert m.marca == "Samsung"
    assert m.nome == "Galaxy S23 Ultra"
    assert not m.conhecido
    assert m == ModeloAparelho.de("Galaxy S23 Ultra", marca="Samsung")
    assert m != ModeloAparelho.de("Galaxy S23 Ultra")


def test_vazio_invalido_e_imutavel() -> None:
    with pytest.raises(ValueError):
        ModeloAparelho.de("   ")
    m = ModeloAparelho.de("16")
    with pytest.raises(AttributeError):
        m.nome = "x"  # type: ignore[misc]
    assert str(m) == "iPhone 16"
    assert {m, ModeloAparelho.de("iphone 16")} == {m}


def test_iphone_fora_da_lista_mantem_a_grafia_iphone() -> None:
    """Modelo novo (ainda nao canonico) nao vira 'Iphone 18 Pro Max' no texto ao cliente."""
    m = ModeloAparelho.de("IPHONE 18 PRO MAX")
    assert (m.marca, m.nome, m.conhecido) == ("Apple", "iPhone 18 Pro Max", False)
    assert ModeloAparelho.de("iphone 18 pro max") == m
