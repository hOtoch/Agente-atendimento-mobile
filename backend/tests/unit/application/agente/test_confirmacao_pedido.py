"""Ficha de confirmacao: calcular_proposta mostra, liberar_desconto negocia, confirmar_pedido
exige o "sim" na rodada seguinte e fechar_acordo so fecha depois disso."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.application.agente.acordo import ficha_confirmacao
from app.application.agente.estado import EstadoAtendimento
from app.domain.estoque import Condicao
from app.domain.valores import Dinheiro

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    INTERESSE_16,
    USADO_EXEMPLO,
    Ambiente,
    confirmar,
    criar_ambiente,
    item,
    na_rodada,
)

VAZIO = EstadoAtendimento()
SEM_USADO = {"tem_troca": False}
PIX = {**COMPRA_HOJE_12X, "tipo_pagamento": "pix", "parcelas": None, "bandeira": None}
CREDITO_10X = {**COMPRA_HOJE_12X, "parcelas": 10}


async def _ficha_pronta(
    amb: Ambiente, compra: dict[str, object] | None = None, usado: dict[str, object] | None = None
) -> EstadoAtendimento:
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", usado or USADO_EXEMPLO),
        ("registrar_compra", compra or COMPRA_HOJE_12X),
    )
    return estado


async def _com_ficha_mostrada(
    amb: Ambiente,
    compra: dict[str, object] | None = None,
    usado: dict[str, object] | None = None,
) -> Any:
    estado = await _ficha_pronta(amb, compra, usado)
    r = await amb.rodar("calcular_proposta", {}, estado)
    assert not r.erro, r.conteudo
    return r


# --- ficha_confirmacao (texto montado pelo codigo) -------------------------------------------


async def test_ficha_tem_aparelho_troca_valor_na_forma_escolhida_data_e_pergunta() -> None:
    itens = [item("IP15-128-AZUL", "iPhone 15", 128, "Azul", 4199, condicao=Condicao.SEMINOVO)]
    amb = await criar_ambiente(itens)
    interesse = {"modelo": "iPhone 15", "capacidade": "128GB", "cor": "Azul"}
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", interesse),
        ("consultar_estoque", interesse),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", CREDITO_10X),
    )
    r = await amb.rodar("calcular_proposta", {}, estado)
    msg = r.conteudo["mensagem_ao_cliente"]
    p = r.estado.ultima_proposta
    assert p is not None
    assert msg.startswith("Confere seu pedido:")
    assert "iPhone 15 seminovo de 128GB, cor azul" in msg
    assert f"Seu iPhone 16 128GB na troca: {p['troca']['valor']}" in msg
    assert f"10x de {p['forma_escolhida']['valor_parcela']} no cartão Mastercard" in msg
    assert f"(total {p['forma_escolhida']['total_pago']})" in msg
    assert "Data prevista da compra: 20/11/2026" in msg
    assert "pré-avaliação" in msg
    assert "Está tudo certo" in msg and "confirmar seu pedido" in msg
    assert msg.count("?") == 1
    # so a forma escolhida: nenhuma alternativa (Pix, outras parcelas) aparece
    for alt in p["alternativas"]:
        for chave in ("valor_a_vista", "valor_parcela"):
            if chave in alt:
                assert alt[chave] not in msg
    # nenhum valor inventado: todo "R$ x" da ficha existe na proposta
    for valor in re.findall(r"R\$ [\d.]+,\d{2}", msg):
        assert valor in json.dumps(p, ensure_ascii=False)


async def test_ficha_so_mostra_desconto_quando_ha() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    assert "Desconto" not in r.conteudo["mensagem_ao_cliente"]
    d = await amb.rodar("liberar_desconto", {"pedido": "mais_desconto", "motivo": "x"}, r.estado)
    msg = d.conteudo["mensagem_ao_cliente"]
    assert "Desconto: R$ 50,00" in msg
    assert "Consegui um desconto de R$ 50,00" in msg


async def test_ficha_sem_troca_e_troca_na_loja() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb, PIX, SEM_USADO)
    msg = r.conteudo["mensagem_ao_cliente"]
    assert "na troca" not in msg
    assert "à vista no Pix" in msg
    assert ficha_confirmacao(r.estado, r.estado.ultima_proposta) == msg
    r2 = await _com_ficha_mostrada(amb, PIX, {**USADO_EXEMPLO, "camera_ok": False})
    assert "será avaliado na loja" in r2.conteudo["mensagem_ao_cliente"]


# --- calcular_proposta ---------------------------------------------------------------------


async def test_calcular_proposta_grava_a_confirmacao_com_a_rodada_e_nao_manda_fechar() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    e = r.estado
    assert e.confirmacao is not None
    assert e.confirmacao["rodada"] == "rodada-1"
    assert e.confirmacao["proposta"] == e.ultima_proposta
    assert not e.pedido_confirmado
    passo = r.conteudo["proximo_passo"].lower()
    assert "aguarde" in passo and "liberar_desconto" in passo
    assert "fechar_acordo agora" not in passo
    extras = ("proximo_passo", "mensagem_ao_cliente", "mensagem")
    assert e.ultima_proposta == {k: v for k, v in r.conteudo.items() if k not in extras}


async def test_calcular_de_novo_sem_mudanca_mantem_a_rodada_da_confirmacao() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    r2 = await na_rodada(amb, "rodada-2").rodar("calcular_proposta", {}, r.estado)
    assert r2.estado.confirmacao == r.estado.confirmacao  # a rodada original continua


async def test_mudar_parcelas_depois_da_ficha_derruba_a_confirmacao_e_gera_nova_ficha() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    estado, _ = await amb.seq(r.estado, ("registrar_compra", CREDITO_10X))
    assert estado.confirmacao is None and not estado.pedido_confirmado
    nova = await na_rodada(amb, "rodada-2").rodar("calcular_proposta", {}, estado)
    assert "10x de" in nova.conteudo["mensagem_ao_cliente"]
    assert nova.estado.confirmacao["rodada"] == "rodada-2"


async def test_confirmacao_antiga_nao_vale_depois_de_mudar() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    estado = await confirmar(amb, r.estado)
    mudou, _ = await amb.seq(estado, ("registrar_compra", CREDITO_10X))
    assert not mudou.pedido_confirmado
    f = await na_rodada(amb, "r3", "sim").rodar("fechar_acordo", {}, mudou)
    assert f.erro


async def test_desconto_pedido_antes_vira_o_primeiro_degrau_na_primeira_ficha() -> None:
    amb = await criar_ambiente()
    estado = await _ficha_pronta(amb)
    # o cliente pediu desconto antes da proposta: a IA nao negocia, so anota
    r0 = await amb.rodar("liberar_desconto", {"pedido": "mais_desconto", "motivo": "x"}, VAZIO)
    assert not r0.erro and r0.estado.desconto_pedido_antes
    assert r0.estado.desconto.liberado == Dinheiro.zero()
    assert "mensagem_ao_cliente" not in r0.conteudo
    r = await amb.rodar("calcular_proposta", {}, replace(estado, desconto_pedido_antes=True))
    assert r.estado.desconto.liberado == Dinheiro(Decimal(50))
    assert "Consegui um desconto de R$ 50,00" in r.conteudo["mensagem_ao_cliente"]
    assert not r.estado.desconto_pedido_antes  # consumido


# --- liberar_desconto ----------------------------------------------------------------------


async def test_escada_50_100_e_depois_vendedor_com_negociacao() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    estado = r.estado
    totais = []
    for n in (1, 2):
        d = await na_rodada(amb, f"r{n + 1}").rodar(
            "liberar_desconto", {"pedido": "mais_desconto", "motivo": "pediu mais"}, estado
        )
        assert not d.erro
        estado = d.estado
        totais.append(estado.desconto.liberado)
        assert estado.confirmacao["rodada"] == f"r{n + 1}"
        assert "Confere seu pedido:" in d.conteudo["mensagem_ao_cliente"]
        assert not estado.handoff_solicitado
    assert totais == [Dinheiro(Decimal(50)), Dinheiro(Decimal(100))]
    d3 = await amb.rodar(
        "liberar_desconto", {"pedido": "mais_desconto", "motivo": "quer mais ainda"}, estado
    )
    e = d3.estado
    assert e.handoff_solicitado and e.motivo_handoff == "negociacao"
    assert e.desconto.liberado == Dinheiro(Decimal(100))
    assert e.negociacao is not None
    assert e.negociacao["motivo"] == "acima_do_teto"
    assert e.negociacao["texto"] == "quer mais ainda"
    assert e.negociacao["liberado"] == str(Dinheiro(Decimal(100)))
    assert "mensagem_ao_cliente" not in d3.conteudo
    assert "vendedor" in d3.conteudo["mensagem"].lower()


async def test_brinde_passa_ao_vendedor_sem_liberar_nada() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    d = await amb.rodar(
        "liberar_desconto", {"pedido": "brinde_ou_beneficio", "motivo": "quer capinha"}, r.estado
    )
    assert d.estado.handoff_solicitado and d.estado.motivo_handoff == "negociacao"
    assert d.estado.desconto.liberado == Dinheiro.zero()
    assert d.estado.negociacao["motivo"] == "brinde_ou_beneficio"


async def test_brinde_antes_da_proposta_tambem_vai_ao_vendedor() -> None:
    amb = await criar_ambiente()
    d = await amb.rodar(
        "liberar_desconto", {"pedido": "brinde_ou_beneficio", "motivo": "quer capinha"}, VAZIO
    )
    assert d.estado.handoff_solicitado and d.estado.motivo_handoff == "negociacao"
    assert not d.estado.desconto_pedido_antes


async def test_liberar_desconto_pedido_invalido_e_erro() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("liberar_desconto", {"pedido": "xis", "motivo": "x"}, VAZIO)
    assert r.erro


# --- confirmar_pedido ----------------------------------------------------------------------


async def test_confirmar_na_mesma_rodada_da_ficha_e_recusado() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    c = await amb.rodar("confirmar_pedido", {}, r.estado)  # mesma rodada-1
    assert c.erro and not c.estado.pedido_confirmado
    assert "ainda não confirmou" in c.conteudo["erro"]


async def test_confirmar_sem_ficha_mostrada_e_recusado() -> None:
    amb = await criar_ambiente()
    estado = await _ficha_pronta(amb)
    c = await na_rodada(amb, "r2", "sim").rodar("confirmar_pedido", {}, estado)
    assert c.erro and "calcular_proposta" in c.conteudo["erro"]


async def test_confirmar_na_rodada_seguinte_com_sim_funciona_e_e_idempotente() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    amb2 = na_rodada(amb, "r2", "sim, pode fechar")
    c = await amb2.rodar("confirmar_pedido", {}, r.estado)
    assert not c.erro and c.estado.pedido_confirmado
    c2 = await amb2.rodar("confirmar_pedido", {}, c.estado)
    assert not c2.erro and c2.estado == c.estado


async def test_confirmar_exige_fala_de_aceite() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    for fala in ("quanto fica em 12x?", "tem desconto?", "não", "pode ser em 12x"):
        c = await na_rodada(amb, "r2", fala).rodar("confirmar_pedido", {}, r.estado)
        assert c.erro and not c.estado.pedido_confirmado, fala
        assert "pergunte" in c.conteudo["erro"].lower()


async def test_confirmar_recusa_se_a_proposta_atual_difere_da_confirmada() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    adulterada = replace(r.estado, confirmacao={"rodada": "rodada-1", "proposta": {"outra": 1}})
    c = await na_rodada(amb, "r2", "sim").rodar("confirmar_pedido", {}, adulterada)
    assert c.erro and "calcular_proposta" in c.conteudo["erro"]


# --- fechar_acordo / chamar_vendedor -------------------------------------------------------


async def test_fechar_acordo_exige_pedido_confirmado() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    f = await amb.rodar("fechar_acordo", {}, r.estado)
    assert f.erro and f.estado.acordo is None
    assert "confirmar_pedido" in f.conteudo["erro"]
    ok = await amb.rodar("fechar_acordo", {}, await confirmar(amb, r.estado))
    assert not ok.erro and ok.estado.acordo is not None


async def test_chamar_vendedor_acordo_fechado_exige_acordo() -> None:
    amb = await criar_ambiente()
    r = await _com_ficha_mostrada(amb)
    v = await amb.rodar("chamar_vendedor", {"motivo": "acordo_fechado"}, r.estado)
    assert v.erro and not v.estado.handoff_solicitado
    outro = await amb.rodar("chamar_vendedor", {"motivo": "pediu uma pessoa"}, r.estado)
    assert not outro.erro and outro.estado.handoff_solicitado
    fechado = await amb.rodar("fechar_acordo", {}, await confirmar(amb, r.estado))
    v2 = await amb.rodar("chamar_vendedor", {"motivo": "acordo_fechado"}, fechado.estado)
    assert not v2.erro and v2.estado.handoff_solicitado


# --- estado --------------------------------------------------------------------------------


def test_estado_antigo_sem_as_chaves_novas_continua_lendo() -> None:
    antigo = EstadoAtendimento().para_dict()
    for chave in ("confirmacao", "pedido_confirmado", "desconto_pedido_antes", "negociacao"):
        antigo.pop(chave, None)
    e = EstadoAtendimento.de_dict(antigo)
    assert e.confirmacao is None and e.negociacao is None
    assert not e.pedido_confirmado and not e.desconto_pedido_antes


def test_estado_ida_e_volta_com_as_chaves_novas() -> None:
    e = EstadoAtendimento(
        confirmacao={"rodada": "r", "proposta": {"a": 1}},
        pedido_confirmado=True,
        desconto_pedido_antes=True,
        negociacao={"motivo": "acima_do_teto"},
    )
    assert EstadoAtendimento.de_dict(json.loads(json.dumps(e.para_dict()))) == e
