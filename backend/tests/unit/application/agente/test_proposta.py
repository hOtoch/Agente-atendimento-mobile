"""Proposta: exemplo oficial ponta a ponta e variacoes (troca na loja, Pix, sem troca)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from app.application.agente.estado import EstadoAtendimento, fatos_do_lead
from app.application.agente.ferramentas import FRASE_OBRIGATORIA
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria
from app.domain.ficha import pode_passar_preco
from app.domain.kanban import Etapa, calcular_etapa
from app.domain.pagamento import Credito, PixDinheiro, calcular_pagamento
from app.domain.valores import Bandeira, Dinheiro

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    INTERESSE_16,
    USADO_EXEMPLO,
    Ambiente,
    criar_ambiente,
)

VAZIO = EstadoAtendimento()


async def _ate_proposta(amb: Ambiente, usado: dict[str, Any], compra: dict[str, Any]) -> Any:
    _, resultados = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", usado),
        ("registrar_compra", compra),
        ("calcular_proposta", {}),
    )
    return resultados[-1]


async def test_exemplo_oficial_ponta_a_ponta_com_repositorio_em_memoria() -> None:
    amb = await criar_ambiente()
    repo = RepositorioAtendimentoEmMemoria()
    estado = await repo.obter(amb.loja_id, amb.lead_id)
    assert estado == VAZIO

    for nome, entrada in [
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", COMPRA_HOJE_12X),
        ("calcular_proposta", {}),
    ]:
        r = await amb.rodar(nome, entrada, estado)
        assert not r.erro, (nome, r.conteudo)
        estado = r.estado
        await repo.salvar(amb.loja_id, amb.lead_id, estado)
        proposta = r.conteudo

    assert await repo.obter(amb.loja_id, amb.lead_id) == estado
    assert estado.proposta_apresentada
    assert pode_passar_preco(estado.ficha)

    # valores esperados vem do dominio, nao de numeros fixos
    preco = Dinheiro(Decimal(4830))
    troca = Dinheiro(Decimal(3100 - 600 - 190))
    regras = (await amb.casos.obter_preco(amb.loja_id)).regras  # type: ignore[union-attr]
    taxas = await amb.casos.obter_taxas(amb.loja_id)
    esperado = calcular_pagamento(
        preco, Dinheiro.zero(), troca, Credito(12, Bandeira.MASTERCARD), regras, taxas
    )

    assert proposta["bloqueado"] is False
    assert proposta["preco_aparelho"] == str(preco)
    assert proposta["troca"]["valor"] == str(troca)
    assert proposta["troca"]["valor"] == "R$ 2.310,00"
    assert proposta["base_parcelamento"] == "R$ 2.520,00"
    escolhida = proposta["forma_escolhida"]
    assert escolhida["parcelas"] == 12
    assert escolhida["valor_parcela"] == str(esperado.valor_parcela)
    assert escolhida["total_pago"] == str(esperado.total_pago)
    assert escolhida["taxa"] == "10,54%"
    assert FRASE_OBRIGATORIA in json.dumps(proposta, ensure_ascii=False)
    assert proposta["frase_obrigatoria"] == FRASE_OBRIGATORIA
    assert proposta["desconto"] == {
        "negociado": "R$ 0,00",
        "oportunidade_unica": None,
        "total": "R$ 0,00",
        "observacao": proposta["desconto"]["observacao"],
    }
    # o proximo passo (fechar o acordo) vai so para o LLM; a proposta guardada e a mesma
    assert "fechar_acordo" in proposta["proximo_passo"]
    assert estado.ultima_proposta == {k: v for k, v in proposta.items() if k != "proximo_passo"}

    # alternativas: 2 ou 3, sem repetir a forma escolhida
    alternativas = proposta["alternativas"]
    assert 2 <= len(alternativas) <= 3
    assert all(a["rotulo"] != escolhida["rotulo"] for a in alternativas)
    pix = calcular_pagamento(preco, Dinheiro.zero(), troca, PixDinheiro(), regras, taxas)
    assert any(a.get("valor_a_vista") == str(pix.total_pago) for a in alternativas)

    # kanban: qualificado, derivado so de fatos
    fatos = fatos_do_lead(estado)
    assert fatos.qualificado and fatos.estoque_consultado and fatos.aparelho_definido
    assert calcular_etapa(Etapa.NOVO_CONTATO, fatos) is Etapa.INTERESSE_QUALIFICADO

    # um evento por execucao
    assert r.eventos[0]["nome"] == "calcular_proposta"


async def test_troca_na_loja_calcula_sem_troca_e_avisa() -> None:
    amb = await criar_ambiente()
    r = await _ate_proposta(amb, USADO_EXEMPLO | {"camera_ok": False}, COMPRA_HOJE_12X)
    assert r.conteudo["bloqueado"] is False
    t = r.conteudo["troca"]
    assert t["status"] == "avaliacao_na_loja"
    assert "loja" in t["observacao"].lower()
    assert "valor" not in t or t.get("valor") is None
    assert r.conteudo["base_parcelamento"] == "R$ 4.830,00"
    assert FRASE_OBRIGATORIA in json.dumps(r.conteudo, ensure_ascii=False)


async def test_traseira_SEM_vai_para_a_loja() -> None:
    amb = await criar_ambiente()
    r = await _ate_proposta(amb, USADO_EXEMPLO | {"traseira_danificada": True}, COMPRA_HOJE_12X)
    assert r.conteudo["troca"]["status"] == "avaliacao_na_loja"


async def test_sem_troca() -> None:
    amb = await criar_ambiente()
    sem_troca = {k: None for k in USADO_EXEMPLO} | {"tem_troca": False}
    r = await _ate_proposta(amb, sem_troca, COMPRA_HOJE_12X)
    assert r.conteudo["troca"]["status"] == "sem_troca"
    assert r.conteudo["base_parcelamento"] == "R$ 4.830,00"


async def test_pix_mostra_valor_a_vista() -> None:
    amb = await criar_ambiente()
    compra = {
        "data_prevista": COMPRA_HOJE_12X["data_prevista"],
        "tipo_pagamento": "pix",
        "parcelas": None,
        "bandeira": None,
        "entrada": None,
    }
    r = await _ate_proposta(amb, USADO_EXEMPLO, compra)
    escolhida = r.conteudo["forma_escolhida"]
    assert escolhida["valor_a_vista"] == "R$ 2.520,00"
    assert len(r.conteudo["alternativas"]) >= 2


async def test_entrada_mais_credito_desconta_a_entrada_da_base() -> None:
    amb = await criar_ambiente()
    compra = COMPRA_HOJE_12X | {
        "tipo_pagamento": "entrada_mais_credito",
        "parcelas": 10,
        "entrada": "500",
    }
    r = await _ate_proposta(amb, USADO_EXEMPLO, compra)
    assert r.conteudo["base_parcelamento"] == "R$ 2.020,00"
    assert r.conteudo["forma_escolhida"]["entrada"] == "R$ 500,00"


async def test_troca_que_cobre_o_aparelho_gera_aviso() -> None:
    from .apoio_ferramentas import item

    amb = await criar_ambiente(itens=[item("BARATO", "iPhone 16", 128, "Preto", 1000)])
    r = await _ate_proposta(amb, USADO_EXEMPLO, COMPRA_HOJE_12X)
    assert r.conteudo["base_parcelamento"] == "R$ 0,00"
    assert r.conteudo["aviso"]


async def test_item_que_acabou_depois_de_confirmado() -> None:
    from .apoio_ferramentas import item

    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", COMPRA_HOJE_12X),
    )
    amb2 = await criar_ambiente(
        itens=[item("IP16-128-PRETO", "iPhone 16", 128, "Preto", 4830, qtd=0)]
    )
    r = await amb2.rodar("calcular_proposta", {}, estado)
    assert r.erro
    assert not r.estado.proposta_apresentada
