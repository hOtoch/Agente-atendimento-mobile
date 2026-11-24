from __future__ import annotations

from evals.cenarios import CENARIOS, CONTROLES
from evals.roteiros import ROTEIROS_FAKE

IDS_ESPERADOS = {
    "preco_logo_de_cara", "preco_tres_vezes", "bateria_omitida_depois_80", "mente_tela_perfeita",
    "muda_de_aparelho", "usado_samsung", "sem_troca_pix", "quer_24x", "desconto_tres_vezes",
    "compra_em_20_dias", "so_oi", "pede_humano", "prompt_injection", "camera_quebrada",
    "exemplo_oficial", "fecha_acordo_pix", "seminovo_sem_bateria", "pergunta_parcelas_nao_fecha",
    "desconto_escada", "pede_brinde",
}  # fmt: skip


def test_catalogo_tem_os_20_cenarios() -> None:
    assert {c.id for c in CENARIOS} == IDS_ESPERADOS
    assert len(CENARIOS) == 20


def test_cenarios_bem_formados() -> None:
    for c in [*CENARIOS, *CONTROLES]:
        assert c.persona and c.objetivo and c.roteiro, c.id
        assert c.max_turnos >= len(c.roteiro), c.id


def test_ids_unicos() -> None:
    ids = [c.id for c in [*CENARIOS, *CONTROLES]]
    assert len(ids) == len(set(ids))


def test_pelo_menos_3_cenarios_roteirizados_e_um_controle_negativo() -> None:
    reais = [c for c in CENARIOS if c.id in ROTEIROS_FAKE]
    assert len(reais) >= 3
    assert CONTROLES and all(c.deve_reprovar and c.id in ROTEIROS_FAKE for c in CONTROLES)


def test_cenario_de_fechamento_cobra_o_acordo_antes_do_handoff() -> None:
    c = next(c for c in CENARIOS if c.id == "fecha_acordo_pix")
    assert c.expectativas.acordo_fechado is True
    assert c.expectativas.handoff is True


def test_controle_de_handoff_sem_acordo_deve_reprovar() -> None:
    c = next(c for c in CONTROLES if c.id == "controle_handoff_sem_acordo")
    assert c.deve_reprovar and c.expectativas.acordo_fechado is True
