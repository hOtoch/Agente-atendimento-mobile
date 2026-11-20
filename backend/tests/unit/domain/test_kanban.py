import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.kanban import (
    Ator,
    Etapa,
    EtapaMudou,
    FatosDoLead,
    MovimentoInvalido,
    atualizar_etapa,
    calcular_etapa,
    mover_manual,
    mover_manual_com_evento,
)

NENHUM = FatosDoLead()
APARELHO_E_ESTOQUE = FatosDoLead(aparelho_definido=True, estoque_consultado=True)
QUALIFICADO = FatosDoLead(aparelho_definido=True, estoque_consultado=True, qualificado=True)
HANDOFF = FatosDoLead(handoff_realizado=True)


def test_valores_estaveis_gravados_no_banco() -> None:
    assert [e.value for e in Etapa] == [
        "novo_contato",
        "interesse_identificado",
        "interesse_qualificado",
        "com_o_vendedor",
        "venda_fechada",
    ]


def test_ordem_crescente_e_nome_de_exibicao() -> None:
    assert [e.ordem for e in Etapa] == [0, 1, 2, 3, 4]
    assert Etapa.NOVO_CONTATO.nome_exibicao == "Novo contato"
    assert Etapa.INTERESSE_IDENTIFICADO.nome_exibicao == "Interesse identificado"
    assert Etapa.INTERESSE_QUALIFICADO.nome_exibicao == "Interesse qualificado"
    assert Etapa.COM_O_VENDEDOR.nome_exibicao == "Com o vendedor"
    assert Etapa.VENDA_FECHADA.nome_exibicao == "Venda fechada"


def test_primeira_mensagem_novo_contato() -> None:
    assert calcular_etapa(Etapa.NOVO_CONTATO, NENHUM) is Etapa.NOVO_CONTATO


def test_aparelho_e_estoque_vira_interesse_identificado() -> None:
    assert calcular_etapa(Etapa.NOVO_CONTATO, APARELHO_E_ESTOQUE) is Etapa.INTERESSE_IDENTIFICADO


@pytest.mark.parametrize(
    "fatos",
    [
        FatosDoLead(aparelho_definido=True),
        FatosDoLead(estoque_consultado=True),
    ],
)
def test_so_aparelho_ou_so_estoque_nao_basta(fatos: FatosDoLead) -> None:
    assert calcular_etapa(Etapa.NOVO_CONTATO, fatos) is Etapa.NOVO_CONTATO


def test_ficha_completa_vira_interesse_qualificado() -> None:
    assert calcular_etapa(Etapa.NOVO_CONTATO, QUALIFICADO) is Etapa.INTERESSE_QUALIFICADO


def test_qualificado_sem_aparelho_e_estoque_nao_conta() -> None:
    assert calcular_etapa(Etapa.NOVO_CONTATO, FatosDoLead(qualificado=True)) is Etapa.NOVO_CONTATO


def test_handoff_vira_com_o_vendedor() -> None:
    assert calcular_etapa(Etapa.NOVO_CONTATO, HANDOFF) is Etapa.COM_O_VENDEDOR


def test_handoff_apos_qualificacao() -> None:
    fatos = dataclasses.replace(QUALIFICADO, handoff_realizado=True)
    assert calcular_etapa(Etapa.INTERESSE_QUALIFICADO, fatos) is Etapa.COM_O_VENDEDOR


@pytest.mark.parametrize("atual", list(Etapa))
def test_nao_regride_sozinho(atual: Etapa) -> None:
    assert calcular_etapa(atual, NENHUM).ordem >= atual.ordem


def test_nao_regride_apos_handoff_mesmo_sem_fatos() -> None:
    assert calcular_etapa(Etapa.COM_O_VENDEDOR, APARELHO_E_ESTOQUE) is Etapa.COM_O_VENDEDOR


def test_venda_fechada_nos_fatos_e_ignorada() -> None:
    fatos = dataclasses.replace(QUALIFICADO, handoff_realizado=True, venda_fechada=True)
    assert calcular_etapa(Etapa.NOVO_CONTATO, fatos) is Etapa.COM_O_VENDEDOR
    assert calcular_etapa(Etapa.NOVO_CONTATO, FatosDoLead(venda_fechada=True)) is Etapa.NOVO_CONTATO


def test_venda_fechada_permanece_apos_ser_marcada() -> None:
    assert calcular_etapa(Etapa.VENDA_FECHADA, NENHUM) is Etapa.VENDA_FECHADA


def test_venda_fechada_por_ia_invalida() -> None:
    r = mover_manual(Etapa.COM_O_VENDEDOR, Etapa.VENDA_FECHADA, Ator.IA)
    assert isinstance(r, MovimentoInvalido)
    assert r.motivo


