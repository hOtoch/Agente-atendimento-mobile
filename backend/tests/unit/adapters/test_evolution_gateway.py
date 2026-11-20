"""Cliente HTTP da Evolution API v2 (respx: nenhum teste toca a rede)."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
import respx

from app.adapters.outbound.canal.evolution_api import EvolutionGateway
from app.application.whatsapp import (
    ErroGateway,
    EstadoConexao,
    WhatsAppGateway,
    nome_instancia,
)

LOJA = UUID("00000000-0000-4000-8000-00000000de30")
INSTANCIA = nome_instancia(LOJA)
BASE = "http://evolution.test"
WEBHOOK = "http://host.docker.internal:8000/webhooks/evolution"


@pytest.fixture
async def gateway() -> AsyncIterator[EvolutionGateway]:
    async with httpx.AsyncClient(base_url=BASE, headers={"apikey": "chave"}) as client:
        yield EvolutionGateway(client, webhook_url=WEBHOOK, webhook_token="segredo")


def _corpo(rota: respx.Route) -> dict[str, object]:
    resultado: dict[str, object] = json.loads(rota.calls.last.request.content)
    return resultado


def test_implementa_a_porta() -> None:
    def _aceita(g: WhatsAppGateway) -> None: ...

    _aceita(EvolutionGateway(httpx.AsyncClient(), webhook_url="", webhook_token=""))


@respx.mock
async def test_enviar_texto(gateway: EvolutionGateway) -> None:
    rota = respx.post(f"{BASE}/message/sendText/{INSTANCIA}").respond(
        201, json={"key": {"id": "BAE5ID", "fromMe": True}}
    )
    id_whatsapp = await gateway.enviar_texto(LOJA, "5511987654321", "Olá!")
    assert id_whatsapp == "BAE5ID"
    assert rota.calls.last.request.headers["apikey"] == "chave"
    assert _corpo(rota) == {"number": "5511987654321", "text": "Olá!"}


@respx.mock
async def test_enviar_texto_sem_id_na_resposta(gateway: EvolutionGateway) -> None:
    respx.post(f"{BASE}/message/sendText/{INSTANCIA}").respond(201, json={})
    assert await gateway.enviar_texto(LOJA, "5511987654321", "x") is None


@respx.mock
async def test_enviar_audio(gateway: EvolutionGateway) -> None:
    rota = respx.post(f"{BASE}/message/sendWhatsAppAudio/{INSTANCIA}").respond(
        201, json={"key": {"id": "AUD1"}}
    )
    assert await gateway.enviar_audio(LOJA, "5511987654321", "http://x/a.ogg") == "AUD1"
    assert _corpo(rota) == {"number": "5511987654321", "audio": "http://x/a.ogg"}


@respx.mock
async def test_enviar_imagem_com_legenda(gateway: EvolutionGateway) -> None:
    rota = respx.post(f"{BASE}/message/sendMedia/{INSTANCIA}").respond(
        201, json={"key": {"id": "IMG1"}}
    )
    id_whatsapp = await gateway.enviar_imagem(
        LOJA, "5511987654321", "AAAA", legenda="Olha", tipo_mime="image/png"
    )
    assert id_whatsapp == "IMG1"
    assert _corpo(rota) == {
        "number": "5511987654321",
        "mediatype": "image",
        "mimetype": "image/png",
        "caption": "Olha",
        "media": "AAAA",
        "fileName": "imagem.png",
    }


@respx.mock
async def test_digitando(gateway: EvolutionGateway) -> None:
    rota = respx.post(f"{BASE}/chat/sendPresence/{INSTANCIA}").respond(201, json={})
    await gateway.digitando(LOJA, "5511987654321", duracao_ms=2500)
    assert _corpo(rota) == {"number": "5511987654321", "presence": "composing", "delay": 2500}


@respx.mock
async def test_baixar_midia_decodifica_o_base64(gateway: EvolutionGateway) -> None:
    rota = respx.post(f"{BASE}/chat/getBase64FromMediaMessage/{INSTANCIA}").respond(
        201,
        json={
            "mediaType": "imageMessage",
            "mimetype": "image/jpeg",
            "base64": base64.b64encode(b"jpegbytes").decode(),
        },
    )
    midia = await gateway.baixar_midia(LOJA, "ID1")
    assert (midia.dados, midia.tipo_mime) == (b"jpegbytes", "image/jpeg")
    assert _corpo(rota) == {"message": {"key": {"id": "ID1"}}, "convertToMp4": False}


@respx.mock
async def test_baixar_midia_sem_base64_e_erro(gateway: EvolutionGateway) -> None:
    respx.post(f"{BASE}/chat/getBase64FromMediaMessage/{INSTANCIA}").respond(201, json={})
    with pytest.raises(ErroGateway):
        await gateway.baixar_midia(LOJA, "ID1")


@respx.mock
async def test_criar_instancia_configura_o_webhook(gateway: EvolutionGateway) -> None:
    rota = respx.post(f"{BASE}/instance/create").respond(201, json={"instance": {}})
    await gateway.criar_instancia(LOJA)
    corpo = _corpo(rota)
    assert corpo["instanceName"] == INSTANCIA
    assert corpo["integration"] == "WHATSAPP-BAILEYS"
    assert corpo["qrcode"] is True
    webhook = corpo["webhook"]
    assert isinstance(webhook, dict)
    assert webhook["url"] == f"{WEBHOOK}?token=segredo"
    assert webhook["headers"] == {"X-Webhook-Token": "segredo"}
    assert webhook["events"] == ["MESSAGES_UPSERT"]
    assert webhook["byEvents"] is False
    assert webhook["base64"] is False


@respx.mock
async def test_criar_instancia_que_ja_existe_so_reaplica_o_webhook(
    gateway: EvolutionGateway,
) -> None:
    respx.post(f"{BASE}/instance/create").respond(
        403,
        json={
            "status": 403,
            "response": {"message": [f'This name "{INSTANCIA}" is already in use.']},
        },
    )
    webhook = respx.post(f"{BASE}/webhook/set/{INSTANCIA}").respond(201, json={})
    await gateway.criar_instancia(LOJA)
    assert webhook.called
    assert _corpo(webhook)["webhook"]["url"] == f"{WEBHOOK}?token=segredo"  # type: ignore[index]


@respx.mock
async def test_criar_instancia_com_outro_erro_estoura(gateway: EvolutionGateway) -> None:
    respx.post(f"{BASE}/instance/create").respond(500, text="boom")
    with pytest.raises(ErroGateway) as erro:
        await gateway.criar_instancia(LOJA)
    assert erro.value.status == 500


@respx.mock
async def test_obter_qr_devolve_a_imagem(gateway: EvolutionGateway) -> None:
    respx.get(f"{BASE}/instance/connect/{INSTANCIA}").respond(
        200,
        json={
            "pairingCode": None,
            "code": "2@xx",
            "base64": "data:image/png;base64,QQ==",
            "count": 1,
        },
    )
    qr = await gateway.obter_qr(LOJA)
    assert qr.qr_base64 == "data:image/png;base64,QQ=="
    assert qr.status is EstadoConexao.CONECTANDO


@respx.mock
async def test_obter_qr_com_instancia_ja_conectada(gateway: EvolutionGateway) -> None:
    respx.get(f"{BASE}/instance/connect/{INSTANCIA}").respond(
        200, json={"instance": {"instanceName": INSTANCIA, "state": "open"}}
    )
    respx.get(f"{BASE}/instance/connectionState/{INSTANCIA}").respond(
        200, json={"instance": {"instanceName": INSTANCIA, "state": "open"}}
    )
    qr = await gateway.obter_qr(LOJA)
    assert qr.qr_base64 is None
    assert qr.status is EstadoConexao.CONECTADO


@pytest.mark.parametrize(
    ("estado", "esperado"),
    [
        ("open", EstadoConexao.CONECTADO),
        ("connecting", EstadoConexao.CONECTANDO),
        ("close", EstadoConexao.DESCONECTADO),
        ("qualquer", EstadoConexao.DESCONECTADO),
    ],
)
@respx.mock
async def test_status_conexao(
    gateway: EvolutionGateway, estado: str, esperado: EstadoConexao
) -> None:
    respx.get(f"{BASE}/instance/connectionState/{INSTANCIA}").respond(
        200, json={"instance": {"instanceName": INSTANCIA, "state": estado}}
    )
    assert await gateway.status_conexao(LOJA) is esperado


@respx.mock
async def test_status_de_instancia_inexistente(gateway: EvolutionGateway) -> None:
    respx.get(f"{BASE}/instance/connectionState/{INSTANCIA}").respond(
        404, json={"status": 404, "response": {"message": "not found"}}
    )
    assert await gateway.status_conexao(LOJA) is EstadoConexao.INEXISTENTE


@respx.mock
async def test_erro_http_vira_erro_do_gateway(gateway: EvolutionGateway) -> None:
    respx.post(f"{BASE}/message/sendText/{INSTANCIA}").respond(400, json={"error": "ruim"})
    with pytest.raises(ErroGateway) as erro:
        await gateway.enviar_texto(LOJA, "1", "x")
    assert erro.value.status == 400


@respx.mock
async def test_falha_de_rede_vira_erro_do_gateway(gateway: EvolutionGateway) -> None:
    respx.post(f"{BASE}/message/sendText/{INSTANCIA}").mock(
        side_effect=httpx.ConnectError("sem rede")
    )
    with pytest.raises(ErroGateway):
        await gateway.enviar_texto(LOJA, "1", "x")
