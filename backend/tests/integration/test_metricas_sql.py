"""`LeitorMetricasSql` com eventos, leads e mensagens SINTETICOS (banco Postgres isolado)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.outbound.db.metricas import LeitorMetricasSql
from app.adapters.outbound.db.models import Conversa, Evento, Lead, Loja, Mensagem
from app.application.metricas import CelulaHorario
from app.domain.metricas import Periodo
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

ATUAL = Periodo(date(2026, 11, 8), date(2026, 11, 14))  # segunda 9/11 = dia_semana 0
ANTERIOR = Periodo(date(2026, 11, 1), date(2026, 11, 7))
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def _z(texto: str) -> datetime:
    """`2026-11-09T12:05` em UTC."""
    return datetime.fromisoformat(texto).replace(tzinfo=UTC)


class Cenario:
    """Dados sinteticos de uma loja; o que fica fora do periodo prova o recorte."""

    def __init__(self, s: AsyncSession) -> None:
        self.s = s
        self.loja_id = uuid.uuid4()
        self.leads: dict[str, uuid.UUID] = {}
        self.conversas: dict[str, uuid.UUID] = {}

    async def preparar(self) -> None:
        self.s.add(Loja(id=self.loja_id, nome="Loja metricas"))
        await self.s.flush()

    async def lead(self, nome: str, criado: str, etapa: str) -> None:
        lead = Lead(
            loja_id=self.loja_id,
            nome=nome,
            telefone=f"t-{nome}",
            canal="webchat",
            etapa=etapa,
            criado_em=_z(criado),
        )
        self.s.add(lead)
        await self.s.flush()
        conversa = Conversa(loja_id=self.loja_id, lead_id=lead.id, canal="webchat")
        self.s.add(conversa)
        await self.s.flush()
        self.leads[nome], self.conversas[nome] = lead.id, conversa.id

    async def msg(self, lead: str, direcao: str, quando: str, autor: str | None = None) -> None:
        self.s.add(
            Mensagem(
                loja_id=self.loja_id,
                conversa_id=self.conversas[lead],
                canal="webchat",
                direcao=direcao,
                autor=autor or ("cliente" if direcao == "entrada" else "ia"),
                conteudo="oi",
                criado_em=_z(quando),
            )
        )

    async def evento(
        self, tipo: str, quando: str, payload: dict[str, Any], lead: str | None = None
    ) -> None:
        self.s.add(
            Evento(
                loja_id=self.loja_id,
                lead_id=None if lead is None else self.leads[lead],
                tipo=tipo,
                payload=payload,
                criado_em=_z(quando),
            )
        )


def _uso(modelo: str, e: int, s: int, cl: int, ce: int, **latencias: int) -> dict[str, Any]:
    return {
        "modelo": modelo,
        "entrada": e,
        "saida": s,
        "cache_leitura": cl,
        "cache_escrita": ce,
        "chamadas": 1,
        **latencias,
    }


def _ferramenta(nome: str, entrada: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"nome": nome, "entrada": entrada, "resultado_resumido": "ok", **extra}


async def _popular(c: Cenario) -> None:
    await c.preparar()
    # --- leads (criado_em em UTC; o recorte e o dia em Sao Paulo, UTC-3) ---
    await c.lead("L1", "2026-11-09T12:00", "com_o_vendedor")
    await c.lead("L2", "2026-11-10T02:30", "novo_contato")  # 9/11 23:30 em SP: dentro
    await c.lead("L3", "2026-11-15T02:00", "venda_fechada")  # 14/11 23:00 em SP: dentro
    await c.lead("L4", "2026-11-15T03:00", "novo_contato")  # 15/11 00:00 em SP: fora
    await c.lead("L5", "2026-11-03T15:00", "interesse_qualificado")  # periodo anterior
    # --- mensagens ---
    await c.msg("L1", "entrada", "2026-11-09T12:05")  # seg 09:05
    await c.msg("L1", "saida", "2026-11-09T12:06")
    await c.msg("L1", "entrada", "2026-11-09T12:10")  # seg 09:10
    await c.msg("L1", "saida", "2026-11-10T15:00", autor="vendedor")
    await c.msg("L2", "entrada", "2026-11-10T02:40")  # seg 23:40 em SP
    await c.msg("L4", "entrada", "2026-11-15T03:30")  # fora do periodo
    await c.msg("L5", "entrada", "2026-11-03T15:00")  # periodo anterior
    # --- llm_uso (os antigos nao tem latencia) ---
    await c.evento(
        "llm_uso",
        "2026-11-09T12:06",
        _uso(
            SONNET,
            1000,
            100,
            5000,
            500,
            latencia_llm_ms=1000,
            latencia_rodada_ms=1500,
            tempo_resposta_ms=3000,
        ),
        "L1",
    )
    await c.evento(
        "llm_uso",
        "2026-11-09T12:11",
        _uso(
            HAIKU,
            200,
            20,
            0,
            0,
            latencia_llm_ms=3000,
            latencia_rodada_ms=2500,
            tempo_resposta_ms=5000,
        ),
        "L1",
    )
    await c.evento("llm_uso", "2026-11-10T02:50", _uso(SONNET, 100, 10, 0, 0), "L2")  # sem latencia
    await c.evento("llm_uso", "2026-11-11T10:00", _uso("modelo-x", 50, 5, 0, 0), "L1")
    await c.evento("llm_uso", "2026-11-16T10:00", _uso(SONNET, 9999, 9999, 0, 0), "L1")  # fora
    await c.evento("llm_uso", "2026-11-03T15:05", _uso(SONNET, 2000, 0, 0, 0), "L5")  # anterior
    # --- erros ---
    await c.evento("erro_llm", "2026-11-09T12:00", {"tipo": "RateLimit", "status": 429}, "L1")
    await c.evento("erro_llm", "2026-11-09T13:00", {"tipo": "RateLimit"}, "L1")
    await c.evento("erro_llm", "2026-11-10T13:00", {"tipo": "Timeout", "modelo": SONNET}, "L2")
    await c.evento("erro_llm", "2026-11-16T13:00", {"tipo": "Timeout"}, "L2")  # fora
    await c.evento("limite_iteracoes", "2026-11-12T13:00", {"max_iteracoes": 8}, "L1")
    await c.evento("resposta_descartada", "2026-11-12T14:00", {"motivo": "x"}, "L1")
    await c.evento("resposta_descartada", "2026-11-13T14:00", {"motivo": "x"}, "L1")
    # --- ferramentas ---
    await c.evento(
        "ferramenta",
        "2026-11-09T12:07",
        _ferramenta("consultar_estoque", {"modelo": "iPhone 15"}, erro=False),
        "L1",
    )
    await c.evento(
        "ferramenta",
        "2026-11-09T12:08",
        _ferramenta("consultar_estoque", {"modelo": "iPhone 15"}, erro=True),
        "L1",
    )
    await c.evento(
        "ferramenta",
        "2026-11-10T02:45",
        _ferramenta("consultar_estoque", {"modelo": "iphone 15 "}, erro=False),
        "L2",
    )
    await c.evento(
        "ferramenta",
        "2026-11-09T12:09",
        _ferramenta("registrar_interesse", {"modelo": "iPhone 14"}, erro=False),
        "L1",
    )
    await c.evento(
        "ferramenta",
        "2026-11-09T12:09",
        _ferramenta("registrar_usado", {"modelo": "iPhone 11"}),
        "L1",
    )  # antigo: sem `erro`
    await c.evento(
        "ferramenta",
        "2026-11-09T12:09",
        _ferramenta("chamar_vendedor", {"motivo": "x"}, erro=False),
        "L1",
    )
    # diagnostico da #76 (traceback) acompanha o `ferramenta` com erro: nao pode contar de novo
    await c.evento(
        "ferramenta_erro", "2026-11-09T12:08", {"nome": "consultar_estoque", "traceback": "x"}, "L1"
    )
    # --- handoffs: dono_mudou com `motivo` (chamar_vendedor); sem motivo nao e handoff ---
    await c.evento(
        "dono_mudou",
        "2026-11-09T12:20",
        {"dono": "vendedor", "vendedor_id": None, "motivo": "acordo_fechado"},
        "L1",
    )
    await c.evento(
        "dono_mudou",
        "2026-11-10T13:10",
        {"dono": "vendedor", "vendedor_id": None, "motivo": "falha_llm"},
        "L2",
    )
    await c.evento(
        "dono_mudou",
        "2026-11-12T10:00",
        {"dono": "vendedor", "vendedor_id": None, "motivo": "Cliente pediu atendente"},
        "L3",
    )
    await c.evento("dono_mudou", "2026-11-12T11:00", {"dono": "ia"}, "L3")  # devolveu: nao conta
    await c.evento(
        "dono_mudou", "2026-11-12T12:00", {"dono": "vendedor", "origem": "celular_da_loja"}, "L3"
    )
    await c.evento(
        "handoff_resumo",
        "2026-11-09T12:20",
        {"motivo": "Acordo fechado", "acordo": {"forma": "Pix"}},
        "L1",
    )
    await c.evento(
        "handoff_resumo",
        "2026-11-12T10:00",
        {"motivo": "Cliente pediu atendente", "acordo": None},
        "L3",
    )
    await c.evento("handoff", "2026-11-10T13:10", {"motivo": "falha_llm", "erro": "ErroLLM"}, "L2")
    # --- outra loja no mesmo periodo: nunca entra ---
    outra = Cenario(c.s)
    await outra.preparar()
    await outra.lead("X1", "2026-11-09T12:00", "novo_contato")
    await outra.msg("X1", "entrada", "2026-11-09T12:05")
    await outra.evento("llm_uso", "2026-11-09T12:06", _uso(SONNET, 777, 7, 0, 0), "X1")
    await outra.evento("erro_llm", "2026-11-09T12:06", {"tipo": "Outra"}, "X1")


@pytest.fixture
async def cenario(db_url: str) -> AsyncIterator[tuple[Cenario, LeitorMetricasSql, AsyncSession]]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        c = Cenario(s)
        await _popular(c)
        await s.commit()
        yield c, LeitorMetricasSql(s), s
    await engine.dispose()


async def test_conversas_e_mensagens_no_periodo_em_sao_paulo(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert t.conversas_novas == 3  # L1, L2 (23:30 de 9/11 em SP) e L3 (23:00 de 14/11)
    assert t.conversas_ativas == 2  # L1 e L2 trocaram mensagens
    assert t.mensagens_recebidas == 3
    assert t.mensagens_enviadas == 2
    assert t.mensagens_enviadas_ia == 1
    anterior = await leitor.totais(c.loja_id, ANTERIOR)
    assert (anterior.conversas_novas, anterior.conversas_ativas) == (1, 1)
    assert anterior.mensagens_recebidas == 1


async def test_funil_conta_leads_do_periodo_pela_etapa_atual(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert dict(t.leads_por_etapa) == {"com_o_vendedor": 1, "novo_contato": 1, "venda_fechada": 1}


async def test_tokens_por_modelo_e_so_da_loja_e_do_periodo(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    por_modelo = {u.modelo: u for u in t.uso_por_modelo}
    assert set(por_modelo) == {SONNET, HAIKU, "modelo-x"}
    sonnet = por_modelo[SONNET]
    assert (sonnet.entrada, sonnet.saida, sonnet.cache_leitura, sonnet.cache_escrita) == (
        1100,
        110,
        5000,
        500,
    )
    assert sonnet.chamadas == 2
    assert por_modelo[HAIKU].entrada == 200


async def test_latencia_ignora_eventos_antigos_sem_o_campo(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert t.latencia_llm.amostras == 2
    assert t.latencia_llm.media_ms == Decimal(2000)
    assert t.latencia_llm.p95_ms == Decimal(2900)  # percentil continuo de [1000, 3000]
    assert t.latencia_rodada.media_ms == Decimal(2000)
    assert t.tempo_resposta.media_ms == Decimal(4000)
    assert t.tempo_resposta.p95_ms == Decimal(4900)


async def test_latencia_e_nula_sem_nenhum_dado(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ANTERIOR)  # so ha um llm_uso antigo, sem latencia
    assert t.latencia_llm.media_ms is None
    assert t.latencia_llm.p95_ms is None
    assert t.latencia_llm.amostras == 0
    assert t.tempo_resposta.p95_ms is None


async def test_erros_ferramentas_e_atritos(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert {(e.tipo, e.quantidade) for e in t.erros_llm_por_tipo} == {
        ("RateLimit", 2),
        ("Timeout", 1),
    }
    assert t.erros_llm_por_tipo[0].tipo == "RateLimit"  # ordenado por quantidade
    assert t.limite_iteracoes == 1
    assert t.respostas_descartadas == 2
    uso = {f.nome: (f.execucoes, f.erros) for f in t.ferramentas}
    assert uso["consultar_estoque"] == (3, 1)
    assert uso["registrar_usado"] == (1, 0)  # evento antigo sem `erro`
    assert [f.nome for f in t.ferramentas][0] == "consultar_estoque"  # mais usada primeiro


async def test_modelos_mais_procurados_contam_leads_sem_diferenciar_caixa(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert [(m.modelo, m.leads) for m in t.modelos_procurados] == [
        ("iPhone 15", 2),  # L1 (duas consultas = 1 lead) e L2
        ("iPhone 14", 1),
    ]


async def test_handoffs_acordos_e_motivos(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert dict(t.handoffs_por_motivo) == {
        "acordo_fechado": 1,
        "falha_llm": 1,
        "Cliente pediu atendente": 1,
    }
    assert t.leads_com_handoff == 3
    assert t.acordos_fechados == 1  # so o resumo com acordo (objeto); `acordo: null` nao conta


async def test_mapa_de_mensagens_recebidas_por_dia_da_semana_e_hora(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    t = await leitor.totais(c.loja_id, ATUAL)
    assert set(t.mapa_horario) == {
        CelulaHorario(dia_semana=0, hora=9, mensagens=2),
        CelulaHorario(dia_semana=0, hora=23, mensagens=1),  # 02:40 UTC de terca = seg 23:40
    }


async def test_series_diarias_no_fuso_de_sao_paulo(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    dias = {d.dia: d for d in await leitor.dias(c.loja_id, ATUAL)}
    assert set(dias) == {
        date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12),
        date(2026, 11, 13), date(2026, 11, 14),
    }  # fmt: skip
    d9 = dias[date(2026, 11, 9)]
    assert d9.conversas_novas == 2  # L1 e L2 (23:30 em SP)
    assert d9.conversas_ativas == 2
    assert d9.mensagens_recebidas == 3
    assert {u.modelo for u in d9.uso_por_modelo} == {SONNET, HAIKU}
    assert next(u for u in d9.uso_por_modelo if u.modelo == SONNET).entrada == 1100
    assert d9.latencia_llm.media_ms == Decimal(2000)
    assert d9.tempo_resposta.p95_ms == Decimal(4900)
    assert d9.erros == 2 + 1  # dois RateLimit + a ferramenta com erro
    d10 = dias[date(2026, 11, 10)]
    assert d10.conversas_novas == 0
    assert d10.conversas_ativas == 1  # a mensagem do vendedor
    assert d10.erros == 1  # Timeout
    assert d10.latencia_llm.media_ms is None
    assert dias[date(2026, 11, 12)].erros == 2  # limite_iteracoes + 1 descarte
    assert dias[date(2026, 11, 14)].conversas_novas == 1  # L3, 23:00 em SP


async def test_periodo_sem_dados_nao_quebra(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, _ = cenario
    vazio = Periodo(date(2026, 1, 1), date(2026, 1, 7))
    t = await leitor.totais(c.loja_id, vazio)
    assert (t.conversas_novas, t.conversas_ativas, t.mensagens_recebidas) == (0, 0, 0)
    assert t.uso_por_modelo == () and t.ferramentas == () and t.mapa_horario == ()
    assert t.latencia_llm.media_ms is None
    assert list(await leitor.dias(c.loja_id, vazio)) == []


async def test_latencia_parcial_e_ferramenta_erro_nao_conta(cenario) -> None:  # type: ignore[no-untyped-def]
    c, leitor, s = cenario
    # rodada com resposta descartada: tem as duas primeiras latencias e nao tem `tempo_resposta_ms`
    await c.evento(
        "llm_uso", "2026-12-02T12:00",
        _uso(SONNET, 1, 1, 0, 0, latencia_llm_ms=700, latencia_rodada_ms=900), "L1",
    )  # fmt: skip
    # sem relogio (evals): nenhuma das tres
    await c.evento("llm_uso", "2026-12-03T12:00", _uso(SONNET, 1, 1, 0, 0), "L1")
    await s.commit()
    periodo = Periodo(date(2026, 12, 1), date(2026, 12, 7))
    t = await leitor.totais(c.loja_id, periodo)
    assert (t.latencia_llm.amostras, t.latencia_llm.media_ms) == (1, Decimal(700))
    assert t.latencia_rodada.media_ms == Decimal(900)
    assert t.tempo_resposta.amostras == 0 and t.tempo_resposta.media_ms is None
    assert t.uso_por_modelo[0].chamadas == 2
    # `ferramenta_erro` (cenario principal) fica fora de erros e de ferramentas
    principal = await leitor.totais(c.loja_id, ATUAL)
    assert "ferramenta_erro" not in {f.nome for f in principal.ferramentas}
    assert sum(f.erros for f in principal.ferramentas) == 1
