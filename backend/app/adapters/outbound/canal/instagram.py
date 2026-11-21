"""Canal Instagram: `CanalPort` sobre a Graph API (API de mensagens do Instagram).

Esqueleto sem conexao real: o cliente HTTP e o provedor de token entram por injecao, e os
testes usam `httpx.MockTransport`. Os passos para ligar de verdade estao em `docs/instagram.md`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx

from app.application.canal import MensagemSaida, TipoMensagem

VERSAO_GRAPH_PADRAO = "v21.0"
"""Conferir a versao vigente na documentacao da Meta antes de ir para producao."""
URL_GRAPH_INSTAGRAM = "https://graph.instagram.com"

TokenDaLoja = Callable[[UUID], str | None]
"""Token de acesso da conta profissional de uma loja (None se a loja nao conectou)."""


class ErroInstagram(Exception):
    def __init__(self, mensagem: str, *, status: int | None = None, codigo: int | None = None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        """`error.code` da Graph API (ex.: fora da janela de resposta)."""


class InstagramAdapter:
    """Implementa `CanalPort` (canal `instagram`).

    A midia vai por URL publica (a Meta baixa); legenda de imagem segue como texto separado,
    porque a API de mensagens do Instagram nao tem legenda em anexo.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        token_da_loja: TokenDaLoja,
        versao: str = VERSAO_GRAPH_PADRAO,
    ) -> None:
        self._client = client
        self._token_da_loja = token_da_loja
        self._versao = versao

    async def enviar(self, msg: MensagemSaida) -> None:
        if msg.tipo is TipoMensagem.TEXTO:
            if not msg.texto:
                raise ValueError("mensagem de texto sem texto")
            await self._post(msg, {"text": msg.texto})
            return
        if not msg.midia_url:
            raise ValueError(f"mensagem de {msg.tipo.value} sem midia_url")
        tipo_anexo = "audio" if msg.tipo is TipoMensagem.AUDIO else "image"
        await self._post(
            msg, {"attachment": {"type": tipo_anexo, "payload": {"url": msg.midia_url}}}
        )
        if msg.texto:
            await self._post(msg, {"text": msg.texto})

    async def _post(self, msg: MensagemSaida, mensagem: dict[str, Any]) -> None:
        token = self._token_da_loja(msg.loja_id)
        if not token:
            raise ErroInstagram(f"loja {msg.loja_id} sem token do Instagram")
        try:
            resposta = await self._client.post(
                f"/{self._versao}/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "recipient": {"id": msg.destinatario},
                    "message": mensagem,
                    "messaging_type": "RESPONSE",
                },
            )
        except httpx.HTTPError as exc:
            raise ErroInstagram(f"Graph API inacessivel: {exc!r}") from exc
        if resposta.status_code >= 400:
            raise _erro(resposta)


def _erro(resposta: httpx.Response) -> ErroInstagram:
    codigo: int | None = None
    detalhe = resposta.text[:300]
    try:
        erro = resposta.json().get("error")
    except (ValueError, AttributeError):
        erro = None
    if isinstance(erro, dict):
        detalhe = str(erro.get("message") or detalhe)
        valor = erro.get("code")
        codigo = valor if isinstance(valor, int) else None
    return ErroInstagram(
        f"Graph API respondeu {resposta.status_code}: {detalhe}",
        status=resposta.status_code,
        codigo=codigo,
    )