def test_venda_fechada_por_sistema_invalida() -> None:
    r = mover_manual(Etapa.COM_O_VENDEDOR, Etapa.VENDA_FECHADA, Ator.SISTEMA)
    assert isinstance(r, MovimentoInvalido)


def test_venda_fechada_por_vendedor_valida() -> None:
    assert mover_manual(Etapa.COM_O_VENDEDOR, Etapa.VENDA_FECHADA, Ator.VENDEDOR) is (
        Etapa.VENDA_FECHADA
    )


@pytest.mark.parametrize("destino", [e for e in Etapa if e is not Etapa.VENDA_FECHADA])
def test_sair_de_venda_fechada_invalido(destino: Etapa) -> None:
    r = mover_manual(Etapa.VENDA_FECHADA, destino, Ator.VENDEDOR)
    assert isinstance(r, MovimentoInvalido)


def test_vendedor_move_para_tras() -> None:
    assert mover_manual(Etapa.COM_O_VENDEDOR, Etapa.NOVO_CONTATO, Ator.VENDEDOR) is (
        Etapa.NOVO_CONTATO
    )


def test_vendedor_move_para_frente() -> None:
    assert mover_manual(Etapa.NOVO_CONTATO, Etapa.COM_O_VENDEDOR, Ator.VENDEDOR) is (
        Etapa.COM_O_VENDEDOR
    )


@pytest.mark.parametrize("destino", [e for e in Etapa if e is not Etapa.NOVO_CONTATO])
def test_ia_move_manual_invalido(destino: Etapa) -> None:
    assert isinstance(mover_manual(Etapa.NOVO_CONTATO, destino, Ator.IA), MovimentoInvalido)


@pytest.mark.parametrize("ator", list(Ator))
def test_mesmo_destino_invalido(ator: Ator) -> None:
    r = mover_manual(Etapa.COM_O_VENDEDOR, Etapa.COM_O_VENDEDOR, ator)
    assert isinstance(r, MovimentoInvalido)


def test_evento_gerado_quando_muda() -> None:
    nova, evento = atualizar_etapa(Etapa.NOVO_CONTATO, APARELHO_E_ESTOQUE)
    assert nova is Etapa.INTERESSE_IDENTIFICADO
    assert evento == EtapaMudou(
        de=Etapa.NOVO_CONTATO,
        para=Etapa.INTERESSE_IDENTIFICADO,
        ator=Ator.SISTEMA,
        motivo=evento.motivo if evento else "",
    )
    assert evento is not None
    assert evento.motivo


def test_evento_ausente_quando_nao_muda() -> None:
    nova, evento = atualizar_etapa(Etapa.NOVO_CONTATO, NENHUM)
    assert nova is Etapa.NOVO_CONTATO
    assert evento is None


def test_atualizar_etapa_aceita_ator_ia() -> None:
    _, evento = atualizar_etapa(Etapa.NOVO_CONTATO, QUALIFICADO, ator=Ator.IA)
    assert evento is not None
    assert evento.ator is Ator.IA
    assert evento.para is Etapa.INTERESSE_QUALIFICADO


def test_evento_manual_valido() -> None:
    r = mover_manual_com_evento(Etapa.COM_O_VENDEDOR, Etapa.NOVO_CONTATO, Ator.VENDEDOR)
    assert not isinstance(r, MovimentoInvalido)
    nova, evento = r
    assert nova is Etapa.NOVO_CONTATO
    assert evento.de is Etapa.COM_O_VENDEDOR
    assert evento.para is Etapa.NOVO_CONTATO
    assert evento.ator is Ator.VENDEDOR


def test_evento_manual_invalido_propaga_movimento_invalido() -> None:
    r = mover_manual_com_evento(Etapa.NOVO_CONTATO, Etapa.VENDA_FECHADA, Ator.IA)
    assert isinstance(r, MovimentoInvalido)


@given(
    sequencia=st.lists(
        st.builds(
            FatosDoLead,
            aparelho_definido=st.booleans(),
            estoque_consultado=st.booleans(),
            qualificado=st.booleans(),
            handoff_realizado=st.booleans(),
            venda_fechada=st.booleans(),
        ),
        max_size=30,
    )
)
def test_propriedade_cadeia_nunca_diminui_nem_chega_a_venda_fechada(
    sequencia: list[FatosDoLead],
) -> None:
    etapa = Etapa.NOVO_CONTATO
    for fatos in sequencia:
        proxima = calcular_etapa(etapa, fatos)
        assert proxima.ordem >= etapa.ordem
        assert proxima is not Etapa.VENDA_FECHADA
        etapa = proxima
