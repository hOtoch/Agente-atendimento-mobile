"""Webhook da Evolution com o app real e Postgres isolado (gateway/barramento falsos)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.barramento.painel import topico_painel
from app.adapters.outbound.canal.enviadas import RegistroEnviadasMemoria
from app.adapters.outbound.db.models import Evento, Lead, Mensagem
from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
from app.application.whatsapp import (
    ErroGateway,
    EstadoConexao,
    MidiaBaixada,
    QrWhatsApp,
    nome_instancia,
)
from app.infra.dependencias import (
    get_agendar,
    get_armazenamento_midia,
    get_barramento,
    get_registro_enviadas,
    get_session,
    get_whatsapp_gateway,
)
from app.infra.settings import Settings, get_settings
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "evolution"
TOKEN = "segredo-de-teste"


class GatewayFalso:
    def __init__(self) -> None:
        self.midia = MidiaBaixada(b"jpegbytes", "image/jpeg")
        self.instancias: list[UUID] = []
        self.estado = EstadoConexao.INEXISTENTE
        self.qr: str | None = "data:image/png;base64,QR=="
        self.falha = False
        self.enviadas: list[tuple[str, str, str]] = []

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
        self.enviadas.append(("texto", numero, texto))
        return f"SENT{len(self.enviadas)}"

    async def baixar_midia(self, loja_id: UUID, id_mensagem: str) -> MidiaBaixada:
        return self.midia

    async def criar_instancia(self, loja_id: UUID) -> None:
        if self.falha:
            raise ErroGateway("fora do ar", status=502)
        self.instancias.append(loja_id)
        self.estado = EstadoConexao.CONECTANDO

    async def obter_qr(self, loja_id: UUID) -> QrWhatsApp:
        return QrWhatsApp(qr_base64=self.qr, status=self.estado)

    async def status_conexao(self, loja_id: UUID) -> EstadoConexao:
        if self.falha:
            raise ErroGateway("fora do ar", status=502)
        return self.estado


class Ambiente:
    def __init__(
        self,
        client: httpx.AsyncClient,
        factory: async_sessionmaker[AsyncSession],
        gateway: GatewayFalso,
        registro: RegistroEnviadasMemoria,
        barramento: BarramentoEmMemoria,
        midia_dir: Path,
    ) -> None:
        self.client = client
        self.factory = factory
        self.gateway = gateway
        self.registro = registro
        self.barramento = barramento
        self.midia_dir = midia_dir
        self.agendadas: list[UUID] = []

    async def loja(self) -> UUID:
        return UUID(await criar_loja_no_banco("Loja Zap"))

    def payload(self, fixture: str, loja: UUID) -> dict[str, Any]:
        dados: dict[str, Any] = json.loads((FIXTURES / f"{fixture}.json").read_text("utf-8"))
        dados["instance"] = nome_instancia(loja)
        return dados

    async def webhook(
        self, payload: dict[str, Any], *, token: str | None = TOKEN, query: bool = False
    ) -> httpx.Response:
        url, headers = "/webhooks/evolution", {}
        if token is not None and query:
            url += f"?token={token}"
        elif token is not None:
            headers["X-Webhook-Token"] = token
        return await self.client.post(url, json=payload, headers=headers)

    async def contar(self, modelo: type) -> int:
        async with self.factory() as s:
            return (await s.execute(select(func.count()).select_from(modelo))).scalar_one()


@pytest.fixture
async def amb(db_url: str, tmp_path: Path) -> AsyncIterator[Ambiente]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    gateway, registro, barramento = GatewayFalso(), RegistroEnviadasMemoria(), BarramentoEmMemoria()
    settings = Settings(
        _env_file=None,
        evolution_webhook_token=TOKEN,
        whatsapp_eco_graca_s=0,
        api_publica_url="http://api.test",
    )

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        a = Ambiente(c, factory, gateway, registro, barramento, tmp_path)

        async def agendar(conversa_id: UUID) -> None:
            a.agendadas.append(conversa_id)

        app.dependency_overrides[get_session] = _sessao
        app.dependency_overrides[get_barramento] = lambda: barramento
        app.dependency_overrides[get_agendar] = lambda: agendar
        app.dependency_overrides[get_whatsapp_gateway] = lambda: gateway
        app.dependency_overrides[get_registro_enviadas] = lambda: registro
        app.dependency_overrides[get_armazenamento_midia] = lambda: ArmazenamentoMidiaDisco(
            tmp_path
        )
        app.dependency_overrides[get_settings] = lambda: settings
        yield a
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_sem_token_ou_com_token_errado_401(amb: Ambiente) -> None:
    loja = await amb.loja()
    payload = amb.payload("texto_conversation", loja)
    assert (await amb.webhook(payload, token=None)).status_code == 401
    assert (await amb.webhook(payload, token="errado")).status_code == 401
    assert (await amb.webhook(payload, token="errado", query=True)).status_code == 401
    assert await amb.contar(Mensagem) == 0


async def test_token_configurado_vazio_recusa_tudo(amb: Ambiente) -> None:
    loja = await amb.loja()
    vazio = Settings(_env_file=None, evolution_webhook_token="", whatsapp_eco_graca_s=0)
    app.dependency_overrides[get_settings] = lambda: vazio
    payload = amb.payload("texto_conversation", loja)
    assert (await amb.webhook(payload, token=None)).status_code == 401
    assert (await amb.webhook(payload, token="")).status_code == 401
    assert await amb.contar(Mensagem) == 0


async def test_token_no_cabecalho_ou_na_query_vale(amb: Ambiente) -> None:
    loja = await amb.loja()
    r1 = await amb.webhook(amb.payload("texto_conversation", loja))
    r2 = await amb.webhook(amb.payload("texto_extendido", loja), query=True)
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert await amb.contar(Mensagem) == 2


async def test_texto_cria_lead_nomeado_mensagem_e_agenda(amb: Ambiente) -> None:
    loja = await amb.loja()
    r = await amb.webhook(amb.payload("texto_conversation", loja))
    assert r.json() == {"resultado": "processada"}
    async with amb.factory() as s:
        lead = (await s.execute(select(Lead))).scalar_one()
        msg = (await s.execute(select(Mensagem))).scalar_one()
    assert (lead.canal, lead.telefone, lead.nome, lead.dono) == (
        "whatsapp",
        "5511987654321",
        "Maria Silva",
        "ia",
    )
    assert (msg.canal, msg.direcao, msg.autor, msg.tipo) == (
        "whatsapp",
        "entrada",
        "cliente",
        "texto",
    )
    assert msg.conteudo == "Oi, vocês têm iPhone 16?"
    assert msg.id_externo == f"{loja}:3EB0A1B2C3D4E5F60001"
    assert len(amb.agendadas) == 1


async def test_evento_duplicado_nao_duplica_a_mensagem(amb: Ambiente) -> None:
    loja = await amb.loja()
    payload = amb.payload("texto_conversation", loja)
    r1, r2 = await amb.webhook(payload), await amb.webhook(payload)
    assert r1.json() == {"resultado": "processada"}
    assert r2.json() == {"resultado": "duplicada"}
    assert await amb.contar(Mensagem) == 1
    assert await amb.contar(Lead) == 1
    assert len(amb.agendadas) == 1


async def test_envios_simultaneos_do_mesmo_evento_gravam_uma_vez(amb: Ambiente) -> None:
    loja = await amb.loja()
    payload = amb.payload("texto_conversation", loja)
    await asyncio.gather(*(amb.webhook(payload) for _ in range(4)))
    assert await amb.contar(Mensagem) == 1


async def test_imagem_e_baixada_e_a_url_aponta_para_a_nossa_api(amb: Ambiente) -> None:
    loja = await amb.loja()
    await amb.webhook(amb.payload("imagem_legenda", loja))
    async with amb.factory() as s:
        msg = (await s.execute(select(Mensagem))).scalar_one()
    assert msg.tipo == "imagem"
    assert msg.conteudo == "Meu aparelho atual"
    assert msg.midia_url is not None
    assert msg.midia_url.startswith("http://api.test/midias/")
    nome = msg.midia_url.rsplit("/", 1)[1]
    assert (amb.midia_dir / nome).read_bytes() == b"jpegbytes"
    # e a rota existente entrega o arquivo
    r = await amb.client.get(f"/midias/{nome}")
    assert (r.status_code, r.content) == (200, b"jpegbytes")


async def test_audio_vira_mensagem_de_audio_com_midia(amb: Ambiente) -> None:
    loja = await amb.loja()
    amb.gateway.midia = MidiaBaixada(b"oggbytes", "audio/ogg; codecs=opus")
    await amb.webhook(amb.payload("audio_ptt", loja))
    async with amb.factory() as s:
        msg = (await s.execute(select(Mensagem))).scalar_one()
    assert msg.tipo == "audio"
    assert msg.midia_url is not None
    assert msg.midia_url.endswith(".ogg")


async def test_documento_entra_como_texto(amb: Ambiente) -> None:
    loja = await amb.loja()
    await amb.webhook(amb.payload("documento", loja))
    async with amb.factory() as s:
        msg = (await s.execute(select(Mensagem))).scalar_one()
    assert msg.tipo == "texto"
    assert "comprovante.pdf" in (msg.conteudo or "")


@pytest.mark.parametrize("fixture", ["grupo", "status", "figurinha", "evento_conexao"])
async def test_ignorados_respondem_200_sem_gravar(amb: Ambiente, fixture: str) -> None:
    loja = await amb.loja()
    r = await amb.webhook(amb.payload(fixture, loja))
    assert r.status_code == 200
    assert r.json() == {"resultado": "ignorada"}
    assert await amb.contar(Mensagem) == 0
    assert await amb.contar(Lead) == 0


async def test_instancia_desconhecida_ou_loja_inexistente_e_ignorada(amb: Ambiente) -> None:
    r = await amb.webhook(amb.payload("instancia_desconhecida", UUID(int=5)) | {"instance": "x"})
    assert r.json() == {"resultado": "ignorada"}
    r = await amb.webhook(amb.payload("texto_conversation", UUID(int=5)))  # loja nao existe
    assert r.json() == {"resultado": "ignorada"}
    assert await amb.contar(Mensagem) == 0


async def test_from_me_grava_como_vendedor_e_pausa_a_ia(amb: Ambiente) -> None:
    loja = await amb.loja()
    barramento_eventos: list[dict[str, object]] = []

    async def escutar() -> None:
        async for evento in amb.barramento.assinar(topico_painel(loja)):
            barramento_eventos.append(evento)
            if len(barramento_eventos) == 2:
                return

    tarefa = asyncio.create_task(escutar())
    await asyncio.sleep(0.05)
    r = await amb.webhook(amb.payload("from_me_texto", loja))
    assert r.json() == {"resultado": "processada"}
    await asyncio.wait_for(tarefa, 3)

    async with amb.factory() as s:
        lead = (await s.execute(select(Lead))).scalar_one()
        msg = (await s.execute(select(Mensagem))).scalar_one()
        eventos = (
            (await s.execute(select(Evento).where(Evento.tipo == "dono_mudou"))).scalars().all()
        )
    assert lead.dono == "vendedor"
    assert (msg.direcao, msg.autor) == ("saida", "vendedor")
    assert msg.conteudo == "Oi Maria, aqui é o Carlos da loja. Posso ajudar?"
    assert len(eventos) == 1
    assert amb.agendadas == []
    assert {e["evento"] for e in barramento_eventos} == {"MensagemNova", "DonoMudou"}


async def test_from_me_duplicado_nao_repete_nada(amb: Ambiente) -> None:
    loja = await amb.loja()
    payload = amb.payload("from_me_texto", loja)
    await amb.webhook(payload)
    r = await amb.webhook(payload)
    assert r.json() == {"resultado": "duplicada"}
    assert await amb.contar(Mensagem) == 1
    async with amb.factory() as s:
        eventos = (
            (await s.execute(select(Evento).where(Evento.tipo == "dono_mudou"))).scalars().all()
        )
    assert len(eventos) == 1


async def test_eco_de_mensagem_enviada_pela_api_nao_pausa_a_ia(amb: Ambiente) -> None:
    loja = await amb.loja()
    await amb.webhook(amb.payload("texto_conversation", loja))  # cliente fala
    payload = amb.payload("from_me_texto", loja)
    await amb.registro.registrar(loja, payload["data"]["key"]["id"])  # a IA tinha enviado
    r = await amb.webhook(payload)
    assert r.json() == {"resultado": "eco"}
    async with amb.factory() as s:
        lead = (await s.execute(select(Lead))).scalar_one()
    assert lead.dono == "ia"
    assert await amb.contar(Mensagem) == 1  # so a do cliente


async def test_status_do_whatsapp_da_loja(amb: Ambiente) -> None:
    loja = await amb.loja()
    r = await amb.client.get(f"/lojas/{loja}/whatsapp/status")
    assert (r.status_code, r.json()) == (200, {"status": "inexistente"})
    amb.gateway.estado = EstadoConexao.CONECTADO
    assert (await amb.client.get(f"/lojas/{loja}/whatsapp/status")).json() == {
        "status": "conectado"
    }


async def test_status_de_loja_inexistente_404(amb: Ambiente) -> None:
    assert (await amb.client.get(f"/lojas/{UUID(int=9)}/whatsapp/status")).status_code == 404
    assert (await amb.client.post(f"/lojas/{UUID(int=9)}/whatsapp/conectar")).status_code == 404


async def test_conectar_cria_a_instancia_e_devolve_o_qr(amb: Ambiente) -> None:
    loja = await amb.loja()
    r = await amb.client.post(f"/lojas/{loja}/whatsapp/conectar")
    assert r.status_code == 200
    assert r.json() == {"status": "conectando", "qr_base64": "data:image/png;base64,QR=="}
    assert amb.gateway.instancias == [loja]


async def test_conectar_com_whatsapp_ja_conectado_nao_recria(amb: Ambiente) -> None:
    loja = await amb.loja()
    amb.gateway.estado = EstadoConexao.CONECTADO
    amb.gateway.qr = None
    r = await amb.client.post(f"/lojas/{loja}/whatsapp/conectar")
    assert r.json() == {"status": "conectado", "qr_base64": None}
    assert amb.gateway.instancias == []


async def test_evolution_fora_do_ar_vira_502(amb: Ambiente) -> None:
    loja = await amb.loja()
    amb.gateway.falha = True
    r = await amb.client.get(f"/lojas/{loja}/whatsapp/status")
    assert r.status_code == 502
    assert "erros" in r.json()


async def test_mensagem_do_vendedor_pelo_painel_sai_pelo_whatsapp_e_o_eco_e_ignorado(
    amb: Ambiente,
) -> None:
    loja = await amb.loja()
    await amb.webhook(amb.payload("texto_conversation", loja))  # cliente fala: lead criado
    async with amb.factory() as s:
        lead = (await s.execute(select(Lead))).scalar_one()
    r = await amb.client.put(
        f"/lojas/{loja}/config/vendedores",
        json={"vendedores": [{"nome": "Carla", "peso_percentual": 100}]},
    )
    vendedor = r.json()["vendedores"][0]["id"]
    r = await amb.client.post(
        f"/lojas/{loja}/leads/{lead.id}/assumir", json={"vendedor_id": vendedor}
    )
    assert r.status_code == 200

    r = await amb.client.post(
        f"/lojas/{loja}/leads/{lead.id}/mensagens", json={"texto": "Oi, Carla"}
    )
    assert r.status_code == 201
    assert r.json()["enviada"] is True
    assert amb.gateway.enviadas == [("texto", "5511987654321", "Oi, Carla")]

    # A Evolution devolve o eco da mensagem que acabamos de enviar: nao e o vendedor no celular.
    eco = amb.payload("from_me_texto", loja)
    eco["data"]["key"]["id"] = "SENT1"
    assert (await amb.webhook(eco)).json() == {"resultado": "eco"}
    assert await amb.contar(Mensagem) == 2  # cliente + vendedor (painel), sem duplicata
