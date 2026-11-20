"""Avaliação de troca do usado (context.md §3.1)."""

from dataclasses import replace

import pytest

from app.domain.troca import (
    SEM,
    AvaliacaoNaLoja,
    CondicaoUsado,
    LinhaTroca,
    MotivoLoja,
    TabelaTroca,
    ValorTroca,
    avaliar_troca,
)
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

IPHONE_16 = ModeloAparelho.de("iPhone 16")
IPHONE_15 = ModeloAparelho.de("iPhone 15")
GALAXY = ModeloAparelho.de("S24", marca="Samsung")
R = Dinheiro.de


def linha(
    modelo: ModeloAparelho = IPHONE_16,
    capacidade: int = 128,
    sem_detalhes: str = "3100",
    **descontos: Dinheiro | object,
) -> LinhaTroca:
    base: dict[str, Dinheiro | object] = {
        "desconto_tela": R("600"),
        "desconto_traseira": SEM,
        "desconto_carcaca": R("300"),
        "desconto_bateria": R("190"),
    }
    base.update(descontos)
    return LinhaTroca(
        modelo=modelo,
        capacidade=Capacidade(capacidade),
        valor_sem_detalhes=R(sem_detalhes),
        limite_bateria_pct=80,
        **base,  # type: ignore[arg-type]
    )


def tabela(*linhas: LinhaTroca, outras: tuple[LinhaTroca, ...] = ()) -> TabelaTroca:
    return TabelaTroca(linhas_apple=tuple(linhas), linhas_outras_marcas=outras)


def usado(**kw: object) -> CondicaoUsado:
    base: dict[str, object] = {
        "tela_danificada": False,
        "traseira_danificada": False,
        "carcaca_marcada": False,
        "bateria_pct": 100,
        "camera_ok": True,
        "outros_defeitos": (),
        "peca_trocada": False,
    }
    base.update(kw)
    return CondicaoUsado(**base)  # type: ignore[arg-type]


def avaliar(
    tab: TabelaTroca, cond: CondicaoUsado, modelo: ModeloAparelho = IPHONE_16, cap: int = 128
) -> ValorTroca | AvaliacaoNaLoja:
    return avaliar_troca(tab, modelo, Capacidade(cap), cond)


def motivo(res: ValorTroca | AvaliacaoNaLoja) -> MotivoLoja:
    assert isinstance(res, AvaliacaoNaLoja)
    return res.motivo


def test_exemplo_oficial() -> None:
    res = avaliar(tabela(linha()), usado(tela_danificada=True, bateria_pct=79))
    assert isinstance(res, ValorTroca)
    assert res.valor == R("2310")
    assert dict(res.descontos_aplicados) == {"tela": R("600"), "bateria": R("190")}


def test_aparelho_perfeito_vale_o_valor_sem_detalhes() -> None:
    res = avaliar(tabela(linha()), usado())
    assert res == ValorTroca(valor=R("3100"), descontos_aplicados=())


def test_bateria_exatamente_no_limite_nao_desconta() -> None:
    res = avaliar(tabela(linha()), usado(bateria_pct=80))
    assert isinstance(res, ValorTroca)
    assert res.valor == R("3100")
    assert res.descontos_aplicados == ()


def test_bateria_um_ponto_abaixo_do_limite_desconta() -> None:
    res = avaliar(tabela(linha()), usado(bateria_pct=79))
    assert isinstance(res, ValorTroca)
    assert res.valor == R("2910")


def test_sem_em_problema_relatado_manda_para_loja() -> None:
    res = avaliar(tabela(linha()), usado(traseira_danificada=True))
    assert motivo(res) is MotivoLoja.SEM_VALOR_WHATSAPP


def test_sem_em_problema_nao_relatado_e_ignorado() -> None:
    res = avaliar(tabela(linha()), usado(carcaca_marcada=True))
    assert isinstance(res, ValorTroca)
    assert res.valor == R("2800")


def test_sem_na_bateria_so_vale_se_abaixo_do_limite() -> None:
    tab = tabela(linha(desconto_bateria=SEM))
    assert isinstance(avaliar(tab, usado(bateria_pct=80)), ValorTroca)
    assert motivo(avaliar(tab, usado(bateria_pct=79))) is MotivoLoja.SEM_VALOR_WHATSAPP


def test_desconto_zero_nao_desconta_nem_aparece() -> None:
    tab = tabela(linha(desconto_tela=R("0")))
    res = avaliar(tab, usado(tela_danificada=True))
    assert isinstance(res, ValorTroca)
    assert res.valor == R("3100")
    assert res.descontos_aplicados == ()


def test_descontos_acumulados() -> None:
    res = avaliar(
        tabela(linha()), usado(tela_danificada=True, carcaca_marcada=True, bateria_pct=70)
    )
    assert isinstance(res, ValorTroca)
    assert res.valor == R("2010")
    assert [m for m, _ in res.descontos_aplicados] == ["tela", "carcaca", "bateria"]


def test_camera_com_defeito_manda_para_loja() -> None:
    assert motivo(avaliar(tabela(linha()), usado(camera_ok=False))) is MotivoLoja.OUTRO_DEFEITO


def test_outros_defeitos_mandam_para_loja() -> None:
    res = avaliar(tabela(linha()), usado(outros_defeitos=("Face ID",)))
    assert motivo(res) is MotivoLoja.OUTRO_DEFEITO


def test_peca_trocada_manda_para_loja() -> None:
    assert motivo(avaliar(tabela(linha()), usado(peca_trocada=True))) is MotivoLoja.PECA_TROCADA


