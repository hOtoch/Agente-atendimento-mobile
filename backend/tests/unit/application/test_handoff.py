"""Handoff: assumir, devolver e chamar o vendedor (em memoria, LLM fake)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria
from app.application.agente.transcricao import (
    CursorEntrada,
    RepositorioTranscricaoEmMemoria,
)
from app.application.handoff import (
    CasosHandoff,
    ConflitoDono,
    ResumoHandoff,
    VendedorNaoEncontrado,
    montar_resumo_estruturado,
)
from app.application.llm import BlocoTexto, ErroLLM, LLMIndisponivel, LLMRecusou
from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.memoria import PublicadorEmMemoria, RepositorioPainelEmMemoria
from app.domain.aparelho import Capacidade, ModeloAparelho
from app.domain.ficha import Ficha, TipoPagamento
from app.domain.valores import Bandeira

AGORA = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


class AvisoGravador:
    def __init__(self, falhar: bool = False) -> None:
        self.chamadas: list[tuple[UUID, UUID, ResumoHandoff]] = []
        self.falhar = falhar

    async def handoff_solicitado(self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff) -> None:
        if self.falhar:
            raise ConnectionError("whatsapp fora do ar")
        self.chamadas.append((loja_id, lead_id, resumo))


def _estado_completo() -> EstadoAtendimento:
    ficha = (
        Ficha.vazia()
        .com_interesse(modelo=ModeloAparelho.de("iPhone 16", "Apple"), capacidade=Capacidade(128))
        .com(tem_troca=True, data_prevista_compra=date(2026, 11, 25))
        .com_usado(modelo=ModeloAparelho.de("iPhone 13", "Apple"), capacidade=Capacidade(128))
        .com_pagamento(tipo=TipoPagamento.CREDITO, parcelas=12, bandeira=Bandeira.MASTERCARD)
    )
    return EstadoAtendimento(
        ficha=ficha,
        ultima_proposta={
            "preco_aparelho": "4830.00",
            "troca": {"status": "avaliada", "valor": "1200.00"},
            "forma_escolhida": {
                "rotulo": "Cartão de crédito em 12x Mastercard",
                "total_pago": "3900.00",
            },
        },
    )


class Cenario:
    def __init__(self, llm: FakeLLM | None = None, aviso: AvisoGravador | None = None) -> None:
        self.loja = uuid4()
        self.vendedor = uuid4()
        self.outro_vendedor = uuid4()
        self.repo = RepositorioPainelEmMemoria()
        self.repo.adicionar_vendedor(self.loja, self.vendedor, "Carla")
        self.repo.adicionar_vendedor(self.loja, self.outro_vendedor, "Davi")
        self.publicador = PublicadorEmMemoria()
        self.transcricao = RepositorioTranscricaoEmMemoria()
        self.atendimento = RepositorioAtendimentoEmMemoria()
        self.llm = llm or FakeLLM([])
        self.aviso = aviso or AvisoGravador()
        self.casos = CasosHandoff(
            repo=self.repo,
            publicador=self.publicador,
            transcricao=self.transcricao,
            atendimento=self.atendimento,
            llm=self.llm,
            aviso=self.aviso,
            agora=lambda: AGORA,
        )

    def lead(self, **campos: object) -> UUID:
        return self.repo.adicionar_lead(self.loja, telefone="s1", **campos)  # type: ignore[arg-type]

    async def estado(self, lead_id: UUID, estado: EstadoAtendimento) -> None:
        await self.atendimento.salvar(self.loja, lead_id, estado)
        self.repo.leads[lead_id] = replace(self.repo.leads[lead_id], estado=estado)


# --- assumir ------------------------------------------------------------------------------------


async def test_assumir_grava_dono_e_publica_dono_mudou() -> None:
    c = Cenario()
    lead = c.lead()
    registro = await c.casos.assumir(c.loja, lead, c.vendedor)

    assert registro.dono == "vendedor" and registro.vendedor_id == c.vendedor
    assert c.repo.leads[lead].dono == "vendedor"
    assert c.repo.leads[lead].vendedor_id == c.vendedor
    (loja, evento) = c.publicador.publicados[0]
    assert loja == c.loja
    assert isinstance(evento, EventoDonoMudou)
    assert evento.dono == f"vendedor:{c.vendedor}" and evento.vendedor_id == c.vendedor


async def test_assumir_aceita_lead_aguardando_vendedor() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=None)
    registro = await c.casos.assumir(c.loja, lead, c.vendedor)
    assert registro.vendedor_id == c.vendedor and registro.dono == "vendedor"


async def test_assumir_conversa_de_outro_vendedor_e_conflito() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.outro_vendedor)
    with pytest.raises(ConflitoDono):
        await c.casos.assumir(c.loja, lead, c.vendedor)


async def test_assumir_com_vendedor_inexistente() -> None:
    c = Cenario()
    with pytest.raises(VendedorNaoEncontrado):
        await c.casos.assumir(c.loja, c.lead(), uuid4())


async def test_assumir_o_que_ja_e_seu_nao_publica_de_novo() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.vendedor)
    await c.casos.assumir(c.loja, lead, c.vendedor)
    assert c.publicador.publicados == []


# --- devolver -----------------------------------------------------------------------------------


async def test_devolver_volta_para_a_ia_e_publica() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.vendedor)
    registro = await c.casos.devolver(c.loja, lead)
    assert registro.dono == "ia"
    assert c.repo.leads[lead].dono == "ia"
    assert c.repo.leads[lead].vendedor_id == c.vendedor  # atribuicao preservada
    (_, evento) = c.publicador.publicados[0]
    assert isinstance(evento, EventoDonoMudou) and evento.dono == "ia"


async def test_devolver_o_que_ja_e_da_ia_e_conflito() -> None:
    c = Cenario()
    with pytest.raises(ConflitoDono):
        await c.casos.devolver(c.loja, c.lead())


async def test_devolver_grava_na_transcricao_as_mensagens_do_vendedor_e_a_instrucao() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.vendedor)
    conversa = c.repo.leads[lead].conversa_id
    assert conversa is not None
    c.repo.adicionar_mensagem(lead, autor="ia", texto="Já chamo um especialista")
    c.repo.adicionar_mensagem(lead, autor="vendedor", texto="Oi, aqui é a Carla. Qual a bateria?")
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="Está em 85%")
    # o cliente ja respondeu ao vendedor: a entrada foi consumida pelo ramo "dono vendedor"
    consumida = c.repo._mensagens[lead][-1]
    await c.transcricao.marcar_consumidas(
        conversa, CursorEntrada(consumida.criada_em, consumida.id)
    )

    await c.casos.devolver(c.loja, lead)

    mensagens = await c.transcricao.listar(conversa)
    assert [m.papel for m in mensagens] == ["system"]
    texto = "".join(b.texto for b in mensagens[0].blocos if isinstance(b, BlocoTexto))
    assert "Vendedor: Oi, aqui é a Carla. Qual a bateria?" in texto
    assert "Cliente: Está em 85%" in texto
    assert "Já chamo um especialista" not in texto  # fala da IA ja esta na transcricao
    assert "não repita" in texto.lower()


async def test_devolver_nao_duplica_entrada_do_cliente_ainda_nao_consumida() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.vendedor)
    conversa = c.repo.leads[lead].conversa_id
    assert conversa is not None
    c.repo.adicionar_mensagem(lead, autor="vendedor", texto="Pode me mandar o print?")
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="mando já")  # ainda nao consumida

    await c.casos.devolver(c.loja, lead)

    (msg,) = await c.transcricao.listar(conversa)
    texto = "".join(b.texto for b in msg.blocos if isinstance(b, BlocoTexto))
    assert "Pode me mandar o print?" in texto
    assert "mando já" not in texto  # vira a mensagem `user` do proximo turno


async def test_devolver_limpa_o_handoff_solicitado_para_a_ia_poder_continuar() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.vendedor)
    await c.estado(lead, EstadoAtendimento(handoff_solicitado=True, motivo_handoff="quer fechar"))

    await c.casos.devolver(c.loja, lead)

    estado = await c.atendimento.obter(c.loja, lead)
    assert estado.handoff_solicitado is False and estado.motivo_handoff is None


# --- chamar o vendedor --------------------------------------------------------------------------


async def test_chamar_vendedor_fica_aguardando_vendedor_e_publica() -> None:
    c = Cenario()
    lead = c.lead(vendedor_id=c.outro_vendedor)  # atribuido antes, depois devolvido
    await c.estado(lead, EstadoAtendimento(handoff_solicitado=True, motivo_handoff="quer fechar"))

    await c.casos.chamar_vendedor(c.loja, lead, "quer fechar")

    registro = c.repo.leads[lead]
    assert registro.dono == "vendedor" and registro.vendedor_id is None
    (_, evento) = c.publicador.publicados[0]
    assert isinstance(evento, EventoDonoMudou)
    assert evento.dono == "vendedor" and evento.vendedor_id is None
    assert evento.para_dict()["vendedor_id"] is None


async def test_chamar_vendedor_grava_o_resumo_e_avisa_o_gancho() -> None:
    llm = FakeLLM([RespostaRoteirizada(texto="Cliente decidido. Quer parcelar. Fechar hoje.")])
    c = Cenario(llm)
    lead = c.lead()
    await c.estado(lead, _estado_completo())
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="quero fechar hoje")

    resumo = await c.casos.chamar_vendedor(c.loja, lead, "cliente quer fechar")

    assert resumo.observacoes == "Cliente decidido. Quer parcelar. Fechar hoje."
    assert resumo.motivo == "cliente quer fechar"
    gravado = await c.casos.resumo_do_lead(c.loja, lead)
    assert gravado == resumo
    assert c.aviso.chamadas == [(c.loja, lead, resumo)]
    # o LLM recebeu a conversa, sem ferramentas
    chamada = llm.chamadas[0]
    assert chamada.ferramentas == []
    texto = "".join(
        b.texto for m in chamada.mensagens for b in m.blocos if isinstance(b, BlocoTexto)
    )
    assert "quero fechar hoje" in texto


@pytest.mark.parametrize(
    "resposta",
    [
        RespostaRoteirizada(erro=LLMIndisponivel("fora")),
        RespostaRoteirizada(erro=LLMRecusou("cyber")),
        RespostaRoteirizada(erro=ErroLLM("qualquer")),
        RespostaRoteirizada(texto="   "),
    ],
)
async def test_resumo_estruturado_sai_mesmo_com_o_llm_falhando(
    resposta: RespostaRoteirizada,
) -> None:
    c = Cenario(FakeLLM([resposta]))
    lead = c.lead()
    await c.estado(lead, _estado_completo())

    resumo = await c.casos.chamar_vendedor(c.loja, lead, "falha_llm")

    assert resumo.observacoes is None
    assert resumo.aparelho_desejado == "iPhone 16 128GB"
    assert resumo.troca == "iPhone 13 128GB"
    assert resumo.valor_troca == Decimal("1200.00")
    assert resumo.proposta == "Cartão de crédito em 12x Mastercard"
    assert resumo.valor_proposta == Decimal("3900.00")
    assert resumo.forma_pagamento is not None and "12x" in resumo.forma_pagamento
    assert resumo.data_prevista == date(2026, 11, 25)
    assert resumo.motivo == "A IA ficou indisponível e passou a conversa para o vendedor"
    assert await c.casos.resumo_do_lead(c.loja, lead) == resumo
    assert len(c.aviso.chamadas) == 1


async def test_resumo_sem_llm_configurado() -> None:
    c = Cenario()
    c.casos = CasosHandoff(
        repo=c.repo,
        publicador=c.publicador,
        transcricao=c.transcricao,
        atendimento=c.atendimento,
        agora=lambda: AGORA,
    )
    lead = c.lead()
    resumo = await c.casos.chamar_vendedor(c.loja, lead, "pediu um vendedor")
    assert resumo.observacoes is None and resumo.motivo == "pediu um vendedor"


async def test_falha_no_gancho_nao_derruba_o_handoff() -> None:
    c = Cenario(FakeLLM([texto_llm("ok")]), AvisoGravador(falhar=True))
    lead = c.lead()
    resumo = await c.casos.chamar_vendedor(c.loja, lead, "x")
    assert resumo.observacoes == "ok"
    assert c.repo.leads[lead].dono == "vendedor"


def texto_llm(t: str) -> RespostaRoteirizada:
    return RespostaRoteirizada(texto=t)


async def test_chamar_vendedor_em_lead_que_ja_e_do_vendedor_nao_republica_o_dono() -> None:
    c = Cenario()
    lead = c.lead(dono="vendedor", vendedor_id=c.vendedor)
    await c.casos.chamar_vendedor(c.loja, lead, "x")
    assert c.repo.leads[lead].vendedor_id == c.vendedor
    assert c.publicador.publicados == []


# --- resumo estruturado (puro) ------------------------------------------------------------------


def test_resumo_estruturado_da_ficha_vazia_tem_todos_os_campos() -> None:
    r = montar_resumo_estruturado(EstadoAtendimento(), motivo="pediu vendedor", agora=AGORA)
    assert r.aparelho_desejado is None and r.troca is None and r.valor_troca is None
    assert r.proposta is None and r.valor_proposta is None
    assert r.forma_pagamento is None and r.data_prevista is None
    assert r.pendencias  # a ficha vazia tem pendencias, em texto legivel
    assert all(isinstance(p, str) and p for p in r.pendencias)
    assert r.observacoes is None
    assert r.motivo == "pediu vendedor"


def test_resumo_sem_troca() -> None:
    estado = EstadoAtendimento(ficha=Ficha.vazia().com(tem_troca=False))
    r = montar_resumo_estruturado(estado, motivo="x", agora=AGORA)
    assert r.troca == "Sem aparelho na troca"
    assert r.valor_troca is None


def test_resumo_dict_ida_e_volta() -> None:
    r = montar_resumo_estruturado(_estado_completo(), motivo="x", agora=AGORA)
    r = replace(r, observacoes="texto")
    d = r.para_dict()
    assert d["valor_troca"] == "1200.00" and d["data_prevista"] == "2026-11-25"
    assert ResumoHandoff.de_dict(d) == r
