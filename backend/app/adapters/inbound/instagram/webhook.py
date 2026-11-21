"""Verificacao do webhook da Meta (funcoes puras, sem framework).

- GET (inscricao): a Meta manda `hub.mode`, `hub.verify_token` e `hub.challenge`; devolvemos o
  challenge se o token bater.
- POST (entrega): a Meta assina o corpo cru com HMAC-SHA256 do app secret em `X-Hub-Signature-256`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PREFIXO = "sha256="


def assinatura_valida(corpo: bytes, cabecalho: str | None, app_secret: str) -> bool:
    """Compara em tempo constante. Segredo vazio nunca autoriza."""
    if not app_secret or not cabecalho or not cabecalho.startswith(_PREFIXO):
        return False
    recebida = cabecalho[len(_PREFIXO) :]
    esperada = hmac.new(app_secret.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(recebida.lower().encode(), esperada.encode())


def responder_desafio(
    modo: str | None, token: str | None, challenge: str | None, *, token_esperado: str
) -> str | None:
    """O challenge a devolver (texto puro, 200) ou None (responder 403)."""
    if not token_esperado or modo != "subscribe" or token is None or challenge is None:
        return None
    if not secrets.compare_digest(token.encode(), token_esperado.encode()):
        return None
    return challenge