def test_capacidade_inexistente_usa_menor_proxima() -> None:
    tab = tabela(
        linha(capacidade=128, sem_detalhes="3100"), linha(capacidade=512, sem_detalhes="4000")
    )
    res = avaliar(tab, usado(), cap=256)
    assert isinstance(res, ValorTroca)
    assert res.valor == R("3100")


def test_capacidade_acima_de_todas_usa_a_maior() -> None:
    tab = tabela(linha(capacidade=128), linha(capacidade=256, sem_detalhes="3500"))
    res = avaliar(tab, usado(), cap=1024)
    assert isinstance(res, ValorTroca)
    assert res.valor == R("3500")


def test_capacidade_exata_tem_prioridade() -> None:
    tab = tabela(linha(capacidade=128), linha(capacidade=256, sem_detalhes="3500"))
    res = avaliar(tab, usado(), cap=256)
    assert isinstance(res, ValorTroca)
    assert res.valor == R("3500")


def test_capacidade_abaixo_da_tabela_manda_para_loja() -> None:
    res = avaliar(tabela(linha(capacidade=128)), usado(), cap=64)
    assert motivo(res) is MotivoLoja.CAPACIDADE_ABAIXO_DA_TABELA


def test_buscar_devolve_none_para_modelo_ausente_e_linha_para_presente() -> None:
    tab = tabela(linha(capacidade=128), linha(capacidade=256))
    assert tab.buscar(IPHONE_15, Capacidade(128)) is None
    achada = tab.buscar(IPHONE_16, Capacidade(200))
    assert achada is not None
    assert achada.capacidade == 128


def test_valor_zero_manda_para_loja() -> None:
    tab = tabela(linha(sem_detalhes="600"))
    res = avaliar(tab, usado(tela_danificada=True))
    assert motivo(res) is MotivoLoja.VALOR_NAO_POSITIVO


def test_valor_negativo_manda_para_loja() -> None:
    tab = tabela(linha(sem_detalhes="500"))
    res = avaliar(tab, usado(tela_danificada=True))
    assert motivo(res) is MotivoLoja.VALOR_NAO_POSITIVO


def test_modelo_apple_fora_da_tabela() -> None:
    res = avaliar(tabela(linha()), usado(), modelo=IPHONE_15)
    assert motivo(res) is MotivoLoja.MODELO_FORA_DA_TABELA


def test_modelo_apple_desconhecido_fora_da_tabela() -> None:
    res = avaliar(tabela(linha()), usado(), modelo=ModeloAparelho.de("iPhone 99"))
    assert motivo(res) is MotivoLoja.MODELO_FORA_DA_TABELA


def test_outra_marca_sem_tabela_manda_para_loja() -> None:
    res = avaliar(tabela(linha()), usado(), modelo=GALAXY)
    assert motivo(res) is MotivoLoja.OUTRA_MARCA


def test_outra_marca_com_linha_avalia_normalmente() -> None:
    tab = tabela(linha(), outras=(linha(modelo=GALAXY, capacidade=256, sem_detalhes="2000"),))
    res = avaliar(tab, usado(tela_danificada=True), modelo=GALAXY, cap=256)
    assert isinstance(res, ValorTroca)
    assert res.valor == R("1400")


def test_outra_marca_com_tabela_mas_modelo_ausente_e_outra_marca() -> None:
    outro = ModeloAparelho.de("Edge", marca="Motorola")
    tab = tabela(linha(), outras=(linha(modelo=GALAXY),))
    assert motivo(avaliar(tab, usado(), modelo=outro)) is MotivoLoja.OUTRA_MARCA


# --- precedência: peça trocada > outro defeito > marca/modelo > capacidade > SEM > valor ---


def test_precedencia_peca_trocada_antes_de_outro_defeito() -> None:
    res = avaliar(tabela(linha()), usado(peca_trocada=True, camera_ok=False))
    assert motivo(res) is MotivoLoja.PECA_TROCADA


def test_precedencia_defeito_antes_de_modelo_fora_da_tabela() -> None:
    res = avaliar(tabela(linha()), usado(camera_ok=False), modelo=IPHONE_15)
    assert motivo(res) is MotivoLoja.OUTRO_DEFEITO


def test_precedencia_outra_marca_antes_de_capacidade() -> None:
    res = avaliar(tabela(linha()), usado(), modelo=GALAXY, cap=64)
    assert motivo(res) is MotivoLoja.OUTRA_MARCA


def test_precedencia_capacidade_antes_de_sem() -> None:
    res = avaliar(tabela(linha()), usado(traseira_danificada=True), cap=64)
    assert motivo(res) is MotivoLoja.CAPACIDADE_ABAIXO_DA_TABELA


def test_precedencia_sem_antes_de_valor_nao_positivo() -> None:
    tab = tabela(linha(sem_detalhes="100"))
    res = avaliar(tab, usado(tela_danificada=True, traseira_danificada=True))
    assert motivo(res) is MotivoLoja.SEM_VALOR_WHATSAPP


def test_condicao_valida_bateria() -> None:
    with pytest.raises(ValueError):
        usado(bateria_pct=101)
    with pytest.raises(ValueError):
        usado(bateria_pct=-1)


def test_linha_e_imutavel() -> None:
    with pytest.raises(AttributeError):
        linha().valor_sem_detalhes = R("1")  # type: ignore[misc]
    assert replace(linha(), limite_bateria_pct=90).limite_bateria_pct == 90
