"""InstagramAdapter (CanalPort do Instagram) sobre um transporte HTTP falso."""

from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from app.adapters.outbound.canal.instagram import ErroInstagram, InstagramAdapter
from app.application.canal import Canal, CanalPort, MensagemSaida, TipoMensagem

LOJA = UUID("00000000-0000-4000-8000-00000000de30")
CLIENTE = "1234567890123456"


class Servidor:
    def __init__(self, status: int = 200, corpo: object | None = None) -> None:
        self.requisicoes: list[httpx.Request] = []
        self._status = status
        self._corpo = corpo if corpo is not None else {"recipient_id": CLIENTE, "message_id": "m1"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)
        return httpx.Response(self._status, json=self._corpo)


def _adapter(servidor: Servidor, token: str | None = "tok-da-loja") -> InstagramAdapter:
    cliente = httpx.AsyncClient(
        base_url="https://graph.instagram.com", transport=httpx.MockTransport(servidor)
    )
    return InstagramAdapter(cliente, token_da_loja=lambda _loja: token, versao="v99.0")


def _saida(tipo: TipoMensagem, texto: str | None, midia: str | None = None) -> MensagemSaida:
    return MensagemSaida(
        loja_id=LOJA,
        canal=Canal.INSTAGRAM,
        destinatario=CLIENTE,
        tipo=tipo,
        texto=texto,
        midia_url=midia,
    )


def test_implementa_canal_port() -> None:
    adapter: CanalPort = _adapter(Servidor())
    assert adapter is not None


async def test_envia_texto() -> None:
    servidor = Servidor()
    await _adapter(servidor).enviar(_saida(TipoMensagem.TEXTO, "Temos sim!"))

    (req,) = servidor.requisicoes
    assert req.method == "POST"
    assert req.url.path == "/v99.0/me/messages"
    assert req.headers["authorization"] == "Bearer tok-da-loja"
    assert json.loads(req.content) == {
        "recipient": {"id": CLIENTE},
        "message": {"text": "Temos sim!"},
        "messaging_type": "RESPONSE",
    }


async def test_envia_imagem_e_depois_a_legenda_como_texto() -> None:
    servidor = Servidor()
    await _adapter(servidor).enviar(
        _saida(TipoMensagem.IMAGEM, "Olha esse", "https://exemplo.com/a.jpg")
    )

    corpos = [json.loads(r.content) for r in servidor.requisicoes]
    assert corpos[0]["message"] == {
        "attachment": {"type": "image", "payload": {"url": "https://exemplo.com/a.jpg"}}
    }
    assert corpos[1]["message"] == {"text": "Olha esse"}


async def test_envia_audio() -> None:
    servidor = Servidor()
    await _adapter(servidor).enviar(_saida(TipoMensagem.AUDIO, None, "https://exemplo.com/a.mp3"))

    (req,) = servidor.requisicoes
    assert json.loads(req.content)["message"] == {
        "attachment": {"type": "audio", "payload": {"url": "https://exemplo.com/a.mp3"}}
    }


async def test_texto_sem_texto_e_midia_sem_url_sao_erros_de_uso() -> None:
    adapter = _adapter(Servidor())
    with pytest.raises(ValueError, match="sem texto"):
        await adapter.enviar(_saida(TipoMensagem.TEXTO, None))
    with pytest.raises(ValueError, match="sem midia_url"):
        await adapter.enviar(_saida(TipoMensagem.IMAGEM, None))


async def test_loja_sem_token_nao_chama_a_graph_api() -> None:
    servidor = Servidor()
    with pytest.raises(ErroInstagram, match="sem token"):
        await _adapter(servidor, token=None).enviar(_saida(TipoMensagem.TEXTO, "oi"))
    assert servidor.requisicoes == []


async def test_erro_da_graph_api_vira_erro_instagram_com_codigo() -> None:
    servidor = Servidor(
        400,
        {"error": {"message": "fora da janela", "type": "OAuthException", "code": 10}},
    )
    with pytest.raises(ErroInstagram) as exc:
        await _adapter(servidor).enviar(_saida(TipoMensagem.TEXTO, "oi"))
    assert exc.value.status == 400
    assert exc.value.codigo == 10
    assert "fora da janela" in str(exc.value)


async def test_falha_de_rede_vira_erro_instagram() -> None:
    def quebrar(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede", request=request)

    cliente = httpx.AsyncClient(
        base_url="https://graph.instagram.com", transport=httpx.MockTransport(quebrar)
    )
    adapter = InstagramAdapter(cliente, token_da_loja=lambda _loja: "t")
    with pytest.raises(ErroInstagram, match="inacessivel"):
        await adapter.enviar(_saida(TipoMensagem.TEXTO, "oi"))
