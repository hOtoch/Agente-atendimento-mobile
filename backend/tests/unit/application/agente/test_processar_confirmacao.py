"""Orquestrador + FakeLLM: ficha de confirmacao, simulacao de parcelas e escada de desconto."""

from __future__ import annotations

from typing import Any

from app.adapters.outbound.llm.fake import RespostaRoteirizada, Roteiro
from app.application.llm import MensagemLLM
from app.domain.kanban import Etapa
from app.domain.valores import Dinheiro

from .apoio_processar import (
    COMPRA_HOJE_12X,
    INTERESSE_16,
    Cenario,
    chamada,
    criar_cenario,
    texto,
)

SEM_TROCA = {"tem_troca": False}
COMPRA_SEM_PARCELAS = {**COMPRA_HOJE_12X, "parcelas": None}


def _chamadas(*itens: tuple[str, str, dict[str, Any] | None]) -> RespostaRoteirizada:
    return RespostaRoteirizada(chamadas=[chamada(i, n, e) for i, n, e in itens])


def _ate_perguntar_parcelas() -> list[Roteiro]:
    return [
        _chamadas(
            ("a1", "registrar_interesse", INTERESSE_16),
            ("a2", "consultar_estoque", INTERESSE_16),
            ("a3", "registrar_usado", SEM_TROCA),
            ("a4", "registrar_compra", COMPRA_SEM_PARCELAS),
        ),
        texto("Em quantas parcelas?"),
    ]


_PRIMEIRA = "quero o iphone 16 128, não tenho troca, crédito mastercard, compro hoje"


async def _relato_10x() -> Cenario:
    """O relato real: 'quanto fica em 10x?' fechava o acordo na hora."""
    c = await criar_cenario(
        [
            *_ate_perguntar_parcelas(),
            _chamadas(
                ("b1", "registrar_compra", {**COMPRA_SEM_PARCELAS, "parcelas": 10}),
                ("b2", "calcular_proposta", None),
            ),
            texto("Fechado! 🎉 Resumo do seu pedido. Um vendedor vai continuar o atendimento."),
        ]
    )
    await c.turno(_PRIMEIRA)
    await c.turno("quanto fica em 10x?")
    return c


async def test_quanto_fica_em_10x_mostra_a_ficha_e_nao_fecha() -> None:
    c = await _relato_10x()
    ficha = c.canal.textos[1]
    assert ficha.startswith("Confere seu pedido:")
    assert "10x de" in ficha
    assert "Fechado" not in ficha
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.acordo is None
    assert not estado.handoff_solicitado
    assert estado.confirmacao is not None and not estado.pedido_confirmado
    assert c.etapa() is Etapa.INTERESSE_QUALIFICADO
    assert c.painel_repo.leads[c.lead_id].dono == "ia"


async def test_modelo_que_tenta_fechar_na_mesma_rodada_da_ficha_e_barrado() -> None:
    c = await criar_cenario(
        [
            *_ate_perguntar_parcelas(),
            _chamadas(
                ("b1", "registrar_compra", {**COMPRA_SEM_PARCELAS, "parcelas": 10}),
                ("b2", "calcular_proposta", None),
                ("b3", "confirmar_pedido", None),
                ("b4", "fechar_acordo", None),
                ("b5", "chamar_vendedor", {"motivo": "acordo_fechado"}),
            ),
            texto("Fechado! 🎉 Um vendedor vai continuar o atendimento."),
        ]
    )
    await c.turno(_PRIMEIRA)
    await c.turno("quanto fica em 10x?")
    assert c.canal.textos[1].startswith("Confere seu pedido:")  # o texto do modelo cai
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.acordo is None and not estado.handoff_solicitado
    assert not estado.pedido_confirmado
    assert c.painel_repo.leads[c.lead_id].dono == "ia"


async def test_sim_na_rodada_seguinte_confirma_fecha_e_passa_ao_vendedor() -> None:
    c = await _relato_10x()
    c.llm._roteiro.extend(
        [
            _chamadas(
                ("c1", "confirmar_pedido", None),
                ("c2", "fechar_acordo", None),
                ("c3", "chamar_vendedor", {"motivo": "acordo_fechado"}),
            ),
            texto("Pronto!"),
            texto("Cliente fechou."),  # observacoes do resumo
        ]
    )
    await c.turno("sim, pode fechar")
    assert c.canal.textos[2].startswith("Fechado! 🎉")
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.pedido_confirmado and estado.acordo is not None
    assert estado.handoff_solicitado and estado.motivo_handoff == "acordo_fechado"
    assert c.etapa() is Etapa.COM_O_VENDEDOR
    assert c.painel_repo.leads[c.lead_id].dono == "vendedor"


async def test_mudar_as_parcelas_apos_a_ficha_gera_nova_ficha_e_o_sim_antigo_nao_vale() -> None:
    c = await _relato_10x()
    c.llm._roteiro.extend(
        [
            # o cliente muda para 12x: nova ficha (e o modelo tenta confirmar na hora: barrado)
            _chamadas(
                ("c1", "registrar_compra", {**COMPRA_SEM_PARCELAS, "parcelas": 12}),
                ("c2", "calcular_proposta", None),
                ("c3", "confirmar_pedido", None),
            ),
            texto("ok"),
            _chamadas(("d1", "confirmar_pedido", None)),
            texto("Confirmado."),
        ]
    )
    await c.turno("pode ser em 12x")
    assert "12x de" in c.canal.textos[2]
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.confirmacao is not None and not estado.pedido_confirmado
    await c.turno("sim")
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.pedido_confirmado


