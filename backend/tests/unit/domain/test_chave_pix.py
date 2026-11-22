"""Chave Pix da loja: tipo, chave e favorecido validados no dominio."""

from __future__ import annotations

import pytest

from app.domain.chave_pix import ChavePix, ChavePixInvalida, TipoChavePix, montar_chave_pix

FAVORECIDO = "Loja Demo Celulares LTDA"


def _montar(tipo: str, chave: str, favorecido: str = FAVORECIDO) -> ChavePix:
    return montar_chave_pix(tipo, chave, favorecido)


def _campos(excecao: ChavePixInvalida) -> dict[str, str]:
    return dict(excecao.erros)


# --- CPF ----------------------------------------------------------------------------------


@pytest.mark.parametrize("texto", ["529.982.247-25", "52998224725", " 529 982 247 25 "])
def test_cpf_valido_normaliza_para_so_digitos(texto: str) -> None:
    chave = _montar("cpf", texto)
    assert chave == ChavePix(TipoChavePix.CPF, "52998224725", FAVORECIDO)


@pytest.mark.parametrize(
    "texto", ["529.982.247-26", "111.111.111-11", "123", "abcdefghijk", "5299822472"]
)
def test_cpf_invalido(texto: str) -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("cpf", texto)
    assert "chave" in _campos(exc.value)


# --- CNPJ ---------------------------------------------------------------------------------


def test_cnpj_valido_normaliza() -> None:
    assert _montar("cnpj", "11.222.333/0001-81").chave == "11222333000181"


def test_cnpj_alfanumerico_valido_normaliza_em_maiusculas() -> None:
    assert _montar("cnpj", "12.abc.345/01de-35").chave == "12ABC34501DE35"


@pytest.mark.parametrize("texto", ["11.222.333/0001-82", "00000000000000", "1122233300018"])
def test_cnpj_invalido(texto: str) -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("cnpj", texto)
    assert "chave" in _campos(exc.value)


# --- e-mail -------------------------------------------------------------------------------


def test_email_valido_normaliza_em_minusculas() -> None:
    assert _montar("email", "  Pix@LojaDemo.Exemplo ").chave == "pix@lojademo.exemplo"


@pytest.mark.parametrize(
    "texto", ["sem-arroba", "a@b", "a b@c.com", "@x.com", "a@" + "x" * 80 + ".com"]
)
def test_email_invalido(texto: str) -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("email", texto)
    assert "chave" in _campos(exc.value)


# --- telefone -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    ["+55 11 91234-5678", "(11) 91234-5678", "11912345678", "5511912345678", "+5511912345678"],
)
def test_telefone_valido_normaliza_para_formato_pix(texto: str) -> None:
    assert _montar("telefone", texto).chave == "+5511912345678"


def test_telefone_fixo_com_ddd_e_aceito() -> None:
    assert _montar("telefone", "(11) 3123-4567").chave == "+551131234567"


@pytest.mark.parametrize(
    "texto", ["91234-5678", "(01) 91234-5678", "(11) 81234-5678", "+1 415 555 0100", "119123"]
)
def test_telefone_invalido(texto: str) -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("telefone", texto)
    assert "chave" in _campos(exc.value)


# --- chave aleatoria ----------------------------------------------------------------------


def test_aleatoria_valida_normaliza_em_minusculas() -> None:
    chave = _montar("aleatoria", "123E4567-E89B-42D3-A456-426614174000")
    assert chave.chave == "123e4567-e89b-42d3-a456-426614174000"


@pytest.mark.parametrize("texto", ["123", "123e4567e89b42d3a456426614174000", "x" * 36, ""])
def test_aleatoria_invalida(texto: str) -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("aleatoria", texto)
    assert "chave" in _campos(exc.value)


# --- tipo e favorecido --------------------------------------------------------------------


def test_tipo_desconhecido() -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("bitcoin", "x")
    assert "tipo" in _campos(exc.value)


def test_favorecido_obrigatorio() -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("email", "pix@lojademo.exemplo", "   ")
    assert "favorecido" in _campos(exc.value)


def test_favorecido_e_aparado() -> None:
    assert _montar("email", "pix@lojademo.exemplo", "  Loja Demo ").favorecido == "Loja Demo"


def test_coleta_todos_os_erros_de_uma_vez() -> None:
    with pytest.raises(ChavePixInvalida) as exc:
        _montar("cpf", "123", "")
    assert set(_campos(exc.value)) == {"chave", "favorecido"}


def test_chave_nao_e_confundida_entre_tipos() -> None:
    # um CPF valido nao serve como CNPJ
    with pytest.raises(ChavePixInvalida):
        _montar("cnpj", "529.982.247-25")
