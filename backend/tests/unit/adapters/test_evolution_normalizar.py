"""Normalizacao dos payloads do webhook da Evolution v2 (fixtures anonimizadas)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.adapters.inbound.evolution.normalizar import Ignorado, normalizar
from app.application.canal import TipoMensagem
from app.application.whatsapp import EventoMensagemWhatsApp

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "evolution"
LOJA = UUID("00000000-0000-4000-8000-00000000de30")


def _carregar(nome: str) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
    return dados


def _evento(nome: str) -> EventoMensagemWhatsApp:
    resultado = normalizar(_carregar(nome))
    assert isinstance(resultado, EventoMensagemWhatsApp), resultado
    return resultado


def test_texto_simples() -> None:
    e = _evento("texto_conversation")
    assert e.loja_id == LOJA
    assert e.id_whatsapp == "3EB0A1B2C3D4E5F60001"
    assert e.de_mim is False
    assert e.contato == "5511987654321"
    assert e.nome == "Maria Silva"
    assert e.tipo is TipoMensagem.TEXTO
    assert e.texto == "Oi, vocês têm iPhone 16?"
    assert e.baixar_midia is False
    assert e.recebida_em == datetime.fromtimestamp(1763644500, UTC)


def test_texto_estendido() -> None:
    e = _evento("texto_extendido")
    assert e.tipo is TipoMensagem.TEXTO
    assert e.texto == "Quanto sai o de 128GB? https://exemplo.com"


def test_imagem_com_legenda_pede_download() -> None:
    e = _evento("imagem_legenda")
    assert e.tipo is TipoMensagem.IMAGEM
    assert e.texto == "Meu aparelho atual"
    assert e.tipo_mime == "image/jpeg"
    assert e.baixar_midia is True


def test_imagem_sem_legenda_tem_texto_vazio() -> None:
    e = _evento("imagem_sem_legenda")
    assert e.tipo is TipoMensagem.IMAGEM
    assert e.texto is None


def test_audio_ptt_pede_download() -> None:
    e = _evento("audio_ptt")
    assert e.tipo is TipoMensagem.AUDIO
    assert e.texto is None
    assert e.tipo_mime == "audio/ogg; codecs=opus"
    assert e.baixar_midia is True


def test_documento_vira_texto_com_nome_e_legenda_sem_baixar() -> None:
    e = _evento("documento")
    assert e.tipo is TipoMensagem.TEXTO
    assert e.texto == "Segue o comprovante\n[documento recebido: comprovante.pdf]"
    assert e.baixar_midia is False


def test_documento_embrulhado_com_legenda() -> None:
    e = _evento("documento_com_legenda")
    assert e.texto == "Orçamento anterior\n[documento recebido: orcamento.pdf]"


def test_from_me_e_marcado() -> None:
    e = _evento("from_me_texto")
    assert e.de_mim is True
    assert e.texto == "Oi Maria, aqui é o Carlos da loja. Posso ajudar?"
    assert e.contato == "5511987654321"
    assert e.nome is None  # o pushName de uma mensagem minha e o da loja, nao o do contato


def test_lid_usa_o_numero_alternativo() -> None:
    e = _evento("lid_com_numero")
    assert e.contato == "5511987654321"


@pytest.mark.parametrize(
    ("fixture", "trecho"),
    [
        ("grupo", "grupo"),
        ("status", "status"),
        ("figurinha", "suportado"),
        ("reacao", "suportado"),
        ("evento_conexao", "evento"),
        ("instancia_desconhecida", "instancia"),
    ],
)
def test_ignorados(fixture: str, trecho: str) -> None:
    resultado = normalizar(_carregar(fixture))
    assert isinstance(resultado, Ignorado)
    assert trecho in resultado.motivo


@pytest.mark.parametrize("payload", [[], "texto", 3, {}, {"event": "messages.upsert"}])
def test_payload_malformado_e_ignorado_sem_estourar(payload: Any) -> None:
    assert isinstance(normalizar(payload), Ignorado)


def test_nome_do_evento_em_caixa_alta_tambem_vale() -> None:
    payload = _carregar("texto_conversation")
    payload["event"] = "MESSAGES_UPSERT"
    assert isinstance(normalizar(payload), EventoMensagemWhatsApp)


def test_texto_vazio_e_ignorado() -> None:
    payload = _carregar("texto_conversation")
    payload["data"]["message"] = {"conversation": "   "}
    assert isinstance(normalizar(payload), Ignorado)


def test_timestamp_em_formato_dicionario_e_texto() -> None:
    payload = _carregar("texto_conversation")
    payload["data"]["messageTimestamp"] = {"low": 1763644500, "high": 0}
    assert _normalizado(payload).recebida_em == datetime.fromtimestamp(1763644500, UTC)
    payload["data"]["messageTimestamp"] = "1763644500"
    assert _normalizado(payload).recebida_em == datetime.fromtimestamp(1763644500, UTC)


def _normalizado(payload: dict[str, Any]) -> EventoMensagemWhatsApp:
    r = normalizar(payload)
    assert isinstance(r, EventoMensagemWhatsApp)
    return r
