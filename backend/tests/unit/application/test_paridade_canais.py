"""Paridade WhatsApp (Evolution) x Instagram: a mesma conversa roteirizada, o mesmo atendimento.

Cada canal entra pelo SEU normalizador, passa por `ReceberMensagem` e pelo MESMO orquestrador
(`ProcessarConversa`, FakeLLM com o mesmo roteiro e ferramentas reais) e sai pelo SEU adaptador
de saida sobre transporte HTTP falso. O que o agente decide (ficha, etapa, textos) nao pode
depender do canal. A rota do Instagram nao existe: o teste monta a cadeia sem ela.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.adapters.inbound.evolution.normalizar import Ignorado as IgnoradoEvolution
from app.adapters.inbound.evolution.normalizar import normalizar as normalizar_evolution
from app.adapters.inbound.instagram.normalizar import Ignorado as IgnoradoInstagram
from app.adapters.inbound.instagram.normalizar import normalizar as normalizar_instagram
from app.adapters.outbound.canal.evolution import EvolutionAdapter
from app.adapters.outbound.canal.instagram import InstagramAdapter
from app.adapters.outbound.llm.fake import RespostaRoteirizada
from app.application.agente.estado import EstadoAtendimento
from app.application.canal import (
    Canal,
    CanalPort,
    MensagemEntrada,
    ReceberMensagem,
    TipoMensagem,
)
from app.application.midia import ReceberMidia
from app.application.whatsapp import (
    MidiaBaixada,
    ProcessarMensagemWhatsApp,
    nome_instancia,
)
from app.domain.kanban import Etapa

from .agente.apoio_processar import (
    COMPRA_HOJE_12X,
    INTERESSE_16,
    USADO_EXEMPLO,
    Cenario,
    chamada,
    criar_cenario,
    texto,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CLIENTE_WHATSAPP = "5511987654321"
CLIENTE_INSTAGRAM = "1234567890123456"

FALAS = [
    "oi, quero um iphone 16 128",
    "tenho um iphone 16 128 com a tela trincada, bateria 79",
    "compro hoje, 12x no mastercard",
    "e quanto fica?",
]


def _roteiro() -> list[Any]:
    return [
        RespostaRoteirizada(
            chamadas=[
                chamada("t1", "registrar_interesse", INTERESSE_16),
                chamada("t2", "consultar_estoque", INTERESSE_16),
            ]
        ),
        texto("Temos o iPhone 16 128GB. Você tem aparelho para dar na troca?"),
        RespostaRoteirizada(chamadas=[chamada("t3", "registrar_usado", USADO_EXEMPLO)]),
        texto("Anotado! Quando pretende comprar e como vai pagar?"),
        RespostaRoteirizada(chamadas=[chamada("t4", "registrar_compra", COMPRA_HOJE_12X)]),
        texto("Perfeito, já tenho tudo para montar sua proposta."),
        RespostaRoteirizada(chamadas=[chamada("t5", "calcular_proposta")]),
        texto("Aqui está a proposta para você."),
    ]


def _fixture(pasta: str, nome: str) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads((FIXTURES / pasta / nome).read_text(encoding="utf-8"))
    return dados


def _payload_evolution(loja_id: UUID, fala: str, n: int) -> dict[str, Any]:
    payload = copy.deepcopy(_fixture("evolution", "texto_conversation.json"))
    payload["instance"] = nome_instancia(loja_id)
    payload["data"]["key"]["id"] = f"3EB0PARIDADE{n:04d}"
    payload["data"]["message"] = {"conversation": fala}
    payload["data"]["messageTimestamp"] = 1763644500 + n
    return payload


def _payload_instagram(fala: str, n: int) -> dict[str, Any]:
    payload = copy.deepcopy(_fixture("instagram", "texto.json"))
    evento = payload["entry"][0]["messaging"][0]
    evento["message"]["mid"] = f"mid-paridade-{n}"
    evento["message"]["text"] = fala
    evento["timestamp"] = 1767225600000 + n * 1000
    return payload


class ConversasDoCanal:
    """`RepositorioConversas` sobre o `ConversasEmMemoria` do cenario (um lead por teste)."""

    def __init__(self, c: Cenario) -> None:
        self._c = c
        self._conversa_id: UUID | None = None
        self._vistos: set[tuple[Canal, str]] = set()

    async def obter_ou_criar(self, loja_id: UUID, canal: Canal, contato: str) -> tuple[UUID, UUID]:
        if self._conversa_id is None:
            self._conversa_id = self._c.conversas.criar_conversa(
                loja_id=loja_id, lead_id=self._c.lead_id, canal=canal, contato=contato
            )
        return self._c.lead_id, self._conversa_id

    async def registrar_entrada(self, conversa_id: UUID, msg: MensagemEntrada) -> bool:
        chave = (msg.canal, msg.id_externo)
        if chave in self._vistos:
            return False
        self._vistos.add(chave)
        self._c.conversas.adicionar_entrada(
            conversa_id, msg.texto, tipo=msg.tipo.value, midia_url=msg.midia_url
        )
        return True

    async def registrar_saida_vendedor(self, *args: Any, **kwargs: Any) -> bool:
        raise AssertionError("o roteiro nao tem mensagem do vendedor")

    async def definir_nome_se_vazio(self, *args: Any, **kwargs: Any) -> None:
        return None


class GatewayEvolutionFalso:
    def __init__(self) -> None:
        self.textos: list[tuple[str, str]] = []

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
        self.textos.append((numero, texto))
        return f"ENVIADA{len(self.textos)}"

    async def digitando(self, loja_id: UUID, numero: str, duracao_ms: int = 1500) -> None:
        return None

    async def baixar_midia(self, loja_id: UUID, id_mensagem: str) -> MidiaBaixada:
        raise AssertionError("o roteiro so tem texto")


class RegistroFalso:
    def __init__(self) -> None:
        self.ids: set[str] = set()

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None:
        self.ids.add(id_whatsapp)

    async def foi_enviada(self, loja_id: UUID, id_whatsapp: str) -> bool:
        return id_whatsapp in self.ids


class SemPausa:
    async def pausar_por_vendedor(self, loja_id: UUID, lead_id: UUID) -> None:
        raise AssertionError("o roteiro nao tem mensagem do vendedor")


@dataclass
class Resultado:
    etapa: Etapa
    estado: EstadoAtendimento
    textos: list[str]
    destinatarios: set[str]


async def _rodar_whatsapp() -> Resultado:
    gateway = GatewayEvolutionFalso()
    registro = RegistroFalso()
    adapter = EvolutionAdapter(gateway, registro)  # type: ignore[arg-type]
    c = await criar_cenario(_roteiro(), canais={Canal.WHATSAPP: adapter})
    repo = ConversasDoCanal(c)

    async def agendar(conversa_id: UUID) -> None:
        await c.caso(conversa_id)

    processar = ProcessarMensagemWhatsApp(
        receber=ReceberMensagem(repo, agendar),
        mensagens_do_celular=repo,
        nomes=repo,
        gateway=gateway,  # type: ignore[arg-type]
        receber_midia=ReceberMidia(None, 0),  # type: ignore[arg-type]
        url_midia=lambda nome: nome,
        registro=registro,
        pausar=SemPausa(),
        repo_conversas=repo,
        graca_eco_s=0.0,
    )
    for n, fala in enumerate(FALAS):
        evento = normalizar_evolution(_payload_evolution(c.loja_id, fala, n))
        assert not isinstance(evento, IgnoradoEvolution), evento
        await processar(evento)
    return Resultado(
        etapa=c.etapa(),
        estado=await c.atendimento.obter(c.loja_id, c.lead_id),
        textos=[t for _, t in gateway.textos],
        destinatarios={d for d, _ in gateway.textos},
    )


async def _rodar_instagram() -> Resultado:
    requisicoes: list[httpx.Request] = []

    def servidor(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"recipient_id": CLIENTE_INSTAGRAM, "message_id": "m"})

    cliente = httpx.AsyncClient(
        base_url="https://graph.instagram.com", transport=httpx.MockTransport(servidor)
    )
    adapter = InstagramAdapter(cliente, token_da_loja=lambda _loja: "tok-da-loja")
    canais: dict[Canal, CanalPort] = {Canal.INSTAGRAM: adapter}
    c = await criar_cenario(_roteiro(), canais=canais)
    repo = ConversasDoCanal(c)

    async def agendar(conversa_id: UUID) -> None:
        await c.caso(conversa_id)

    receber = ReceberMensagem(repo, agendar)
    for n, fala in enumerate(FALAS):
        resultados = normalizar_instagram(
            _payload_instagram(fala, n), loja_da_conta=lambda _conta: c.loja_id
        )
        assert len(resultados) == 1
        entrada = resultados[0]
        assert not isinstance(entrada, IgnoradoInstagram), entrada
        await receber(entrada)
    corpos = [json.loads(r.content) for r in requisicoes]
    return Resultado(
        etapa=c.etapa(),
        estado=await c.atendimento.obter(c.loja_id, c.lead_id),
        textos=[b["message"]["text"] for b in corpos],
        destinatarios={b["recipient"]["id"] for b in corpos},
    )


async def test_mesma_conversa_gera_o_mesmo_atendimento_nos_dois_canais() -> None:
    whatsapp = await _rodar_whatsapp()
    instagram = await _rodar_instagram()

    assert len(whatsapp.textos) == len(FALAS)
    assert instagram.textos == whatsapp.textos
    assert instagram.etapa is whatsapp.etapa is Etapa.INTERESSE_QUALIFICADO
    assert instagram.estado == whatsapp.estado
    assert instagram.estado.estoque_consultado
    assert instagram.estado.ficha.interesse.capacidade is not None


async def test_cada_canal_responde_para_o_contato_do_proprio_canal() -> None:
    whatsapp = await _rodar_whatsapp()
    instagram = await _rodar_instagram()

    assert whatsapp.destinatarios == {CLIENTE_WHATSAPP}
    assert instagram.destinatarios == {CLIENTE_INSTAGRAM}


def test_texto_do_instagram_vira_a_mesma_mensagem_de_entrada_do_agente() -> None:
    entrada = normalizar_instagram(
        _payload_instagram("oi", 0), loja_da_conta=lambda _conta: uuid4()
    )[0]
    assert isinstance(entrada, MensagemEntrada)
    assert (entrada.canal, entrada.tipo, entrada.texto, entrada.midia_url) == (
        Canal.INSTAGRAM,
        TipoMensagem.TEXTO,
        "oi",
        None,
    )
