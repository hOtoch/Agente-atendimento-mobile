"""Normalizacao dos payloads do webhook `instagram` da Graph API (fixtures anonimizadas)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.adapters.inbound.instagram.normalizar import Ignorado, normalizar
from app.application.canal import Canal, MensagemEntrada, TipoMensagem

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "instagram"
LOJA = UUID("00000000-0000-4000-8000-00000000de30")
CONTA_DA_LOJA = "17841400000000001"
CLIENTE = "1234567890123456"
INSTANTE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _loja(conta: str) -> UUID | None:
    return LOJA if conta == CONTA_DA_LOJA else None


def _carregar(nome: str) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
    return dados


def _resultados(nome: str) -> list[MensagemEntrada | Ignorado]:
    return normalizar(_carregar(nome), loja_da_conta=_loja)


def _mensagem(nome: str) -> MensagemEntrada:
    resultados = _resultados(nome)
    assert len(resultados) == 1, resultados
    assert isinstance(resultados[0], MensagemEntrada), resultados[0]
    return resultados[0]


def _motivo(nome: str) -> str:
    resultados = _resultados(nome)
    assert len(resultados) == 1, resultados
    assert isinstance(resultados[0], Ignorado), resultados[0]
    return resultados[0].motivo


def test_dm_de_texto_vira_mensagem_de_entrada() -> None:
    m = _mensagem("texto")
    assert m.loja_id == LOJA
    assert m.canal is Canal.INSTAGRAM
    assert m.remetente == CLIENTE
    assert m.id_externo.startswith("aWdfZAG1faXRlbToxOklHTWVzc2FnZ")
    assert m.tipo is TipoMensagem.TEXTO
    assert m.texto == "Oi, vocês têm iPhone 16?"
    assert m.midia_url is None
    assert m.recebida_em == INSTANTE


def test_imagem_sem_texto() -> None:
    m = _mensagem("imagem")
    assert m.tipo is TipoMensagem.IMAGEM
    assert m.texto is None
    assert m.midia_url is not None
    assert m.midia_url.startswith("https://lookaside.fbsbx.com/")
    assert m.id_externo == "mid.imagem001"


def test_imagem_com_texto_guarda_a_legenda() -> None:
    m = _mensagem("imagem_com_texto")
    assert m.tipo is TipoMensagem.IMAGEM
    assert m.texto == "É este aqui"
    assert m.midia_url is not None


def test_audio() -> None:
    m = _mensagem("audio")
    assert m.tipo is TipoMensagem.AUDIO
    assert m.texto is None
    assert m.midia_url is not None


def test_resposta_a_story_e_tratada_como_texto() -> None:
    m = _mensagem("resposta_a_story")
    assert m.tipo is TipoMensagem.TEXTO
    assert m.texto == "Quanto está esse?"


def test_varias_mensagens_no_mesmo_envelope_viram_varias_entradas() -> None:
    resultados = _resultados("lote")
    assert [r.texto for r in resultados if isinstance(r, MensagemEntrada)] == [
        "Primeira",
        "Segunda",
    ]
    assert [r.id_externo for r in resultados if isinstance(r, MensagemEntrada)] == [
        "mid.lote001",
        "mid.lote002",
    ]


@pytest.mark.parametrize(
    ("fixture", "trecho"),
    [
        ("eco", "eco"),
        ("reacao", "nao e mensagem"),
        ("leitura", "nao e mensagem"),
        ("postback", "nao e mensagem"),
        ("apagada", "apagada"),
        ("nao_suportada", "nao suportada"),
        ("video", "anexo"),
        ("conta_desconhecida", "conta"),
        ("sem_mid", "mid"),
    ],
)
def test_o_que_nao_interessa_volta_como_ignorado(fixture: str, trecho: str) -> None:
    assert trecho in _motivo(fixture)


def test_objeto_que_nao_e_instagram_e_ignorado() -> None:
    resultados = _resultados("objeto_page")
    assert len(resultados) == 1
    assert isinstance(resultados[0], Ignorado)
    assert "page" in resultados[0].motivo


@pytest.mark.parametrize(
    "payload",
    [None, "texto", 42, [], {}, {"object": "instagram"}, {"object": "instagram", "entry": "x"}],
)
def test_payload_malformado_nunca_estoura(payload: object) -> None:
    resultados = normalizar(payload, loja_da_conta=_loja)
    assert all(isinstance(r, Ignorado) for r in resultados)
    assert resultados  # sempre diz por que nao fez nada


def test_entradas_malformadas_dentro_do_envelope_nao_estouram() -> None:
    payload = {
        "object": "instagram",
        "entry": [
            "lixo",
            {"id": CONTA_DA_LOJA, "messaging": "lixo"},
            {"id": CONTA_DA_LOJA, "messaging": [42, {"sender": {}, "message": {"mid": "m"}}]},
            {"id": CONTA_DA_LOJA, "messaging": [{"sender": {"id": CLIENTE}, "message": "x"}]},
        ],
    }
    resultados = normalizar(payload, loja_da_conta=_loja)
    assert resultados
    assert all(isinstance(r, Ignorado) for r in resultados)


def test_texto_em_branco_sem_anexo_e_ignorado() -> None:
    payload = _carregar("texto")
    payload["entry"][0]["messaging"][0]["message"]["text"] = "   "
    resultados = normalizar(payload, loja_da_conta=_loja)
    assert len(resultados) == 1
    assert isinstance(resultados[0], Ignorado)


def test_timestamp_invalido_cai_no_instante_atual() -> None:
    payload = _carregar("texto")
    payload["entry"][0]["messaging"][0]["timestamp"] = "ontem"
    resultados = normalizar(payload, loja_da_conta=_loja)
    assert isinstance(resultados[0], MensagemEntrada)
    assert abs((datetime.now(UTC) - resultados[0].recebida_em).total_seconds()) < 5
