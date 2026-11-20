"""Caso de uso do webhook do WhatsApp (porta de entrada da Evolution), com fakes em memoria."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.canal import Canal, MensagemEntrada, ReceberMensagem, TipoMensagem
from app.application.midia import ConteudoMidia, ReceberMidia
from app.application.whatsapp import (
    ErroGateway,
    EventoMensagemWhatsApp,
    MidiaBaixada,
    ProcessarMensagemWhatsApp,
    ResultadoWebhook,
    id_externo_whatsapp,
    loja_da_instancia,
    nome_instancia,
)

LOJA = UUID("00000000-0000-4000-8000-00000000de30")
EM = datetime(2026, 11, 20, 13, 0, tzinfo=UTC)


def test_nome_da_instancia_e_deterministico_e_reversivel() -> None:
    assert nome_instancia(LOJA) == f"loja-{LOJA}"
    assert loja_da_instancia(nome_instancia(LOJA)) == LOJA


@pytest.mark.parametrize(
    "nome",
    ["", "loja-", "loja-123", "outra-instancia", f"x-{LOJA}", f"loja-{str(LOJA).upper()}"],
)
def test_instancia_invalida_nao_vira_loja(nome: str) -> None:
    assert loja_da_instancia(nome) is None


def test_id_externo_e_escopado_pela_loja() -> None:
    assert id_externo_whatsapp(LOJA, "ABC") == f"{LOJA}:ABC"


class RepoMemoria:
    """`RepositorioConversas` + `RepositorioMensagensDoCelular` + `NomesDeContatos`."""

    def __init__(self) -> None:
        self.leads: dict[tuple[UUID, Canal, str], tuple[UUID, UUID]] = {}
        self.entradas: dict[tuple[Canal, str], MensagemEntrada] = {}
        self.do_celular: dict[tuple[Canal, str], tuple[UUID, str | None]] = {}
        self.nomes: dict[str, str] = {}

    async def obter_ou_criar(self, loja_id: UUID, canal: Canal, contato: str) -> tuple[UUID, UUID]:
        chave = (loja_id, canal, contato)
        if chave not in self.leads:
            self.leads[chave] = (uuid4(), uuid4())
        return self.leads[chave]

    async def registrar_entrada(self, conversa_id: UUID, msg: MensagemEntrada) -> bool:
        chave = (msg.canal, msg.id_externo)
        if chave in self.entradas:
            return False
        self.entradas[chave] = msg
        return True

    async def registrar_saida_vendedor(
        self,
        conversa_id: UUID,
        *,
        loja_id: UUID,
        canal: Canal,
        id_externo: str,
        tipo: TipoMensagem,
        texto: str | None,
        midia_url: str | None,
    ) -> bool:
        chave = (canal, id_externo)
        if chave in self.do_celular:
            return False
        self.do_celular[chave] = (conversa_id, texto)
        return True

    async def definir_nome_se_vazio(
        self, loja_id: UUID, canal: Canal, contato: str, nome: str
    ) -> None:
        self.nomes.setdefault(contato, nome)


class RegistroMemoria:
    def __init__(self) -> None:
        self.ids: set[tuple[UUID, str]] = set()
        self.consultas = 0

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None:
        self.ids.add((loja_id, id_whatsapp))

    async def foi_enviada(self, loja_id: UUID, id_whatsapp: str) -> bool:
        self.consultas += 1
        return (loja_id, id_whatsapp) in self.ids


class PausarFalso:
    def __init__(self) -> None:
        self.chamadas: list[tuple[UUID, UUID]] = []

    async def pausar_por_vendedor(self, loja_id: UUID, lead_id: UUID) -> None:
        self.chamadas.append((loja_id, lead_id))


class GatewayFalso:
    def __init__(self, midia: MidiaBaixada | None = None, falha: bool = False) -> None:
        self.midia = midia or MidiaBaixada(b"bytes", "image/jpeg")
        self.falha = falha
        self.baixadas: list[tuple[UUID, str]] = []

    async def baixar_midia(self, loja_id: UUID, id_mensagem: str) -> MidiaBaixada:
        self.baixadas.append((loja_id, id_mensagem))
        if self.falha:
            raise ErroGateway("fora do ar")
        return self.midia


class ArmazenamentoFalso:
    def __init__(self) -> None:
        self.salvos: list[tuple[bytes, str]] = []

    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        self.salvos.append((dados, tipo_mime))
        return f"{len(self.salvos):032x}.jpg"

    async def ler(self, nome: str) -> ConteudoMidia | None:
        return None


class Cenario:
    def __init__(self, gateway: GatewayFalso | None = None, graca_s: float = 0.0) -> None:
        self.repo = RepoMemoria()
        self.registro = RegistroMemoria()
        self.pausar = PausarFalso()
        self.agendadas: list[UUID] = []
        self.gateway = gateway or GatewayFalso()
        self.armazenamento = ArmazenamentoFalso()

        async def agendar(conversa_id: UUID) -> None:
            self.agendadas.append(conversa_id)

        self.caso = ProcessarMensagemWhatsApp(
            receber=ReceberMensagem(self.repo, agendar),
            mensagens_do_celular=self.repo,
            nomes=self.repo,
            gateway=self.gateway,
            receber_midia=ReceberMidia(self.armazenamento, 1024),
            repo_conversas=self.repo,
            url_midia=lambda nome: f"http://api/midias/{nome}",
            registro=self.registro,
            pausar=self.pausar,
            graca_eco_s=graca_s,
        )


def _evento(
    id_whatsapp: str = "A1",
    *,
    de_mim: bool = False,
    tipo: TipoMensagem = TipoMensagem.TEXTO,
    texto: str | None = "oi",
    tipo_mime: str | None = None,
    baixar_midia: bool = False,
    nome: str | None = "Maria",
) -> EventoMensagemWhatsApp:
    return EventoMensagemWhatsApp(
        loja_id=LOJA,
        id_whatsapp=id_whatsapp,
        de_mim=de_mim,
        contato="5511987654321",
        nome=nome,
        tipo=tipo,
        texto=texto,
        tipo_mime=tipo_mime,
        baixar_midia=baixar_midia,
        recebida_em=EM,
    )


async def test_mensagem_do_cliente_entra_e_agenda_a_conversa() -> None:
    c = Cenario()
    resultado = await c.caso(_evento())
    assert resultado is ResultadoWebhook.PROCESSADA
    (entrada,) = c.repo.entradas.values()
    assert entrada.canal is Canal.WHATSAPP
    assert entrada.remetente == "5511987654321"
    assert entrada.id_externo == f"{LOJA}:A1"
    assert entrada.texto == "oi"
    assert len(c.agendadas) == 1
    assert c.repo.nomes == {"5511987654321": "Maria"}
    assert c.pausar.chamadas == []


async def test_evento_duplicado_nao_duplica_nem_reagenda() -> None:
    c = Cenario()
    assert await c.caso(_evento()) is ResultadoWebhook.PROCESSADA
    assert await c.caso(_evento()) is ResultadoWebhook.DUPLICADA
    assert len(c.repo.entradas) == 1
    assert len(c.agendadas) == 1


async def test_imagem_e_baixada_guardada_e_vira_url() -> None:
    c = Cenario()
    evento = _evento(
        tipo=TipoMensagem.IMAGEM, texto="meu aparelho", tipo_mime="image/jpeg", baixar_midia=True
    )
    await c.caso(evento)
    assert c.gateway.baixadas == [(LOJA, "A1")]
    assert c.armazenamento.salvos == [(b"bytes", "image/jpeg")]
    (entrada,) = c.repo.entradas.values()
    assert entrada.tipo is TipoMensagem.IMAGEM
    assert entrada.midia_url == f"http://api/midias/{1:032x}.jpg"
    assert entrada.texto == "meu aparelho"


async def test_audio_normaliza_o_tipo_mime_com_codec() -> None:
    gateway = GatewayFalso(MidiaBaixada(b"ogg", "audio/ogg; codecs=opus"))
    c = Cenario(gateway)
    evento = _evento(
        tipo=TipoMensagem.AUDIO, texto=None, tipo_mime="audio/ogg; codecs=opus", baixar_midia=True
    )
    await c.caso(evento)
    assert c.armazenamento.salvos == [(b"ogg", "audio/ogg")]


async def test_falha_no_download_ainda_registra_a_mensagem_sem_midia() -> None:
    c = Cenario(GatewayFalso(falha=True))
    evento = _evento(
        tipo=TipoMensagem.IMAGEM, texto=None, tipo_mime="image/jpeg", baixar_midia=True
    )
    assert await c.caso(evento) is ResultadoWebhook.PROCESSADA
    (entrada,) = c.repo.entradas.values()
    assert entrada.tipo is TipoMensagem.IMAGEM
    assert entrada.midia_url is None


async def test_midia_de_tipo_nao_suportado_nao_derruba_o_webhook() -> None:
    c = Cenario(GatewayFalso(MidiaBaixada(b"%PDF", "application/pdf")))
    evento = _evento(
        tipo=TipoMensagem.IMAGEM, texto=None, tipo_mime="image/jpeg", baixar_midia=True
    )
    assert await c.caso(evento) is ResultadoWebhook.PROCESSADA
    assert c.armazenamento.salvos == []


async def test_from_me_registra_como_vendedor_e_pausa_a_ia() -> None:
    c = Cenario()
    resultado = await c.caso(_evento("B1", de_mim=True, texto="Oi, aqui e o Carlos", nome=None))
    assert resultado is ResultadoWebhook.PROCESSADA
    (lead_id, _conversa) = next(iter(c.repo.leads.values()))
    assert c.pausar.chamadas == [(LOJA, lead_id)]
    assert c.repo.do_celular[(Canal.WHATSAPP, f"{LOJA}:B1")][1] == "Oi, aqui e o Carlos"
    assert c.repo.entradas == {}  # nao e mensagem do cliente
    assert c.agendadas == []  # a IA nao responde ao proprio vendedor


async def test_from_me_duplicado_nao_pausa_de_novo() -> None:
    c = Cenario()
    await c.caso(_evento("B1", de_mim=True))
    assert await c.caso(_evento("B1", de_mim=True)) is ResultadoWebhook.DUPLICADA
    assert len(c.pausar.chamadas) == 1


async def test_eco_de_mensagem_enviada_pela_api_nao_pausa_a_ia() -> None:
    c = Cenario()
    await c.registro.registrar(LOJA, "ECO1")
    resultado = await c.caso(_evento("ECO1", de_mim=True, texto="resposta da IA"))
    assert resultado is ResultadoWebhook.ECO
    assert c.pausar.chamadas == []
    assert c.repo.do_celular == {}
    assert c.repo.leads == {}


async def test_eco_do_outro_lado_da_loja_nao_vale() -> None:
    """O id registrado numa loja nao esconde um fromMe de outra loja."""
    c = Cenario()
    await c.registro.registrar(UUID(int=1), "ECO1")
    assert await c.caso(_evento("ECO1", de_mim=True)) is ResultadoWebhook.PROCESSADA


async def test_eco_que_chega_antes_do_registro_e_pego_na_segunda_consulta() -> None:
    """O webhook pode correr mais que o retorno do envio: ha uma tolerancia curta."""
    c = Cenario(graca_s=0.01)
    original = c.registro.foi_enviada

    async def atrasada(loja_id: UUID, id_whatsapp: str) -> bool:
        achou = await original(loja_id, id_whatsapp)
        if not achou:
            c.registro.ids.add((loja_id, id_whatsapp))  # o envio terminou durante a espera
        return achou

    c.registro.foi_enviada = atrasada  # type: ignore[method-assign]
    assert await c.caso(_evento("ECO2", de_mim=True)) is ResultadoWebhook.ECO
    assert c.pausar.chamadas == []
    assert c.registro.consultas == 2  # a primeira nao achou; a segunda, depois da espera, sim


async def test_mensagem_do_cliente_nao_consulta_o_registro_de_ecos() -> None:
    c = Cenario()
    await c.caso(_evento())
    assert c.registro.consultas == 0


async def test_midia_acima_do_limite_nao_derruba_o_webhook() -> None:
    c = Cenario(GatewayFalso(MidiaBaixada(b"x" * 2048, "image/jpeg")))  # limite do cenario: 1024
    evento = _evento(
        tipo=TipoMensagem.IMAGEM, texto=None, tipo_mime="image/jpeg", baixar_midia=True
    )
    assert await c.caso(evento) is ResultadoWebhook.PROCESSADA
    (entrada,) = c.repo.entradas.values()
    assert entrada.midia_url is None
