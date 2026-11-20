"""Casos de uso do painel com repositorio e publicador em memoria (sem IO)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal, MensagemSaida
from app.application.painel.casos_de_uso import (
    CasosPainel,
    ConflitoDono,
    LeadNaoEncontrado,
    MovimentoEtapaInvalido,
    VendedorNaoEncontrado,
)
from app.application.painel.eventos import (
    EventoDonoMudou,
    EventoEtapaMudou,
    EventoMensagemNova,
)
from app.application.painel.memoria import PublicadorEmMemoria, RepositorioPainelEmMemoria
from app.domain.aparelho import Capacidade, ModeloAparelho
from app.domain.ficha import Ficha
from app.domain.kanban import Etapa

AGORA = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


class CanalFalso:
    def __init__(self) -> None:
        self.enviadas: list[MensagemSaida] = []

    async def enviar(self, msg: MensagemSaida) -> None:
        self.enviadas.append(msg)


class Cenario:
    def __init__(self) -> None:
        self.loja = uuid4()
        self.vendedor = uuid4()
        self.repo = RepositorioPainelEmMemoria()
        self.repo.adicionar_vendedor(self.loja, self.vendedor, "Carla")
        self.publicador = PublicadorEmMemoria()
        self.canal = CanalFalso()
        self.casos = CasosPainel(
            repo=self.repo,
            publicador=self.publicador,
            canais={Canal.WEBCHAT: self.canal},
            agora=lambda: AGORA,
        )

    def lead(self, **campos: object) -> UUID:
        return self.repo.adicionar_lead(self.loja, **campos)  # type: ignore[arg-type]


@pytest.fixture
def c() -> Cenario:
    return Cenario()


def _estado_com_interesse() -> EstadoAtendimento:
    ficha = Ficha.vazia().com_interesse(
        modelo=ModeloAparelho.de("iPhone 16", "Apple"), capacidade=Capacidade(128)
    )
    return EstadoAtendimento(
        ficha=ficha,
        ultima_proposta={
            "preco_aparelho": "4830.00",
            "forma_escolhida": {"rotulo": "Cartao 12x", "total_pago": "5339.40"},
        },
    )


# --- kanban -----------------------------------------------------------------------------------


async def test_kanban_traz_as_cinco_etapas_em_ordem_mesmo_vazias(c: Cenario) -> None:
    colunas = await c.casos.kanban(c.loja)
    assert [col.etapa for col in colunas] == list(Etapa)
    assert all(col.leads == [] for col in colunas)
    assert colunas[0].nome == "Novo contato"


async def test_kanban_agrupa_por_etapa_com_dados_do_card(c: Cenario) -> None:
    novo = c.lead(nome="Ana", telefone="s1")
    qualificado = c.lead(
        nome="Bia",
        telefone="5511999990000",
        etapa=Etapa.INTERESSE_QUALIFICADO,
        estado=_estado_com_interesse(),
        etapa_desde=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
        dono="vendedor",
        vendedor_id=c.vendedor,
    )
    colunas = {col.etapa: col for col in await c.casos.kanban(c.loja)}

    assert [x.id for x in colunas[Etapa.NOVO_CONTATO].leads] == [novo]
    card = colunas[Etapa.INTERESSE_QUALIFICADO].leads[0]
    assert card.id == qualificado
    assert card.nome == "Bia"
    assert card.telefone == "5511999990000"
    assert card.aparelho_desejado == "iPhone 16 128GB"
    assert card.valor_estimado == Decimal("5339.40")
    assert card.dono == f"vendedor:{c.vendedor}"
    assert card.vendedor_id == c.vendedor
    assert card.vendedor_nome == "Carla"
    assert card.etapa_desde == datetime(2026, 11, 20, 14, 0, tzinfo=UTC)


async def test_card_sem_proposta_usa_preco_do_aparelho_ou_nada(c: Cenario) -> None:
    sem = c.lead(telefone="a")
    pix = c.lead(
        telefone="b",
        estado=EstadoAtendimento(ultima_proposta={"forma_escolhida": {"valor_a_vista": "4500.00"}}),
    )
    colunas = await c.casos.kanban(c.loja)
    cards = {x.id: x for x in colunas[0].leads}
    assert cards[sem].valor_estimado is None
    assert cards[sem].aparelho_desejado is None
    assert cards[sem].dono == "ia"
    assert cards[pix].valor_estimado == Decimal("4500.00")


async def test_kanban_so_traz_leads_da_loja(c: Cenario) -> None:
    c.repo.adicionar_lead(uuid4(), telefone="outra-loja")
    c.lead(telefone="minha")
    colunas = await c.casos.kanban(c.loja)
    assert [x.telefone for x in colunas[0].leads] == ["minha"]


# --- detalhe ----------------------------------------------------------------------------------


async def test_detalhe_traz_ficha_pendencias_mensagens_e_eventos(c: Cenario) -> None:
    lead = c.lead(telefone="s1", estado=_estado_com_interesse())
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="oi")
    c.repo.adicionar_mensagem(lead, autor="ia", texto="ola!")
    c.repo.adicionar_evento(lead, "etapa_mudou", {"de": "novo_contato"})

    d = await c.casos.detalhe(c.loja, lead)

    assert d.card.id == lead
    assert d.ficha["interesse"]["capacidade"] == 128
    assert "estoque_confirmado" in d.pendencias
    assert "aparelho_modelo" not in d.pendencias
    assert [m.texto for m in d.mensagens] == ["oi", "ola!"]
    assert [m.autor for m in d.mensagens] == ["cliente", "ia"]
    assert [e.tipo for e in d.eventos] == ["etapa_mudou"]
    assert d.proposta is not None


async def test_detalhe_de_lead_inexistente_ou_de_outra_loja(c: Cenario) -> None:
    de_outra = c.repo.adicionar_lead(uuid4(), telefone="x")
    with pytest.raises(LeadNaoEncontrado):
        await c.casos.detalhe(c.loja, uuid4())
    with pytest.raises(LeadNaoEncontrado):
        await c.casos.detalhe(c.loja, de_outra)


# --- mover etapa ------------------------------------------------------------------------------


async def test_mover_etapa_valido_grava_e_publica(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    card = await c.casos.mover_etapa(c.loja, lead, Etapa.COM_O_VENDEDOR)

    assert card.etapa is Etapa.COM_O_VENDEDOR
    assert c.repo.leads[lead].etapa is Etapa.COM_O_VENDEDOR
    assert c.repo.eventos_de(lead)[-1].tipo == "etapa_mudou"
    assert c.repo.eventos_de(lead)[-1].payload["ator"] == "vendedor"
    assert c.publicador.publicados == [
        (
            c.loja,
            EventoEtapaMudou(
                lead_id=lead,
                de=Etapa.NOVO_CONTATO,
                para=Etapa.COM_O_VENDEDOR,
                ator="vendedor",
                motivo="Movido manualmente para Com o vendedor.",
                em=AGORA,
            ),
        )
    ]


async def test_mover_para_venda_fechada_e_permitido_so_manual(c: Cenario) -> None:
    lead = c.lead(telefone="s1", etapa=Etapa.COM_O_VENDEDOR)
    card = await c.casos.mover_etapa(c.loja, lead, Etapa.VENDA_FECHADA)
    assert card.etapa is Etapa.VENDA_FECHADA


async def test_mover_para_a_mesma_etapa_e_invalido(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    with pytest.raises(MovimentoEtapaInvalido):
        await c.casos.mover_etapa(c.loja, lead, Etapa.NOVO_CONTATO)
    assert c.publicador.publicados == []


async def test_venda_fechada_e_etapa_final(c: Cenario) -> None:
    lead = c.lead(telefone="s1", etapa=Etapa.VENDA_FECHADA)
    with pytest.raises(MovimentoEtapaInvalido) as exc:
        await c.casos.mover_etapa(c.loja, lead, Etapa.NOVO_CONTATO)
    assert "final" in exc.value.motivo
    assert c.repo.leads[lead].etapa is Etapa.VENDA_FECHADA
    assert c.publicador.publicados == []


async def test_mover_lead_inexistente(c: Cenario) -> None:
    with pytest.raises(LeadNaoEncontrado):
        await c.casos.mover_etapa(c.loja, uuid4(), Etapa.COM_O_VENDEDOR)


# --- assumir / devolver -----------------------------------------------------------------------


async def test_assumir_troca_o_dono_e_publica(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    card = await c.casos.assumir(c.loja, lead, c.vendedor)

    assert card.dono == f"vendedor:{c.vendedor}"
    assert card.vendedor_nome == "Carla"
    assert c.repo.leads[lead].dono == "vendedor"
    assert c.repo.leads[lead].vendedor_id == c.vendedor
    assert c.repo.eventos_de(lead)[-1].tipo == "dono_mudou"
    assert c.publicador.publicados == [
        (
            c.loja,
            EventoDonoMudou(
                lead_id=lead, dono=f"vendedor:{c.vendedor}", vendedor_id=c.vendedor, em=AGORA
            ),
        )
    ]


async def test_assumir_com_vendedor_de_outra_loja_ou_inexistente(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    outra = uuid4()
    c.repo.adicionar_vendedor(uuid4(), outra, "De fora")
    for vendedor in (uuid4(), outra):
        with pytest.raises(VendedorNaoEncontrado):
            await c.casos.assumir(c.loja, lead, vendedor)
    assert c.repo.leads[lead].dono == "ia"


async def test_assumir_lead_ja_assumido_por_outro_e_conflito(c: Cenario) -> None:
    lead = c.lead(telefone="s1", dono="vendedor", vendedor_id=c.vendedor)
    outro = uuid4()
    c.repo.adicionar_vendedor(c.loja, outro, "Dani")
    with pytest.raises(ConflitoDono):
        await c.casos.assumir(c.loja, lead, outro)


async def test_assumir_de_novo_pelo_mesmo_vendedor_e_idempotente(c: Cenario) -> None:
    lead = c.lead(telefone="s1", dono="vendedor", vendedor_id=c.vendedor)
    card = await c.casos.assumir(c.loja, lead, c.vendedor)
    assert card.dono == f"vendedor:{c.vendedor}"
    assert c.publicador.publicados == []


async def test_devolver_volta_para_a_ia_e_publica(c: Cenario) -> None:
    lead = c.lead(telefone="s1", dono="vendedor", vendedor_id=c.vendedor)
    card = await c.casos.devolver(c.loja, lead)

    assert card.dono == "ia"
    assert card.vendedor_id == c.vendedor  # a atribuicao do lead permanece
    assert c.publicador.publicados == [
        (c.loja, EventoDonoMudou(lead_id=lead, dono="ia", vendedor_id=None, em=AGORA))
    ]


async def test_devolver_lead_que_ja_e_da_ia_e_conflito(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    with pytest.raises(ConflitoDono):
        await c.casos.devolver(c.loja, lead)


# --- mensagem do vendedor ---------------------------------------------------------------------


async def test_enviar_mensagem_exige_que_o_vendedor_tenha_assumido(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    with pytest.raises(ConflitoDono):
        await c.casos.enviar_mensagem(c.loja, lead, "oi")
    assert c.canal.enviadas == []


async def test_enviar_mensagem_envia_pelo_canal_persiste_e_publica(c: Cenario) -> None:
    lead = c.lead(telefone="sessao-1", dono="vendedor", vendedor_id=c.vendedor)
    envio = await c.casos.enviar_mensagem(c.loja, lead, "  Posso ajudar!  ")

    assert envio.enviada is True
    assert envio.mensagem.autor == "vendedor"
    assert envio.mensagem.texto == "Posso ajudar!"
    assert [(m.destinatario, m.texto) for m in c.canal.enviadas] == [("sessao-1", "Posso ajudar!")]
    assert [m.autor for m in await c.repo.listar_mensagens(c.loja, lead)] == ["vendedor"]
    (loja, evento) = c.publicador.publicados[-1]
    assert loja == c.loja
    assert isinstance(evento, EventoMensagemNova)
    assert (evento.lead_id, evento.autor, evento.direcao, evento.texto) == (
        lead,
        "vendedor",
        "saida",
        "Posso ajudar!",
    )


async def test_enviar_em_canal_sem_adaptador_persiste_mas_nao_marca_enviada() -> None:
    c = Cenario()
    lead = c.lead(telefone="5511", canal=Canal.WHATSAPP, dono="vendedor", vendedor_id=c.vendedor)
    envio = await c.casos.enviar_mensagem(c.loja, lead, "oi")
    assert envio.enviada is False
    assert c.canal.enviadas == []
    assert len(await c.repo.listar_mensagens(c.loja, lead)) == 1


async def test_falha_do_publicador_nao_derruba_o_caso_de_uso(c: Cenario) -> None:
    lead = c.lead(telefone="s1")
    c.publicador.falhar = True
    card = await c.casos.mover_etapa(c.loja, lead, Etapa.COM_O_VENDEDOR)
    assert card.etapa is Etapa.COM_O_VENDEDOR
