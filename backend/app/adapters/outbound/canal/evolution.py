"""Canal WhatsApp: `CanalPort` sobre o `WhatsAppGateway` (Evolution API)."""

from __future__ import annotations

import base64
from uuid import UUID

from app.application.canal import MensagemSaida, TipoMensagem
from app.application.midia import ArmazenamentoMidia
from app.application.whatsapp import RegistroEnviadas, WhatsAppGateway

_MIME_POR_EXTENSAO = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class EvolutionAdapter:
    """Implementa `CanalPort` (canal `whatsapp`).

    Midia que e nossa (`{base_midia}/midias/<nome>`) segue como base64, porque a Evolution
    (em Docker) nem sempre alcanca a URL local da API; qualquer outra URL vai como esta.
    """

    def __init__(
        self,
        gateway: WhatsAppGateway,
        registro: RegistroEnviadas,
        *,
        armazenamento: ArmazenamentoMidia | None = None,
        base_midia: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._registro = registro
        self._armazenamento = armazenamento
        self._prefixo_midia = f"{base_midia.rstrip('/')}/midias/" if base_midia else None

    async def enviar(self, msg: MensagemSaida) -> None:
        if msg.tipo is TipoMensagem.TEXTO:
            if not msg.texto:
                raise ValueError("mensagem de texto sem texto")
            id_whatsapp = await self._gateway.enviar_texto(msg.loja_id, msg.destinatario, msg.texto)
        elif msg.tipo is TipoMensagem.AUDIO:
            midia, _ = await self._midia(msg)
            id_whatsapp = await self._gateway.enviar_audio(msg.loja_id, msg.destinatario, midia)
        else:
            midia, tipo_mime = await self._midia(msg)
            id_whatsapp = await self._gateway.enviar_imagem(
                msg.loja_id, msg.destinatario, midia, legenda=msg.texto, tipo_mime=tipo_mime
            )
        if id_whatsapp:
            await self._registro.registrar(msg.loja_id, id_whatsapp)

    async def digitando(self, loja_id: UUID, destinatario: str, duracao_ms: int = 1500) -> None:
        """Indicador de 'digitando...' no WhatsApp do cliente."""
        await self._gateway.digitando(loja_id, destinatario, duracao_ms)

    async def _midia(self, msg: MensagemSaida) -> tuple[str, str]:
        """`(url_ou_base64, tipo_mime)`."""
        url = msg.midia_url
        if not url:
            raise ValueError(f"mensagem de {msg.tipo.value} sem midia_url")
        if self._armazenamento and self._prefixo_midia and url.startswith(self._prefixo_midia):
            conteudo = await self._armazenamento.ler(url[len(self._prefixo_midia) :])
            if conteudo is not None:
                return base64.b64encode(conteudo.dados).decode(), conteudo.tipo_mime
        extensao = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        return url, _MIME_POR_EXTENSAO.get(extensao, "image/jpeg")
