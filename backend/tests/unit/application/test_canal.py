"""ReceberMensagem com repositorio em memoria e `agendar` fake."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.canal import (
    Canal,
    MensagemEntrada,
    ReceberMensagem,
    TipoMensagem,
)


class RepoMemoria:
    def __init__(self) -> None:
        self.leads: dict[tuple[UUID, Canal, str], tuple[UUID, UUID]] = {}
        self.ids: set[tuple[Canal, str]] = set()

    async def obter_ou_criar(self, loja_id: UUID, canal: Canal, contato: str) -> tuple[UUID, UUID]:
        chave = (loja_id, canal, contato)
        if chave not in self.leads:
            self.leads[chave] = (uuid4(), uuid4())
        return self.leads[chave]

    async def registrar_entrada(self, conversa_id: UUID, msg: MensagemEntrada) -> bool:
        chave = (msg.canal, msg.id_externo)
        if chave in self.ids:
            return False
        self.ids.add(chave)
        return True


def _msg(id_externo: str = "m1", remetente: str = "s1") -> MensagemEntrada:
    return MensagemEntrada(
        loja_id=UUID(int=1),
        canal=Canal.WEBCHAT,
        id_externo=id_externo,
        remetente=remetente,
        tipo=TipoMensagem.TEXTO,
        texto="oi",
        midia_url=None,
        recebida_em=datetime.now(UTC),
    )


def test_valores_dos_enums_batem_com_o_banco() -> None:
    assert [c.value for c in Canal] == ["webchat", "whatsapp", "instagram"]
    assert [t.value for t in TipoMensagem] == ["texto", "audio", "imagem"]


async def test_mensagem_nova_agenda_a_conversa() -> None:
    agendadas: list[UUID] = []

    async def agendar(conversa_id: UUID) -> None:
        agendadas.append(conversa_id)

    caso = ReceberMensagem(RepoMemoria(), agendar)
    conversa_id, nova = await caso(_msg())
    assert nova is True
    assert agendadas == [conversa_id]


async def test_mesmo_id_externo_nao_duplica_nem_reagenda() -> None:
    agendadas: list[UUID] = []

    async def agendar(conversa_id: UUID) -> None:
        agendadas.append(conversa_id)

    caso = ReceberMensagem(RepoMemoria(), agendar)
    c1, n1 = await caso(_msg())
    c2, n2 = await caso(_msg())
    assert (n1, n2) == (True, False)
    assert c1 == c2
    assert len(agendadas) == 1


async def test_mensagens_diferentes_da_mesma_sessao_reusam_conversa() -> None:
    async def agendar(conversa_id: UUID) -> None:
        return None

    caso = ReceberMensagem(RepoMemoria(), agendar)
    c1, _ = await caso(_msg("a"))
    c2, _ = await caso(_msg("b"))
    assert c1 == c2


async def test_receber_publica_mensagem_nova_para_o_painel_so_quando_e_nova() -> None:
    from app.application.painel.memoria import PublicadorEmMemoria

    async def agendar(_: UUID) -> None:
        return None

    painel = PublicadorEmMemoria()
    repo = RepoMemoria()
    receber = ReceberMensagem(repo, agendar, painel=painel)

    conversa_id, _ = await receber(_msg("m1"))
    await receber(_msg("m1"))  # duplicada: nao publica de novo

    assert len(painel.publicados) == 1
    loja, evento = painel.publicados[0]
    assert loja == UUID(int=1)
    assert evento.nome == "MensagemNova"  # type: ignore[union-attr]
    assert evento.conversa_id == conversa_id  # type: ignore[union-attr]
    assert (evento.autor, evento.direcao, evento.texto) == ("cliente", "entrada", "oi")  # type: ignore[union-attr]
    assert evento.lead_id == repo.leads[(UUID(int=1), Canal.WEBCHAT, "s1")][0]  # type: ignore[union-attr]
