"""Handoff: assumir, devolver e chamar o vendedor (em memoria, LLM fake)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
from app.application.canal import TipoMensagem
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
from app.application.painel.portas import MensagemRegistro
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
    assert resumo.motivo.startswith("A IA teve uma falha técnica e passou o atendimento para você.")
    assert "falha_llm" not in resumo.motivo
    assert await c.casos.resumo_do_lead(c.loja, lead) == resumo
    assert len(c.aviso.chamadas) == 1


async def test_resumo_completo_sem_o_llm_traz_aparelho_troca_proposta_e_falas_do_cliente() -> None:
    c = Cenario(FakeLLM([RespostaRoteirizada(erro=LLMIndisponivel("sem credito"))]))
    lead = c.lead()
    await c.estado(lead, _estado_completo())
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="oi, quero o iphone 16")
    c.repo.adicionar_mensagem(lead, autor="ia", texto="Qual capacidade?")
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="128, tenho um 13 pra troca")
    c.repo.adicionar_mensagem(lead, autor="cliente", texto="pode ser em 12x no master")

    resumo = await c.casos.chamar_vendedor(c.loja, lead, "falha_llm")

    assert resumo.observacoes is None
    assert resumo.aparelho_desejado == "iPhone 16 128GB"
    assert resumo.troca == "iPhone 13 128GB"
    assert resumo.valor_troca == Decimal("1200.00")
    assert resumo.valor_aparelho == Decimal("4830.00")
    assert resumo.valor_proposta == Decimal("3900.00")
    assert resumo.ultimas_mensagens_cliente == [
        "oi, quero o iphone 16",
        "128, tenho um 13 pra troca",
        "pode ser em 12x no master",
    ]
    gravado = await c.casos.resumo_do_lead(c.loja, lead)
    assert gravado == resumo


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
    assert r.ultimas_mensagens_cliente == []


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


def _msg(autor: str, texto: str | None, tipo: str = "texto", n: int = 0) -> MensagemRegistro:
    return MensagemRegistro(
        id=uuid4(),
        conversa_id=uuid4(),
        direcao="entrada" if autor == "cliente" else "saida",
        autor=autor,
        tipo=TipoMensagem(tipo),
        texto=texto,
        midia_url=None,
        criada_em=AGORA + timedelta(seconds=n),
    )


def _estado_rico() -> EstadoAtendimento:
    base = _estado_completo()
    ficha = base.ficha.com_interesse(cor="Preto", sku_estoque_confirmado="IP16-128-PT").com_usado(
        tela_danificada=True,
        traseira_danificada=False,
        carcaca_marcada=False,
        bateria_pct=82,
        camera_ok=True,
        outros_defeitos=(),
        peca_trocada=False,
    )
    proposta = {
        "aparelho": {"sku": "IP16-128-PT", "modelo": "iPhone 16", "cor": "Preto"},
        "preco_aparelho": "4830.00",
        "troca": {"status": "avaliada", "valor": "1200.00"},
        "desconto": {"negociado": "100.00", "total": "130.00"},
        "forma_escolhida": {
            "rotulo": "Cartão de crédito em 12x Mastercard",
            "parcelas": 12,
            "valor_parcela": "325.00",
            "total_pago": "3900.00",
        },
    }
    return replace(base, ficha=ficha, ultima_proposta=proposta)


def test_resumo_estruturado_com_ficha_completa_traz_todos_os_campos() -> None:
    r = montar_resumo_estruturado(_estado_rico(), motivo="x", agora=AGORA)
    assert r.aparelho_desejado == "iPhone 16 128GB"
    assert r.cor == "Preto" and r.sku == "IP16-128-PT"
    assert r.troca == "iPhone 13 128GB"
    assert r.troca_condicao == "tela danificada, bateria 82%"
    assert r.troca_status == "avaliada" and r.valor_troca == Decimal("1200.00")
    assert r.valor_aparelho == Decimal("4830.00")
    assert r.desconto == Decimal("130.00")
    assert r.proposta == "Cartão de crédito em 12x Mastercard"
    assert r.valor_proposta == Decimal("3900.00")
    assert r.parcelas == 12 and r.valor_parcela == Decimal("325.00")
    assert r.forma_pagamento is not None and "12x" in r.forma_pagamento
    assert r.data_prevista == date(2026, 11, 25)
    assert r.pendencias == [] or all(isinstance(p, str) for p in r.pendencias)


def test_resumo_pega_cor_e_sku_da_proposta_quando_a_ficha_nao_tem() -> None:
    estado = replace(_estado_rico(), ficha=_estado_completo().ficha)
    r = montar_resumo_estruturado(estado, motivo="x", agora=AGORA)
    assert r.cor == "Preto" and r.sku == "IP16-128-PT"


def test_resumo_troca_avaliada_na_loja_nao_inventa_valor() -> None:
    estado = replace(
        _estado_rico(),
        ultima_proposta={
            "preco_aparelho": "4830.00",
            "troca": {"status": "avaliacao_na_loja", "motivo": "aparelho muito danificado"},
            "forma_escolhida": {"rotulo": "Pix ou dinheiro à vista", "valor_a_vista": "4830.00"},
        },
    )
    r = montar_resumo_estruturado(estado, motivo="x", agora=AGORA)
    assert r.troca_status == "avaliacao_na_loja" and r.valor_troca is None
    assert r.valor_proposta == Decimal("4830.00")
    assert r.parcelas is None and r.valor_parcela is None


def test_resumo_condicao_do_usado_sem_avarias() -> None:
    ficha = _estado_completo().ficha.com_usado(
        tela_danificada=False, traseira_danificada=False, camera_ok=True
    )
    r = montar_resumo_estruturado(EstadoAtendimento(ficha=ficha), motivo="x", agora=AGORA)
    assert r.troca_condicao == "sem avarias informadas"


def test_resumo_so_guarda_as_ultimas_tres_falas_do_cliente_truncadas() -> None:
    mensagens = [
        _msg("cliente", "primeira", n=1),
        _msg("ia", "resposta da IA", n=2),
        _msg("cliente", "segunda", n=3),
        _msg("cliente", None, tipo="audio", n=4),
        _msg("vendedor", "oi", n=5),
        _msg("cliente", "x" * 500, n=6),
    ]
    r = montar_resumo_estruturado(EstadoAtendimento(), motivo="x", agora=AGORA, mensagens=mensagens)
    assert r.ultimas_mensagens_cliente[:2] == ["segunda", "[áudio]"]
    assert len(r.ultimas_mensagens_cliente) == 3
    ultima = r.ultimas_mensagens_cliente[2]
    assert ultima.startswith("xxx") and ultima.endswith("…") and len(ultima) <= 160


def test_motivo_falha_llm_e_legivel_e_acionavel() -> None:
    estado = _estado_rico()
    estado = replace(estado, ficha=estado.ficha.com_pagamento(bandeira=None))
    r = montar_resumo_estruturado(estado, motivo="falha_llm", agora=AGORA)
    assert r.motivo.startswith("A IA teve uma falha técnica e passou o atendimento para você.")
    assert "falha_llm" not in r.motivo and "LLM" not in r.motivo
    assert "O cliente estava em " in r.motivo
    assert "bandeira do cartão" in r.motivo


def test_motivo_falha_llm_com_muitas_pendencias_resume() -> None:
    r = montar_resumo_estruturado(EstadoAtendimento(), motivo="falha_llm", agora=AGORA)
    assert "Novo contato" in r.motivo
    assert "e mais" in r.motivo
    assert len(r.pendencias) > 3  # a lista completa continua no resumo


def test_motivo_falha_llm_sem_pendencias() -> None:
    r = montar_resumo_estruturado(_estado_rico(), motivo="falha_llm", agora=AGORA)
    if not r.pendencias:
        assert "ficha estava completa" in r.motivo


def test_de_dict_aceita_resumo_antigo_sem_os_campos_novos() -> None:
    antigo = {
        "motivo": "A IA ficou indisponível e passou a conversa para o vendedor",
        "aparelho_desejado": "iPhone 16 128GB",
        "troca": "iPhone 13 128GB",
        "valor_troca": "1200.00",
        "proposta": None,
        "valor_proposta": None,
        "forma_pagamento": None,
        "data_prevista": "2026-11-25",
        "pendencias": ["bandeira do cartão"],
        "observacoes": None,
        "gerado_em": "2026-11-20T15:00:00+00:00",
    }
    r = ResumoHandoff.de_dict(antigo)
    assert r.motivo.startswith("A IA ficou indisponível")
    assert r.cor is None and r.sku is None and r.troca_condicao is None
    assert r.valor_aparelho is None and r.desconto is None and r.parcelas is None
    assert r.ultimas_mensagens_cliente == []


def test_resumo_novo_dict_ida_e_volta() -> None:
    r = montar_resumo_estruturado(
        _estado_rico(),
        motivo="falha_llm",
        agora=AGORA,
        mensagens=[_msg("cliente", "quero fechar")],
    )
    assert ResumoHandoff.de_dict(r.para_dict()) == r


# --- acordo fechado pela IA (#74) ---------------------------------------------------------------


def _acordo() -> dict[str, object]:
    return {
        "fechado_em": "2026-11-20T14:30:00+00:00",
        "aparelho": {"sku": "IP16-128-PT", "modelo": "iPhone 16", "cor": "Preto"},
        "preco_aparelho": "R$ 4.830,00",
        "troca": {
            "status": "avaliada",
            "valor": "R$ 1.200,00",
            "aparelho_usado": "iPhone 13 128GB",
        },
        "desconto": {"negociado": "R$ 100,00", "total": "R$ 130,00"},
        "desconto_liberado": "R$ 100,00",
        "forma_escolhida": {
            "rotulo": "Cartão de crédito em 12x Mastercard",
            "parcelas": 12,
            "valor_parcela": "R$ 325,00",
            "total_pago": "R$ 3.900,00",
        },
        "pagamento": {"tipo": "credito", "parcelas": 12, "bandeira": "mastercard", "entrada": None},
        "data_prevista": "2026-11-25",
        "informado": {
            "endereco": "Rua das Palmeiras, 123",
            "horarios": "seg: 09:00-18:00; sab: 09:00-14:00",
            "chave_pix": {"tipo": "email", "chave": "pix@loja.exemplo", "favorecido": "Loja Demo"},
        },
    }


def test_resumo_sem_acordo_nao_tem_o_bloco() -> None:
    r = montar_resumo_estruturado(_estado_rico(), motivo="x", agora=AGORA)
    assert r.acordo is None


def test_resumo_traz_o_acordo_completo() -> None:
    estado = replace(_estado_rico(), acordo=_acordo())
    r = montar_resumo_estruturado(estado, motivo="acordo_fechado", agora=AGORA)
    a = r.acordo
    assert a is not None
    assert a.fechado_em == datetime(2026, 11, 20, 14, 30, tzinfo=UTC)
    assert a.forma == "Cartão de crédito em 12x Mastercard"
    assert a.valor_total == Decimal("3900.00")
    assert a.data_prevista == date(2026, 11, 25)
    assert a.endereco == "Rua das Palmeiras, 123"
    assert a.horarios == "seg: 09:00-18:00; sab: 09:00-14:00"
    assert a.pix_chave == "pix@loja.exemplo"
    assert a.pix_favorecido == "Loja Demo"


def test_acordo_sem_chave_pix_no_resumo() -> None:
    dados = _acordo()
    dados["informado"] = {"endereco": "Rua A", "horarios": "seg: 09:00-18:00", "chave_pix": None}
    r = montar_resumo_estruturado(
        replace(_estado_rico(), acordo=dados), motivo="acordo_fechado", agora=AGORA
    )
    assert r.acordo is not None
    assert r.acordo.pix_chave is None and r.acordo.pix_favorecido is None


def test_motivo_acordo_fechado_e_legivel() -> None:
    estado = replace(_estado_rico(), acordo=_acordo())
    r = montar_resumo_estruturado(estado, motivo="acordo_fechado", agora=AGORA)
    assert r.motivo == (
        "Acordo fechado pela IA: cliente vai à loja em 25/11/2026 para concluir; "
        "confira os detalhes abaixo."
    )


def test_motivo_acordo_fechado_sem_data_no_acordo() -> None:
    dados = _acordo()
    dados["data_prevista"] = None
    estado = replace(_estado_rico(), acordo=dados)
    estado = replace(estado, ficha=estado.ficha.com(data_prevista_compra=None))
    r = montar_resumo_estruturado(estado, motivo="acordo_fechado", agora=AGORA)
    assert r.motivo.startswith("Acordo fechado pela IA: cliente vai à loja para concluir")


def test_motivo_acordo_fechado_sem_acordo_no_estado_passa_direto() -> None:
    # o codigo nao inventa um acordo que nao existe
    r = montar_resumo_estruturado(_estado_rico(), motivo="acordo_fechado", agora=AGORA)
    assert "Acordo fechado pela IA" not in r.motivo


def test_resumo_com_acordo_dict_ida_e_volta() -> None:
    estado = replace(_estado_rico(), acordo=_acordo())
    r = montar_resumo_estruturado(estado, motivo="acordo_fechado", agora=AGORA)
    volta = ResumoHandoff.de_dict(json.loads(json.dumps(r.para_dict())))
    assert volta == r
    assert volta.acordo is not None


def test_resumo_antigo_sem_acordo_continua_valido() -> None:
    r = montar_resumo_estruturado(_estado_rico(), motivo="x", agora=AGORA)
    dados = r.para_dict()
    dados.pop("acordo")
    assert ResumoHandoff.de_dict(dados).acordo is None


def _estado_com_aparelho(aparelho: dict[str, object]) -> EstadoAtendimento:
    return replace(
        _estado_rico(),
        ultima_proposta={
            "aparelho": aparelho,
            "preco_aparelho": "1999.00",
            "troca": {"status": "avaliada", "valor": "500.00"},
            "forma_escolhida": {"rotulo": "Pix ou dinheiro à vista", "valor_a_vista": "1499.00"},
        },
    )


def test_resumo_seminovo_sem_bateria_manda_confirmar_na_loja() -> None:
    estado = _estado_com_aparelho(
        {"modelo": "iPhone 16", "condicao": "seminovo", "bateria_pct": None}
    )
    r = montar_resumo_estruturado(estado, motivo="x", agora=AGORA)
    assert r.aparelho_desejado == "iPhone 16 128GB (bateria não cadastrada — confirmar na loja)"


def test_resumo_seminovo_com_bateria_e_novo_nao_trazem_o_aviso() -> None:
    for aparelho in (
        {"modelo": "iPhone 16", "condicao": "seminovo", "bateria_pct": 91},
        {"modelo": "iPhone 16", "condicao": "novo"},
        {"modelo": "iPhone 16", "condicao": "seminovo"},  # proposta antiga, sem o campo
    ):
        r = montar_resumo_estruturado(_estado_com_aparelho(aparelho), motivo="x", agora=AGORA)
        assert r.aparelho_desejado == "iPhone 16 128GB"


def test_motivo_negociacao_resume_o_pedido_o_liberado_e_o_teto() -> None:
    negociacao = {
        "motivo": "acima_do_teto",
        "pedido": "mais_desconto",
        "texto": "quer mais um pouco",
        "liberado": "R$ 100,00",
        "teto": "R$ 100,00",
    }
    estado = replace(_estado_rico(), negociacao=negociacao)
    r = montar_resumo_estruturado(estado, motivo="negociacao", agora=AGORA)
    assert r.motivo.startswith("Negociação: o cliente pediu mais desconto (quer mais um pouco)")
    assert "R$ 100,00" in r.motivo and "teto" in r.motivo


def test_motivo_negociacao_sem_dados_no_estado_passa_direto() -> None:
    r = montar_resumo_estruturado(_estado_rico(), motivo="negociacao", agora=AGORA)
    assert r.motivo == "negociacao"
