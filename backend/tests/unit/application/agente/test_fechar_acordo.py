"""fechar_acordo: so com proposta apresentada, ficha completa e forma aceita; grava o acordo."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

from app.application.agente.estado import EstadoAtendimento
from app.application.config.entradas import EntradaPagamento
from app.application.config.modelos import PerfilLoja

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    HOJE,
    INTERESSE_16,
    USADO_EXEMPLO,
    Ambiente,
    criar_ambiente,
)

VAZIO = EstadoAtendimento()
PIX_HOJE = {**dict.fromkeys(COMPRA_HOJE_12X), "data_prevista": HOJE.isoformat()} | {
    "tipo_pagamento": "pix"
}
SEM_USADO = {"tem_troca": False}


async def _com_proposta(
    amb: Ambiente, compra: dict[str, object] | None = None, usado: dict[str, object] | None = None
) -> EstadoAtendimento:
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", usado or USADO_EXEMPLO),
        ("registrar_compra", compra or COMPRA_HOJE_12X),
        ("calcular_proposta", {}),
    )
    assert estado.proposta_apresentada
    return estado


async def _chave_pix(amb: Ambiente, *, com_chave: bool) -> None:
    atual = await amb.casos.obter_pagamento(amb.loja_id)
    chave = atual.chave_pix
    await amb.casos.atualizar_pagamento(
        amb.loja_id,
        EntradaPagamento(
            aceita_pix=atual.formas.pix,
            aceita_debito=atual.formas.debito,
            aceita_credito=atual.formas.credito,
            chave_pix_tipo=chave.tipo.value if chave and com_chave else None,
            chave_pix=chave.chave if chave and com_chave else None,
            chave_pix_favorecido=chave.favorecido if chave and com_chave else None,
        ),
    )


# --- recusas -------------------------------------------------------------------------------


async def test_sem_proposta_e_recusado() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("fechar_acordo", {}, VAZIO)
    assert r.erro
    assert r.estado == VAZIO
    assert "calcular_proposta" in r.conteudo["erro"]


async def test_com_ficha_incompleta_e_recusado_e_diz_o_que_falta() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    incompleto = replace(estado, ficha=estado.ficha.com(data_prevista_compra=None))
    r = await amb.rodar("fechar_acordo", {}, incompleto)
    assert r.erro
    assert r.estado.acordo is None
    assert "data prevista da compra" in json.dumps(r.conteudo, ensure_ascii=False)


async def test_proposta_apresentada_sem_ultima_proposta_e_recusada() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    r = await amb.rodar("fechar_acordo", {}, replace(estado, ultima_proposta=None))
    assert r.erro
    assert r.estado.acordo is None


async def test_forma_nao_aceita_pela_loja_e_recusada() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)  # credito 12x
    atual = await amb.casos.obter_pagamento(amb.loja_id)
    await amb.casos.atualizar_pagamento(
        amb.loja_id,
        EntradaPagamento(
            aceita_pix=True,
            aceita_debito=True,
            aceita_credito=False,
            chave_pix_tipo=atual.chave_pix.tipo.value if atual.chave_pix else None,
            chave_pix=atual.chave_pix.chave if atual.chave_pix else None,
            chave_pix_favorecido=atual.chave_pix.favorecido if atual.chave_pix else None,
        ),
    )
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert r.erro
    assert r.estado.acordo is None
    assert "crédito" in r.conteudo["erro"]
    assert r.conteudo["formas_aceitas"] == ["pix", "debito"]


async def test_proposta_velha_depois_de_mudar_a_ficha_e_recusada() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    # o cliente mudou de ideia para Pix, mas a proposta apresentada era a do cartao
    estado, _ = await amb.seq(estado, ("registrar_compra", PIX_HOJE))
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert r.erro
    assert r.estado.acordo is None
    assert "calcular_proposta" in r.conteudo["erro"]


# --- acordo gravado ------------------------------------------------------------------------


async def test_fecha_o_acordo_no_cartao_e_devolve_endereco_e_horarios() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert not r.erro, r.conteudo

    perfil = await amb.casos.obter_perfil(amb.loja_id)
    assert isinstance(perfil, PerfilLoja)
    assert r.conteudo["status"] == "ok"
    assert r.conteudo["endereco"] == perfil.endereco
    assert "seg: 09:00-18:00" in r.conteudo["horarios"]
    assert "sab: 09:00-14:00" in r.conteudo["horarios"]
    assert "pix" not in r.conteudo  # cartao: sem chave Pix
    assert r.conteudo["data_prevista"] == "20/11/2026"
    assert "acordo_fechado" in r.conteudo["mensagem"]  # motivo do chamar_vendedor
    assert "agradeça" in r.conteudo["mensagem"].lower()

    a = r.estado.acordo
    assert a is not None
    assert a["aparelho"]["sku"] == "IP16-128-PRETO"
    assert a["preco_aparelho"] == estado.ultima_proposta["preco_aparelho"]  # type: ignore[index]
    assert a["forma_escolhida"] == estado.ultima_proposta["forma_escolhida"]  # type: ignore[index]
    assert a["troca"]["status"] == "avaliada"
    assert a["troca"]["aparelho_usado"] == "iPhone 16 128GB"
    assert a["desconto"]["total"] == estado.ultima_proposta["desconto"]["total"]  # type: ignore[index]
    assert a["desconto_liberado"] == "R$ 0,00"
    assert a["pagamento"] == {
        "tipo": "credito",
        "parcelas": 12,
        "bandeira": "mastercard",
        "entrada": None,
    }
    assert a["data_prevista"] == date(2026, 11, 20).isoformat()
    assert a["informado"]["endereco"] == perfil.endereco
    assert a["informado"]["chave_pix"] is None
    assert a["fechado_em"]
    json.dumps(a)  # serializavel (vai para o banco)
    assert r.estado.ultima_proposta == estado.ultima_proposta  # nao mexe na proposta
    assert not r.estado.handoff_solicitado  # quem chama o vendedor e a IA, depois


async def test_acordo_leva_o_desconto_liberado() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    estado, _ = await amb.seq(estado, ("liberar_desconto", {"motivo": "pediu desconto"}))
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert not r.erro
    assert r.estado.acordo["desconto_liberado"] == "R$ 50,00"  # type: ignore[index]
    assert r.estado.acordo["desconto"]["negociado"] == "R$ 50,00"  # type: ignore[index]


async def test_pix_com_chave_devolve_chave_e_favorecido() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb, PIX_HOJE, SEM_USADO)
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert not r.erro, r.conteudo
    assert r.conteudo["pix"] == {
        "tipo": "email",
        "chave": "pix@lojademo.exemplo",
        "favorecido": "Loja Demo Celulares",
    }
    assert "Pix" in r.conteudo["mensagem"]
    assert r.estado.acordo["informado"]["chave_pix"] == r.conteudo["pix"]  # type: ignore[index]
    assert r.estado.acordo["pagamento"]["tipo"] == "pix"  # type: ignore[index]
    assert r.estado.acordo["troca"]["status"] == "sem_troca"  # type: ignore[index]


async def test_pix_sem_chave_manda_o_vendedor_informar_na_loja() -> None:
    amb = await criar_ambiente()
    await _chave_pix(amb, com_chave=False)
    estado = await _com_proposta(amb, PIX_HOJE, SEM_USADO)
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert not r.erro, r.conteudo
    assert "pix" not in r.conteudo
    assert "vendedor" in r.conteudo["instrucao_pix"].lower()
    assert "inventar" in r.conteudo["instrucao_pix"].lower()
    assert r.estado.acordo["informado"]["chave_pix"] is None  # type: ignore[index]


async def test_entrada_mais_cartao_devolve_a_chave_pix_para_a_entrada() -> None:
    amb = await criar_ambiente()
    compra = {
        **PIX_HOJE,
        "tipo_pagamento": "entrada_mais_credito",
        "parcelas": 10,
        "bandeira": "Visa",
        "entrada": "1000",
    }
    estado = await _com_proposta(amb, compra, SEM_USADO)
    r = await amb.rodar("fechar_acordo", {}, estado)
    assert not r.erro, r.conteudo
    assert r.conteudo["pix"]["chave"] == "pix@lojademo.exemplo"
    assert "entrada" in r.conteudo["mensagem"].lower()
    assert r.estado.acordo["pagamento"]["entrada"] == "R$ 1.000,00"  # type: ignore[index]


# --- idempotencia --------------------------------------------------------------------------


async def test_chamar_de_novo_nao_muda_nada() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    primeiro = await amb.rodar("fechar_acordo", {}, estado)
    segundo = await amb.rodar("fechar_acordo", {}, primeiro.estado)
    assert not segundo.erro
    assert segundo.estado.acordo == primeiro.estado.acordo  # mesmo fechado_em
    assert segundo.conteudo["endereco"] == primeiro.conteudo["endereco"]


async def test_chamar_de_novo_com_algo_diferente_atualiza() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    primeiro = await amb.rodar("fechar_acordo", {}, estado)
    refeito, _ = await amb.seq(
        primeiro.estado,
        ("registrar_compra", PIX_HOJE),
        ("calcular_proposta", {}),
    )
    assert refeito.acordo is None  # mudar a ficha derruba o acordo antigo
    segundo = await amb.rodar("fechar_acordo", {}, refeito)
    assert not segundo.erro, segundo.conteudo
    assert segundo.estado.acordo["pagamento"]["tipo"] == "pix"  # type: ignore[index]
    assert segundo.estado.acordo != primeiro.estado.acordo


async def test_mudar_a_ficha_sem_recalcular_derruba_o_acordo() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    fechado = await amb.rodar("fechar_acordo", {}, estado)
    assert fechado.estado.acordo is not None
    r = await amb.rodar("registrar_compra", PIX_HOJE, fechado.estado)
    assert r.estado.acordo is None


async def test_ferramentas_que_nao_mudam_nada_mantem_o_acordo() -> None:
    amb = await criar_ambiente()
    estado = await _com_proposta(amb)
    fechado = await amb.rodar("fechar_acordo", {}, estado)
    r = await amb.rodar("calcular_proposta", {}, fechado.estado)  # mesma proposta
    assert r.estado.acordo == fechado.estado.acordo
    v = await amb.rodar("chamar_vendedor", {"motivo": "acordo_fechado"}, fechado.estado)
    assert v.estado.acordo == fechado.estado.acordo
    assert v.estado.handoff_solicitado
