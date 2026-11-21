"""Verificacao do webhook da Meta: desafio (GET) e assinatura `X-Hub-Signature-256` (POST)."""

from __future__ import annotations

import hashlib
import hmac

from app.adapters.inbound.instagram.webhook import assinatura_valida, responder_desafio

SEGREDO = "segredo-do-app"
CORPO = b'{"object":"instagram","entry":[]}'


def _assinar(corpo: bytes, segredo: str = SEGREDO) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


def test_assinatura_correta_e_aceita() -> None:
    assert assinatura_valida(CORPO, _assinar(CORPO), SEGREDO)


def test_assinatura_de_outro_segredo_e_recusada() -> None:
    assert not assinatura_valida(CORPO, _assinar(CORPO, "outro"), SEGREDO)


def test_corpo_adulterado_e_recusado() -> None:
    assert not assinatura_valida(CORPO + b" ", _assinar(CORPO), SEGREDO)


def test_cabecalho_ausente_ou_malformado_e_recusado() -> None:
    assert not assinatura_valida(CORPO, None, SEGREDO)
    assert not assinatura_valida(CORPO, "", SEGREDO)
    assert not assinatura_valida(CORPO, "sha1=abc", SEGREDO)
    assert not assinatura_valida(CORPO, "sha256=nao-e-hex", SEGREDO)


def test_segredo_vazio_nunca_autoriza() -> None:
    assert not assinatura_valida(CORPO, _assinar(CORPO, ""), "")


def test_desafio_devolve_o_challenge_quando_o_token_confere() -> None:
    assert responder_desafio("subscribe", "tok", "123456", token_esperado="tok") == "123456"


def test_desafio_recusa_modo_ou_token_errado() -> None:
    assert responder_desafio("unsubscribe", "tok", "1", token_esperado="tok") is None
    assert responder_desafio("subscribe", "errado", "1", token_esperado="tok") is None
    assert responder_desafio("subscribe", None, "1", token_esperado="tok") is None
    assert responder_desafio("subscribe", "tok", None, token_esperado="tok") is None


def test_desafio_com_token_esperado_vazio_nunca_autoriza() -> None:
    assert responder_desafio("subscribe", "", "1", token_esperado="") is None