async def test_escada_de_desconto_50_100_e_depois_vendedor_com_negociacao() -> None:
    c = await criar_cenario(
        [
            *_ate_perguntar_parcelas(),
            _chamadas(
                ("b1", "registrar_compra", {**COMPRA_SEM_PARCELAS, "parcelas": 10}),
                ("b2", "calcular_proposta", None),
            ),
            texto("segue"),
            _chamadas(("c1", "liberar_desconto", {"pedido": "mais_desconto", "motivo": "pediu"})),
            texto("segue"),
            _chamadas(("d1", "liberar_desconto", {"pedido": "mais_desconto", "motivo": "mais"})),
            texto("segue"),
            _chamadas(("e1", "liberar_desconto", {"pedido": "mais_desconto", "motivo": "de novo"})),
            texto("Vou chamar um vendedor para continuar a negociação com você."),
            texto("Cliente quer mais desconto."),  # observacoes do resumo
        ]
    )
    await c.turno(_PRIMEIRA)
    await c.turno("quanto fica em 10x?")
    await c.turno("tem desconto?")
    assert "Desconto: R$ 50,00" in c.canal.textos[2]
    await c.turno("só isso? faz mais um pouco")
    assert "Desconto: R$ 100,00" in c.canal.textos[3]
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.desconto.liberado == Dinheiro.zero() + Dinheiro.de("100")
    await c.turno("ainda quero mais")
    assert c.canal.textos[4].startswith("Vou chamar um vendedor")
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.handoff_solicitado and estado.motivo_handoff == "negociacao"
    assert c.painel_repo.leads[c.lead_id].dono == "vendedor"
    resumo = await c.handoff.resumo_do_lead(c.loja_id, c.lead_id)
    assert resumo is not None
    assert "negociação" in resumo.motivo.lower()
    assert "R$ 100,00" in resumo.motivo and "de novo" in resumo.motivo


async def test_brinde_vai_ao_vendedor_com_negociacao() -> None:
    c = await criar_cenario(
        [
            *_ate_perguntar_parcelas(),
            _chamadas(
                ("b1", "registrar_compra", {**COMPRA_SEM_PARCELAS, "parcelas": 10}),
                ("b2", "calcular_proposta", None),
            ),
            texto("segue"),
            _chamadas(
                (
                    "c1",
                    "liberar_desconto",
                    {"pedido": "brinde_ou_beneficio", "motivo": "quer uma capinha"},
                )
            ),
            texto("Vou chamar um vendedor para ver esse brinde com você."),
            texto("Cliente quer brinde."),
        ]
    )
    await c.turno(_PRIMEIRA)
    await c.turno("quanto fica em 10x?")
    await c.turno("ganho uma capinha de brinde?")
    # a ficha antiga da rodada anterior nao e reenviada: so a fala do modelo
    assert c.canal.textos[2].startswith("Vou chamar um vendedor")
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.handoff_solicitado and estado.motivo_handoff == "negociacao"
    assert estado.desconto.liberado == Dinheiro.zero()


async def test_desconto_pedido_antes_da_proposta_nao_e_negociado_e_entra_na_primeira_ficha() -> (
    None
):
    c = await criar_cenario(
        [
            _chamadas(
                ("a1", "registrar_interesse", INTERESSE_16),
                ("a2", "consultar_estoque", INTERESSE_16),
                ("a3", "liberar_desconto", {"pedido": "mais_desconto", "motivo": "pediu"}),
            ),
            texto("Já vejo o desconto quando fecharmos a ficha. Você tem aparelho na troca?"),
            _chamadas(
                ("b1", "registrar_usado", SEM_TROCA),
                ("b2", "registrar_compra", {**COMPRA_HOJE_12X, "parcelas": 10}),
                ("b3", "calcular_proposta", None),
            ),
            texto("segue"),
        ]
    )
    await c.turno("quero o iphone 16 128, tem desconto?")
    assert "Confere" not in c.canal.textos[0]
    await c.turno("não tenho troca, crédito mastercard 10x, compro hoje")
    assert c.canal.textos[1].startswith("Confere seu pedido:")
    assert "Desconto: R$ 50,00" in c.canal.textos[1]
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert not estado.handoff_solicitado


async def test_resposta_descartada_derruba_a_ficha_que_o_cliente_nao_viu() -> None:
    caixa: dict[str, Cenario] = {}

    def chega_no_meio(_: list[MensagemLLM]) -> RespostaRoteirizada:
        caixa["c"].cliente_diz("sim")
        return texto("segue")

    c = await criar_cenario(
        [
            *_ate_perguntar_parcelas(),
            _chamadas(
                ("b1", "registrar_compra", {**COMPRA_SEM_PARCELAS, "parcelas": 10}),
                ("b2", "calcular_proposta", None),
            ),
            chega_no_meio,
        ]
    )
    caixa["c"] = c
    await c.turno(_PRIMEIRA)
    await c.turno("quanto fica em 10x?")  # o "sim" chega antes de a ficha sair: descarta
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.confirmacao is None and not estado.pedido_confirmado
    assert len(c.canal.textos) == 1  # so a pergunta das parcelas
