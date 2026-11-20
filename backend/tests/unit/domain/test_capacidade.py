import pytest

from app.domain.valores import Capacidade


@pytest.mark.parametrize(
    ("entrada", "gb"),
    [
        ("64", 64),
        ("128GB", 128),
        ("128 gb", 128),
        ("128G", 128),
        ("256 GB", 256),
        ("512", 512),
        ("1TB", 1024),
        ("1 tb", 1024),
        ("2TB", 2048),
        ("1,5TB", 1536),
        (128, 128),
    ],
)
def test_normaliza_para_gb(entrada: str | int, gb: int) -> None:
    assert Capacidade(entrada) == gb
    assert int(Capacidade(entrada)) == gb


def test_tb_igual_1024() -> None:
    assert Capacidade("1TB") == 1024


def test_ordenavel() -> None:
    caps = [Capacidade("1TB"), Capacidade("64"), Capacidade("256GB")]
    assert sorted(caps) == [64, 256, 1024]
    assert Capacidade("128") < Capacidade("1TB")
    assert max(caps) == Capacidade("1TB")


def test_str_e_hash() -> None:
    assert str(Capacidade("128 gb")) == "128GB"
    assert str(Capacidade("1TB")) == "1TB"
    assert {Capacidade("128"), Capacidade("128GB")} == {Capacidade(128)}


@pytest.mark.parametrize("ruim", ["", "abc", "0", "-64", "12XB", 0, -1])
def test_invalida(ruim: str | int) -> None:
    with pytest.raises(ValueError):
        Capacidade(ruim)


def test_float_rejeitado() -> None:
    with pytest.raises(TypeError):
        Capacidade(128.0)  # type: ignore[arg-type]
