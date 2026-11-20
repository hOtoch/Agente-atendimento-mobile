"""Canal webchat: a saida vai para o navegador via barramento (SSE na ponta)."""

from datetime import UTC, datetime
from uuid import UUID

from app.application.canal import BarramentoMensagens, MensagemSaida


def topico_webchat(loja_id: UUID, sessao: str) -> str:
    return f"webchat:{loja_id}:{sessao}"


class WebChatAdapter:
    """Implementa `CanalPort`."""

    def __init__(self, barramento: BarramentoMensagens) -> None:
        self._barramento = barramento

    async def enviar(self, msg: MensagemSaida) -> None:
        await self._barramento.publicar(
            topico_webchat(msg.loja_id, msg.destinatario),
            {
                "tipo": msg.tipo.value,
                "texto": msg.texto,
                "midia_url": msg.midia_url,
                "enviada_em": datetime.now(UTC).isoformat(),
            },
        )
