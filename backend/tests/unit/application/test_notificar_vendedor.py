"""Notificacao do vendedor no handoff: distribui, atribui o dono e avisa no WhatsApp (fakes)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.canal import Canal
from app.application.config.entradas import EntradaVendedor
from app.application.config.memoria import MemoriaVendedores
from app.application.distribuicao_memoria import MemoriaAtribuicoes
from app.application.distribuir_lead import DistribuirLead
from app.application.handoff import ResumoHandoff
from app.application.notificar_vendedor import (
    NotificarVendedorNoHandoff,
    ServicosDaDistribuicao,
    formatar_brl,
    montar_mensagem_vendedor,
    numero_whatsapp,
)
from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.memoria import PublicadorEmMemoria, RepositorioPainelEmMemoria
from app.application.whatsapp import ErroGateway

D = Decimal
AGORA = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
PAINEL = "https://painel.loja.exemplo"


def resumo_completo(**campos: object) -> ResumoHandoff:
    base: dict[str, object] = {
        "motivo": "Cliente quer fechar",
        "aparelho_desejado": "iPhone 16 128GB",
        "troca": "iPhone 13 128GB",
        "valor_troca": D("1200"),
        "proposta": "Cartão de crédito em 12x",
        "valor_proposta": D("3900.5"),
        "forma_pagamento": "Crédito 12x Mastercard",
        "data_prevista": date(2026, 11, 25),
        "pendencias": ["bateria do usado"],
        "observacoes": "Cliente achou o preço alto, mas quer fechar.",
        "gerado_em": AGORA,
    }
    base.update(campos)
    return ResumoHandoff(**base)  # type: ignore[arg-type]


def resumo_rico(**campos: object) -> ResumoHandoff:
    base: dict[str, object] = dict(
        motivo=(
            "A IA teve uma falha técnica e passou o atendimento para você. "
            "O cliente estava em Interesse qualificado; falta: bandeira do cartão."
        ),
        cor="Preto",
        sku="IP16-128-PT",
        troca_condicao="tela danificada, bateria 82%",
        troca_status="avaliada",
        valor_aparelho=D("4830"),
        desconto=D("130"),
        parcelas=12,
        valor_parcela=D("325"),
        ultimas_mensagens_cliente=[
            "quero o iphone 16",
            "tenho um 13 pra troca",
            "em 12x no master",
        ],
        observacoes=None,
    )
    base.update(campos)
    return resumo_completo(**base)


def resumo_vazio() -> ResumoHandoff:
    return ResumoHandoff(
        motivo="Cliente pediu o vendedor",
        aparelho_desejado=None,
        troca=None,
        valor_troca=None,
        proposta=None,
        valor_proposta=None,
        forma_pagamento=None,
        data_prevista=None,
        pendencias=[],
        observacoes=None,
        gerado_em=AGORA,
    )


# --- funcoes puras ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (D("0"), "R$ 0,00"),
        (D("3900.5"), "R$ 3.900,50"),
        (D("1234567.895"), "R$ 1.234.567,90"),
        (D("0.005"), "R$ 0,01"),
        (D("4830"), "R$ 4.830,00"),
    ],
)
def test_formata_brl_com_decimal_e_half_up(valor: Decimal, esperado: str) -> None:
    assert formatar_brl(valor) == esperado


@pytest.mark.parametrize(
    ("telefone", "esperado"),
    [
        ("(11) 98888-7777", "5511988887777"),
        ("+55 11 98888-7777", "5511988887777"),
        ("1133334444", "551133334444"),
        ("5511988887777", "5511988887777"),
        ("", None),
        (None, None),
        ("sem numero", None),
    ],
)
def test_numero_whatsapp_so_digitos_com_ddi(telefone: str | None, esperado: str | None) -> None:
    assert numero_whatsapp(telefone) == esperado


def test_mensagem_traz_lead_resumo_e_link() -> None:
    lead_id = uuid4()
    texto = montar_mensagem_vendedor(
        lead_id=lead_id,
        lead_nome="Marcos",
        lead_telefone="5511999990000",
        canal=Canal.WHATSAPP,
        resumo=resumo_completo(),
        url_painel=PAINEL + "/",
    )
    for trecho in (
        "Marcos",
        "+5511999990000",
        "iPhone 16 128GB",
        "iPhone 13 128GB",
        "R$ 1.200,00",
        "R$ 3.900,50",
        "Crédito 12x Mastercard",
        "25/11/2026",
        "bateria do usado",
        "Cliente achou o preço alto",
        f"{PAINEL}/conversas?lead={lead_id}",
    ):
        assert trecho in texto
    assert "//conversas" not in texto


def test_mensagem_traz_o_resumo_completo_sem_o_llm() -> None:
    texto = montar_mensagem_vendedor(
        lead_id=uuid4(),
        lead_nome="Marcos",
        lead_telefone="5511999990000",
        canal=Canal.WHATSAPP,
        resumo=resumo_rico(),
        url_painel=PAINEL,
    )
    for trecho in (
        "Motivo: A IA teve uma falha técnica e passou o atendimento para você.",
        "Aparelho: iPhone 16 128GB, Preto (SKU IP16-128-PT)",
        "Troca: iPhone 13 128GB (tela danificada, bateria 82%) - avaliada em R$ 1.200,00",
        "Proposta: Cartão de crédito em 12x - total R$ 3.900,50 (12x de R$ 325,00)",
        "Valores: aparelho R$ 4.830,00, troca R$ 1.200,00, desconto R$ 130,00",
        "Pagamento: Crédito 12x Mastercard",
        "Data prevista: 25/11/2026",
        "Pendências: bateria do usado",
        "Últimas mensagens do cliente:",
        '- "quero o iphone 16"',
        '- "tenho um 13 pra troca"',
        '- "em 12x no master"',
    ):
        assert trecho in texto, trecho
    assert "Observações" not in texto
    assert "falha_llm" not in texto


def test_mensagem_troca_avaliada_na_loja() -> None:
    texto = montar_mensagem_vendedor(
        lead_id=uuid4(),
        lead_nome=None,
        lead_telefone="abc",
        canal=Canal.WEBCHAT,
        resumo=resumo_rico(troca_status="avaliacao_na_loja", valor_troca=None),
        url_painel=PAINEL,
    )
    assert "Troca: iPhone 13 128GB (tela danificada, bateria 82%) - avaliação na loja" in texto
    assert "troca R$" not in texto


def test_mensagem_de_resumo_antigo_continua_valida() -> None:
    texto = montar_mensagem_vendedor(
        lead_id=uuid4(),
        lead_nome="Ana",
        lead_telefone="abc",
        canal=Canal.WEBCHAT,
        resumo=resumo_completo(),
        url_painel=PAINEL,
    )
    assert "Últimas mensagens" not in texto and "Valores:" not in texto


def test_mensagem_omite_o_que_nao_existe() -> None:
    texto = montar_mensagem_vendedor(
        lead_id=uuid4(),
        lead_nome=None,
        lead_telefone="abc123",
        canal=Canal.WEBCHAT,
        resumo=resumo_vazio(),
        url_painel=PAINEL,
    )
    assert "Cliente pediu o vendedor" in texto
    assert "None" not in texto and "R$" not in texto
    assert "Pendências" not in texto and "Observações" not in texto
    assert "Troca" not in texto


# --- caso de uso --------------------------------------------------------------------------------


class GatewayGravador:
    def __init__(self, *, falhar: bool = False) -> None:
        self.enviados: list[tuple[UUID, str, str]] = []
        self.falhar = falhar

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
        if self.falhar:
            raise ErroGateway("instancia desconectada", status=400)
        self.enviados.append((loja_id, numero, texto))
        return f"ID{len(self.enviados)}"


class RegistroGravador:
    def __init__(self) -> None:
        self.ids: list[tuple[UUID, str]] = []

    async def registrar(self, loja_id: UUID, id_whatsapp: str) -> None:
        self.ids.append((loja_id, id_whatsapp))


class Cenario:
    def __init__(self, *, gateway: GatewayGravador | None = None) -> None:
        self.loja = uuid4()
        self.vendedores = MemoriaVendedores()
        self.atribuicoes = MemoriaAtribuicoes()
        self.repo = RepositorioPainelEmMemoria()
        self.publicador = PublicadorEmMemoria()
        self.gateway = gateway or GatewayGravador()
        self.registro = RegistroGravador()
        self.sessoes = 0
        self.sessoes_abertas = 0
        self.caso = NotificarVendedorNoHandoff(
            abrir=self._abrir,
            gateway=self.gateway,
            registro=self.registro,
            publicador=self.publicador,
            url_painel=PAINEL,
        )

    @asynccontextmanager
    async def _abrir(self) -> AsyncIterator[ServicosDaDistribuicao]:
        self.sessoes += 1
        self.sessoes_abertas += 1
        try:
            yield ServicosDaDistribuicao(
                distribuir=DistribuirLead(self.vendedores, self.atribuicoes),
                repo=self.repo,
                vendedores=self.vendedores,
            )
        finally:
            self.sessoes_abertas -= 1

    async def vendedor(self, nome: str, telefone: str | None, peso: str = "100") -> UUID:
        atuais = [
            EntradaVendedor(v.id, v.nome, v.telefone, v.peso_percentual, v.ativo)
            for v in await self.vendedores.listar(self.loja)
        ]
        lista = await self.vendedores.substituir(
            self.loja, [*atuais, EntradaVendedor(None, nome, telefone, D(peso), True)]
        )
        vid = lista[-1].id
        self.repo.adicionar_vendedor(self.loja, vid, nome)
        return vid

    def lead(self, **campos: object) -> UUID:
        lead_id = self.repo.adicionar_lead(
            self.loja,
            telefone=str(campos.pop("telefone", "5511977776666")),
            canal=Canal.WHATSAPP,
            dono="vendedor",  # estado em que o handoff deixa o lead: aguardando vendedor
            **campos,  # type: ignore[arg-type]
        )
        self.atribuicoes.criar_lead(self.loja, lead_id)
        return lead_id


async def test_handoff_envia_ao_vendedor_certo() -> None:
    c = Cenario()
    carla = await c.vendedor("Carla", "(11) 98888-1111", "100")
    lead = c.lead(nome="Marcos")
    await c.caso.handoff_solicitado(c.loja, lead, resumo_completo())

    assert c.repo.leads[lead].vendedor_id == carla
    assert c.repo.leads[lead].dono == "vendedor"
    ((loja, numero, texto),) = c.gateway.enviados
    assert (loja, numero) == (c.loja, "5511988881111")
    assert "Marcos" in texto and f"/conversas?lead={lead}" in texto
    assert c.registro.ids == [(c.loja, "ID1")]


async def test_mensagem_vai_para_o_vendedor_escolhido_pela_distribuicao() -> None:
    c = Cenario()
    carla = await c.vendedor("Carla", "11900000001", "75")
    davi = await c.vendedor("Davi", "11900000002", "25")
    destinos: list[str] = []
    for _ in range(8):
        await c.caso.handoff_solicitado(c.loja, c.lead(), resumo_completo())
        destinos.append(c.gateway.enviados[-1][1])
    # 75/25 sobre 8 leads: 6 para a Carla e 2 para o Davi, cada um no seu telefone
    assert destinos.count("5511900000001") == 6
    assert destinos.count("5511900000002") == 2
    contagem = c.atribuicoes.contagem(c.loja)
    assert contagem == {carla: 6, davi: 2}


async def test_atribui_dono_e_publica_dono_mudou_com_vendedor() -> None:
    c = Cenario()
    carla = await c.vendedor("Carla", "11900000001")
    lead = c.lead()
    await c.caso.handoff_solicitado(c.loja, lead, resumo_completo())

    dono = f"vendedor:{carla}"
    (loja, evento) = c.publicador.publicados[-1]
    assert loja == c.loja
    assert isinstance(evento, EventoDonoMudou)
    assert (evento.lead_id, evento.dono, evento.vendedor_id) == (lead, dono, carla)
    evento_banco = c.repo.eventos_de(lead)[-1]
    assert evento_banco.tipo == "dono_mudou"
    assert evento_banco.payload["origem"] == "distribuicao"


async def test_sem_vendedor_disponivel_deixa_aguardando_e_nao_envia() -> None:
    c = Cenario()
    lead = c.lead()
    await c.caso.handoff_solicitado(c.loja, lead, resumo_completo())  # nao levanta
    assert c.repo.leads[lead].dono == "vendedor"
    assert c.repo.leads[lead].vendedor_id is None
    assert c.gateway.enviados == [] and c.publicador.publicados == []


async def test_vendedor_sem_telefone_fica_atribuido_mas_nao_envia() -> None:
    c = Cenario()
    carla = await c.vendedor("Carla", None)
    lead = c.lead()
    await c.caso.handoff_solicitado(c.loja, lead, resumo_completo())
    assert c.repo.leads[lead].vendedor_id == carla
    assert c.gateway.enviados == []
    assert len(c.publicador.publicados) == 1


async def test_whatsapp_desconectado_nao_desfaz_a_atribuicao() -> None:
    c = Cenario(gateway=GatewayGravador(falhar=True))
    carla = await c.vendedor("Carla", "11900000001")
    lead = c.lead()
    await c.caso.handoff_solicitado(c.loja, lead, resumo_completo())  # nao levanta
    assert c.repo.leads[lead].vendedor_id == carla
    assert c.registro.ids == []


async def test_envio_so_acontece_depois_de_fechar_a_transacao() -> None:
    c = Cenario()
    await c.vendedor("Carla", "11900000001")

    class GatewayQueConfere(GatewayGravador):
        async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
            assert c.sessoes_abertas == 0, "a trava da loja nao pode durar durante o HTTP"
            return await super().enviar_texto(loja_id, numero, texto)

    c.gateway = GatewayQueConfere()
    c.caso = NotificarVendedorNoHandoff(
        abrir=c._abrir,
        gateway=c.gateway,
        registro=c.registro,
        publicador=c.publicador,
        url_painel=PAINEL,
    )
    await c.caso.handoff_solicitado(c.loja, c.lead(), resumo_completo())
    assert len(c.gateway.enviados) == 1


async def test_lead_que_ja_tem_vendedor_dono_nao_e_redistribuido_nem_reavisado() -> None:
    c = Cenario()
    carla = await c.vendedor("Carla", "11900000001")
    await c.vendedor("Davi", "11900000002")
    lead = c.lead(vendedor_id=carla)
    await c.caso.handoff_solicitado(c.loja, lead, resumo_completo())
    assert c.gateway.enviados == [] and c.publicador.publicados == []
    assert c.sessoes == 1


async def test_lead_inexistente_so_loga() -> None:
    c = Cenario()
    await c.vendedor("Carla", "11900000001")
    await c.caso.handoff_solicitado(c.loja, uuid4(), resumo_completo())
    assert c.gateway.enviados == []
