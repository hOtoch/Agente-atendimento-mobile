"""Cliente HTTP da Evolution API v2 (implementa `WhatsAppGateway`)."""

from __future__ import annotations

import base64
import binascii
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from app.application.whatsapp import (
    ErroGateway,
    EstadoConexao,
    MidiaBaixada,
    QrWhatsApp,
    nome_instancia,
)

_ESTADOS = {
    "open": EstadoConexao.CONECTADO,
    "connecting": EstadoConexao.CONECTANDO,
    "close": EstadoConexao.DESCONECTADO,
}
_EXTENSAO_IMAGEM = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def criar_cliente_http(url: str, api_key: str, *, timeout_s: float = 20.0) -> httpx.AsyncClient:
    """Cliente com a base e a chave da Evolution (`apikey` global)."""
    return httpx.AsyncClient(base_url=url, headers={"apikey": api_key}, timeout=timeout_s)


class EvolutionGateway:
    def __init__(self, client: httpx.AsyncClient, *, webhook_url: str, webhook_token: str) -> None:
        self._client = client
        self._webhook_url = webhook_url
        self._webhook_token = webhook_token

    # --- infraestrutura -----------------------------------------------------------------------

    async def _chamar(
        self,
        metodo: str,
        rota: str,
        corpo: dict[str, Any] | None = None,
        *,
        aceitar: tuple[int, ...] = (),
    ) -> tuple[int, Any]:
        try:
            resposta = await self._client.request(metodo, rota, json=corpo)
        except httpx.HTTPError as exc:
            raise ErroGateway(f"Evolution inacessivel: {exc!r}") from exc
        if resposta.status_code >= 400 and resposta.status_code not in aceitar:
            raise ErroGateway(
                f"Evolution respondeu {resposta.status_code} em {metodo} {rota}: "
                f"{resposta.text[:300]}",
                status=resposta.status_code,
            )
        try:
            dados: Any = resposta.json()
        except ValueError:
            dados = None
        return resposta.status_code, dados

    @staticmethod
    def _id_enviado(dados: Any) -> str | None:
        chave = dados.get("key") if isinstance(dados, dict) else None
        valor = chave.get("id") if isinstance(chave, dict) else None
        return str(valor) if valor else None

    def _webhook(self) -> dict[str, Any]:
        # O token vai no cabecalho e na query: a Evolution cai em um se o outro nao for honrado.
        separador = "&" if "?" in self._webhook_url else "?"
        return {
            "enabled": True,
            "url": f"{self._webhook_url}{separador}token={quote(self._webhook_token)}",
            "byEvents": False,
            "base64": False,
            "headers": {"X-Webhook-Token": self._webhook_token},
            "events": ["MESSAGES_UPSERT"],
        }

    # --- instancia ----------------------------------------------------------------------------

    async def criar_instancia(self, loja_id: UUID) -> None:
        nome = nome_instancia(loja_id)
        status, _ = await self._chamar(
            "POST",
            "/instance/create",
            {
                "instanceName": nome,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
                "webhook": self._webhook(),
            },
            aceitar=(403,),
        )
        if status == 403:  # nome em uso: instancia ja existe; so garante o webhook
            await self._chamar("POST", f"/webhook/set/{nome}", {"webhook": self._webhook()})

    async def status_conexao(self, loja_id: UUID) -> EstadoConexao:
        status, dados = await self._chamar(
            "GET", f"/instance/connectionState/{nome_instancia(loja_id)}", aceitar=(404,)
        )
        if status == 404:
            return EstadoConexao.INEXISTENTE
        instancia = dados.get("instance") if isinstance(dados, dict) else None
        estado = instancia.get("state") if isinstance(instancia, dict) else None
        return _ESTADOS.get(str(estado), EstadoConexao.DESCONECTADO)

    async def obter_qr(self, loja_id: UUID) -> QrWhatsApp:
        _, dados = await self._chamar("GET", f"/instance/connect/{nome_instancia(loja_id)}")
        qr = dados.get("base64") if isinstance(dados, dict) else None
        if isinstance(qr, str) and qr:
            return QrWhatsApp(qr_base64=qr, status=EstadoConexao.CONECTANDO)
        return QrWhatsApp(qr_base64=None, status=await self.status_conexao(loja_id))

    # --- envio --------------------------------------------------------------------------------

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
        _, dados = await self._chamar(
            "POST",
            f"/message/sendText/{nome_instancia(loja_id)}",
            {"number": numero, "text": texto},
        )
        return self._id_enviado(dados)

    async def enviar_audio(self, loja_id: UUID, numero: str, audio: str) -> str | None:
        _, dados = await self._chamar(
            "POST",
            f"/message/sendWhatsAppAudio/{nome_instancia(loja_id)}",
            {"number": numero, "audio": audio},
        )
        return self._id_enviado(dados)

    async def enviar_imagem(
        self,
        loja_id: UUID,
        numero: str,
        imagem: str,
        legenda: str | None = None,
        tipo_mime: str = "image/jpeg",
    ) -> str | None:
        extensao = _EXTENSAO_IMAGEM.get(tipo_mime, "jpg")
        _, dados = await self._chamar(
            "POST",
            f"/message/sendMedia/{nome_instancia(loja_id)}",
            {
                "number": numero,
                "mediatype": "image",
                "mimetype": tipo_mime,
                "caption": legenda or "",
                "media": imagem,
                "fileName": f"imagem.{extensao}",
            },
        )
        return self._id_enviado(dados)

    async def digitando(self, loja_id: UUID, numero: str, duracao_ms: int = 1500) -> None:
        await self._chamar(
            "POST",
            f"/chat/sendPresence/{nome_instancia(loja_id)}",
            {"number": numero, "presence": "composing", "delay": duracao_ms},
        )

    # --- midia recebida -----------------------------------------------------------------------

    async def baixar_midia(self, loja_id: UUID, id_mensagem: str) -> MidiaBaixada:
        _, dados = await self._chamar(
            "POST",
            f"/chat/getBase64FromMediaMessage/{nome_instancia(loja_id)}",
            {"message": {"key": {"id": id_mensagem}}, "convertToMp4": False},
        )
        conteudo = dados.get("base64") if isinstance(dados, dict) else None
        if not isinstance(conteudo, str) or not conteudo:
            raise ErroGateway(f"Evolution nao devolveu a midia da mensagem {id_mensagem}")
        if conteudo.startswith("data:") and "," in conteudo:
            conteudo = conteudo.split(",", 1)[1]
        try:
            bytes_ = base64.b64decode(conteudo, validate=False)
        except binascii.Error as exc:
            raise ErroGateway("midia da Evolution com base64 invalido") from exc
        mime = str(dados.get("mimetype") or "application/octet-stream")
        return MidiaBaixada(dados=bytes_, tipo_mime=mime)
