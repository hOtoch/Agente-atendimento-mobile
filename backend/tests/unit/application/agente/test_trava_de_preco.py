"""A trava: sem ficha completa, calcular_proposta nunca devolve valor."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.application.agente.estado import EstadoAtendimento
from app.domain.ficha import Ficha, pendencias

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    HOJE,
    INTERESSE_16,
    USADO_EXEMPLO,
    criar_ambiente,
    sem_valores,
)
from .test_conversao import fichas_completas

VAZIO = EstadoAtendimento()


async def test_ficha_vazia_bloqueia_com_pendencias_e_sem_numeros() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("calcular_proposta", {}, VAZIO)
    assert not r.erro
    assert r.conteudo["bloqueado"] is True
    assert r.conteudo["pendencias"]
    assert isinstance(r.conteudo["proxima_pergunta"], str) and r.conteudo["proxima_pergunta"]
    assert set(r.conteudo) >= {"bloqueado", "pendencias", "proxima_pergunta"}
    sem_valores(r.conteudo)
    assert not r.estado.proposta_apresentada
    assert r.estado.ultima_proposta is None


async def test_bloqueado_a_cada_etapa_ate_a_ficha_completar() -> None:
    amb = await criar_ambiente()
    passos = [
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
    ]
    estado = VAZIO
    for nome, entrada in passos:
        estado = (await amb.rodar(nome, entrada, estado)).estado
        r = await amb.rodar("calcular_proposta", {}, estado)
        assert r.conteudo["bloqueado"] is True
        sem_valores(r.conteudo)
        assert not r.estado.proposta_apresentada
    estado = (await amb.rodar("registrar_compra", COMPRA_HOJE_12X, estado)).estado
    r = await amb.rodar("calcular_proposta", {}, estado)
    assert r.conteudo["bloqueado"] is False


async def test_pendencias_em_ptbr_e_proxima_pergunta_segue_a_ordem() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("calcular_proposta", {}, VAZIO)
    assert "aparelho" in r.conteudo["pendencias"][0].lower()
    assert "Pendencia" not in json.dumps(r.conteudo)
    estado = (await amb.rodar("registrar_interesse", INTERESSE_16, VAZIO)).estado
    r2 = await amb.rodar("calcular_proposta", {}, estado)
    assert len(r2.conteudo["pendencias"]) < len(r.conteudo["pendencias"])
    assert r2.conteudo["proxima_pergunta"] != r.conteudo["proxima_pergunta"]


async def test_trocar_o_aparelho_depois_da_proposta_volta_a_bloquear() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", COMPRA_HOJE_12X),
        ("calcular_proposta", {}),
        ("registrar_interesse", {"modelo": "iPhone 15", "capacidade": "128GB", "cor": None}),
    )
    r = await amb.rodar("calcular_proposta", {}, estado)
    assert r.conteudo["bloqueado"] is True
    sem_valores(r.conteudo)
    d = await amb.rodar("liberar_desconto", {"motivo": "x"}, estado)
    assert d.conteudo["bloqueado"] is True
    assert d.estado.desconto.liberado == estado.desconto.liberado


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.data())
def test_qualquer_ficha_incompleta_bloqueia_sem_numeros(data: st.DataObject) -> None:
    ficha: Ficha = data.draw(fichas_completas())
    apagar = data.draw(
        st.lists(
            st.sampled_from(
                ["modelo", "capacidade", "sku", "troca", "data", "tipo", "parcelas", "bandeira"]
            ),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    mudancas = {
        "modelo": lambda f: f.com_interesse(modelo=None),
        "capacidade": lambda f: f.com_interesse(capacidade=None),
        "sku": lambda f: f.com_interesse(sku_estoque_confirmado=None),
        "troca": lambda f: f.com(tem_troca=None),
        "data": lambda f: f.com(data_prevista_compra=None),
        "tipo": lambda f: f.com_pagamento(tipo=None),
        "parcelas": lambda f: f.com_pagamento(parcelas=None),
        "bandeira": lambda f: f.com_pagamento(bandeira=None),
    }
    for chave in apagar:
        ficha = mudancas[chave](ficha)
    estado = EstadoAtendimento(ficha=ficha)

    async def rodar():  # type: ignore[no-untyped-def]
        amb = await criar_ambiente()
        return await amb.rodar("calcular_proposta", {}, estado)

    r = asyncio.run(rodar())
    if pendencias(ficha):
        assert r.conteudo["bloqueado"] is True
        sem_valores(r.conteudo)


async def test_oportunidade_unica_aparece_separada_do_desconto_negociado() -> None:
    amb = await criar_ambiente()
    longe = (HOJE + timedelta(days=30)).isoformat()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", COMPRA_HOJE_12X | {"data_prevista": longe}),
    )
    r = await amb.rodar("calcular_proposta", {}, estado)
    d = r.conteudo["desconto"]
    assert d["negociado"] == "R$ 0,00"
    assert d["oportunidade_unica"] == "R$ 100,00"
    assert d["total"] == "R$ 100,00"
    assert "por fora" in json.dumps(r.conteudo, ensure_ascii=False).lower()
    # depois de um degrau, os dois aparecem separados e somam
    r2 = await amb.rodar("liberar_desconto", {"motivo": "pediu"}, r.estado)
    d2 = r2.conteudo["proposta"]["desconto"]
    assert d2["negociado"] == "R$ 50,00"
    assert d2["oportunidade_unica"] == "R$ 100,00"
    assert d2["total"] == "R$ 150,00"


async def test_data_proxima_nao_tem_oportunidade_unica() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", COMPRA_HOJE_12X | {"data_prevista": date(2026, 11, 25).isoformat()}),
    )
    r = await amb.rodar("calcular_proposta", {}, estado)
    assert r.conteudo["desconto"]["oportunidade_unica"] is None
