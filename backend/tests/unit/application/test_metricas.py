"""Caso de uso `MetricasAgente`: KPIs, variacao vs. periodo anterior, series e custo."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.config.modelos import ErrosDeValidacao, LojaNaoEncontrada
from app.application.metricas import (
    CelulaHorario,
    ContagemPorTipo,
    DiaBruto,
    Latencia,
    MetricasAgente,
    ModeloProcurado,
    TotaisPeriodo,
    UsoFerramenta,
    UsoModelo,
)
from app.domain.metricas import Periodo

SONNET = "claude-sonnet-5-5"
LOJA = uuid4()


class LojasFalso:
    def __init__(self, existe: bool = True) -> None:
        self._existe = existe

    async def criar(self, nome: str) -> UUID:
        raise NotImplementedError

    async def existe(self, loja_id: UUID) -> bool:
        return self._existe


class LeitorFalso:
    def __init__(
        self,
        totais: dict[Periodo, TotaisPeriodo] | None = None,
        dias: dict[Periodo, list[DiaBruto]] | None = None,
    ) -> None:
        self._totais = totais or {}
        self._dias = dias or {}
        self.consultas: list[Periodo] = []

    async def totais(self, loja_id: UUID, periodo: Periodo) -> TotaisPeriodo:
        self.consultas.append(periodo)
        return self._totais.get(periodo, TotaisPeriodo())

    async def dias(self, loja_id: UUID, periodo: Periodo) -> Sequence[DiaBruto]:
        return self._dias.get(periodo, [])


def _caso(
    leitor: LeitorFalso, *, existe: bool = True, hoje: date = date(2026, 11, 22)
) -> MetricasAgente:
    return MetricasAgente(LojasFalso(existe), leitor, hoje=lambda: hoje)


def _uso(modelo: str = SONNET, e: int = 0, s: int = 0, cl: int = 0, ce: int = 0) -> UsoModelo:
    return UsoModelo(modelo, e, s, cl, ce, chamadas=1)


ATUAL = Periodo(date(2026, 11, 8), date(2026, 11, 14))
ANTERIOR = Periodo(date(2026, 11, 1), date(2026, 11, 7))


async def test_loja_inexistente() -> None:
    with pytest.raises(LojaNaoEncontrada):
        await _caso(LeitorFalso(), existe=False).executar(LOJA, None, None)


async def test_padrao_sao_os_ultimos_30_dias_ate_hoje() -> None:
    leitor = LeitorFalso()
    r = await _caso(leitor).executar(LOJA, None, None)
    assert (r.periodo.de, r.periodo.ate) == (date(2026, 10, 24), date(2026, 11, 22))
    assert r.periodo.dias == 30
    assert r.periodo_anterior == Periodo(date(2026, 9, 24), date(2026, 10, 23))
    assert leitor.consultas == [r.periodo, r.periodo_anterior]


async def test_so_o_ate_informado_conta_30_dias_para_tras() -> None:
    r = await _caso(LeitorFalso()).executar(LOJA, None, date(2026, 11, 10))
    assert (r.periodo.de, r.periodo.ate) == (date(2026, 10, 12), date(2026, 11, 10))


async def test_so_o_de_informado_vai_ate_hoje() -> None:
    r = await _caso(LeitorFalso()).executar(LOJA, date(2026, 11, 15), None)
    assert (r.periodo.de, r.periodo.ate) == (date(2026, 11, 15), date(2026, 11, 22))


@pytest.mark.parametrize(
    ("de", "ate", "campo"),
    [
        (date(2026, 11, 10), date(2026, 11, 9), "de"),
        (date(2024, 1, 1), date(2026, 11, 9), "de"),  # mais de 366 dias
    ],
)
async def test_periodo_invalido_e_recusado(de: date, ate: date, campo: str) -> None:
    with pytest.raises(ErrosDeValidacao) as exc:
        await _caso(LeitorFalso()).executar(LOJA, de, ate)
    assert exc.value.erros[0].caminho == campo


async def test_periodo_sem_dados_devolve_zeros_e_listas_vazias() -> None:
    r = await _caso(LeitorFalso()).executar(LOJA, ATUAL.de, ATUAL.ate)
    k = r.kpis
    assert k.conversas_ativas.valor == 0
    assert k.mensagens_recebidas.valor == 0
    assert k.acordos_fechados.valor == 0
    assert k.custo_total_usd.valor == Decimal(0)
    assert k.tokens_total.valor == 0
    # sem denominador nao ha razao: None, nao zero
    assert k.mensagens_por_conversa.valor is None
    assert k.taxa_conversao.valor is None
    assert k.taxa_handoff.valor is None
    assert k.taxa_cache.valor is None
    assert k.custo_por_conversa_usd.valor is None
    assert k.custo_por_acordo_usd.valor is None
    # sem amostra: latencia nula (nunca zero)
    assert k.latencia_llm_media_ms.valor is None
    assert k.latencia_llm_p95_ms.valor is None
    assert k.tempo_resposta_p95_ms.valor is None
    assert k.conversas_ativas.variacao_pct == Decimal("0.0")
    assert r.custo.total_usd == Decimal(0)
    assert r.custo.completo is True
    assert r.custo.por_modelo == ()
    assert r.ferramentas == ()
    assert r.modelos_procurados == ()
    assert r.mapa_horario == ()
    assert r.erros.total == 0
    assert r.erros.llm_por_tipo == ()
    # funil e motivos de handoff sao fixos (todos com zero); a serie tem todos os dias
    assert [e.leads for e in r.funil] == [0, 0, 0, 0, 0]
    assert [h.quantidade for h in r.handoffs] == [0, 0, 0, 0]
    assert [p.dia for p in r.series] == ATUAL.listar_dias()
    assert all(p.conversas_novas == 0 and p.custo_usd == Decimal(0) for p in r.series)
    assert all(p.latencia_llm_media_ms is None for p in r.series)


async def test_kpis_e_variacao_contra_o_periodo_anterior() -> None:
    atual = TotaisPeriodo(
        conversas_novas=12,
        conversas_ativas=10,
        mensagens_recebidas=60,
        mensagens_enviadas=70,
        mensagens_enviadas_ia=65,
        leads_com_handoff=4,
        acordos_fechados=2,
        uso_por_modelo=(_uso(e=1_000_000, s=100_000, cl=2_000_000, ce=400_000),),  # US$ 4,20
        latencia_llm=Latencia(Decimal(900), Decimal(2000), 8),
        tempo_resposta=Latencia(Decimal(4000), Decimal(9000), 8),
    )
    anterior = TotaisPeriodo(conversas_ativas=5, acordos_fechados=2, mensagens_recebidas=0)
    leitor = LeitorFalso({ATUAL: atual, ANTERIOR: anterior})
    r = await _caso(leitor).executar(LOJA, ATUAL.de, ATUAL.ate)
    k = r.kpis

    assert k.conversas_ativas.valor == 10
    assert k.conversas_ativas.anterior == 5
    assert k.conversas_ativas.variacao_pct == Decimal("100.0")
    assert k.acordos_fechados.variacao_pct == Decimal("0.0")
    assert k.mensagens_recebidas.variacao_pct is None  # anterior zerado
    assert k.mensagens_por_conversa.valor == Decimal("13")  # (60 + 70) / 10
    assert k.taxa_conversao.valor == Decimal("0.2")  # 2 acordos / 10 conversas ativas
    assert k.taxa_handoff.valor == Decimal("0.4")
    assert k.latencia_llm_media_ms.valor == Decimal(900)
    assert k.latencia_llm_p95_ms.valor == Decimal(2000)
    assert k.tempo_resposta_media_ms.valor == Decimal(4000)
    assert k.tempo_resposta_p95_ms.valor == Decimal(9000)
    assert k.latencia_llm_media_ms.anterior is None
    # custo e razoes de custo
    assert k.custo_total_usd.valor == Decimal("4.20")
    assert k.custo_por_conversa_usd.valor == Decimal("0.42")
    assert k.custo_por_acordo_usd.valor == Decimal("2.10")
    assert k.tokens_total.valor == 3_500_000
    # 2.000.000 lidos / (1.000.000 + 2.000.000 + 400.000)
    assert k.taxa_cache.valor == Decimal(2_000_000) / Decimal(3_400_000)


async def test_custo_por_modelo_marca_modelo_sem_preco_sem_inventar() -> None:
    totais = TotaisPeriodo(
        conversas_ativas=1,
        uso_por_modelo=(
            _uso(SONNET, e=1_000_000),  # 2,00
            _uso("modelo-x", e=5_000_000, s=1_000),
        ),
    )
    r = await _caso(LeitorFalso({ATUAL: totais})).executar(LOJA, ATUAL.de, ATUAL.ate)
    assert r.custo.completo is False
    assert r.custo.modelos_sem_preco == ("modelo-x",)
    assert r.custo.total_usd == Decimal("2.00")  # so o que tem preco
    por_modelo = {m.modelo: m for m in r.custo.por_modelo}
    assert por_modelo[SONNET].custo_usd == Decimal("2.00")
    assert por_modelo["modelo-x"].custo_usd is None
    assert por_modelo["modelo-x"].entrada == 5_000_000


async def test_funil_segue_a_ordem_do_kanban_com_zeros_e_o_periodo_anterior() -> None:
    atual = TotaisPeriodo(leads_por_etapa={"venda_fechada": 2, "novo_contato": 5})
    anterior = TotaisPeriodo(leads_por_etapa={"novo_contato": 3})
    r = await _caso(LeitorFalso({ATUAL: atual, ANTERIOR: anterior})).executar(
        LOJA, ATUAL.de, ATUAL.ate
    )
    assert [(e.etapa, e.leads, e.leads_anterior) for e in r.funil] == [
        ("novo_contato", 5, 3),
        ("interesse_identificado", 0, 0),
        ("interesse_qualificado", 0, 0),
        ("com_o_vendedor", 0, 0),
        ("venda_fechada", 2, 0),
    ]
    assert r.funil[0].nome == "Novo contato"


async def test_handoffs_agrupados_por_categoria() -> None:
    atual = TotaisPeriodo(
        handoffs_por_motivo={
            "acordo_fechado": 3,
            "falha_llm": 1,
            "Cliente pediu para falar com um atendente": 2,
            "O cliente quer falar com uma pessoa": 1,
            "Desconto acima do teto": 4,
        },
        leads_com_handoff=10,
    )
    r = await _caso(LeitorFalso({ATUAL: atual})).executar(LOJA, ATUAL.de, ATUAL.ate)
    assert [(h.motivo, h.quantidade) for h in r.handoffs] == [
        ("pedido_cliente", 3),
        ("acordo_fechado", 3),
        ("falha_tecnica", 1),
        ("outros", 4),
    ]
    assert r.handoffs[0].nome == "Pedido do cliente"
    assert r.total_handoffs == 11


async def test_erros_somam_llm_ferramentas_limite_e_descartes() -> None:
    atual = TotaisPeriodo(
        erros_llm_por_tipo=(ContagemPorTipo("RateLimit", 2), ContagemPorTipo("Timeout", 1)),
        ferramentas=(
            UsoFerramenta("consultar_estoque", 10, 1),
            UsoFerramenta("registrar_usado", 4, 2),
        ),
        limite_iteracoes=1,
        respostas_descartadas=2,
    )
    r = await _caso(LeitorFalso({ATUAL: atual})).executar(LOJA, ATUAL.de, ATUAL.ate)
    assert r.erros.llm == 3
    assert r.erros.ferramentas == 3
    assert r.erros.limite_iteracoes == 1
    assert r.erros.respostas_descartadas == 2
    assert r.erros.total == 9
    assert r.kpis.erros.valor == 9
    assert r.kpis.respostas_descartadas.valor == 2
    assert r.erros.llm_por_tipo[0].tipo == "RateLimit"
    assert [f.nome for f in r.ferramentas] == ["consultar_estoque", "registrar_usado"]


async def test_series_diarias_incluem_todos_os_dias_com_zeros_e_custo_por_dia() -> None:
    dias = [
        DiaBruto(
            dia=date(2026, 11, 9),
            conversas_novas=2,
            conversas_ativas=3,
            mensagens_recebidas=10,
            uso_por_modelo=(_uso(e=1_000_000),),
            latencia_llm=Latencia(Decimal(800), Decimal(1500), 4),
            tempo_resposta=Latencia(Decimal(3000), Decimal(7000), 4),
            erros=1,
        ),
        DiaBruto(dia=date(2026, 11, 12), conversas_novas=1, erros=0),
    ]
    r = await _caso(LeitorFalso(dias={ATUAL: dias})).executar(LOJA, ATUAL.de, ATUAL.ate)
    assert [p.dia for p in r.series] == ATUAL.listar_dias()
    por_dia = {p.dia: p for p in r.series}
    d9 = por_dia[date(2026, 11, 9)]
    assert (d9.conversas_novas, d9.conversas_ativas, d9.mensagens_recebidas) == (2, 3, 10)
    assert d9.custo_usd == Decimal("2.00")
    assert d9.tokens == 1_000_000
    assert d9.latencia_llm_media_ms == Decimal(800)
    assert d9.latencia_llm_p95_ms == Decimal(1500)
    assert d9.tempo_resposta_media_ms == Decimal(3000)
    assert d9.tempo_resposta_p95_ms == Decimal(7000)
    assert d9.erros == 1
    vazio = por_dia[date(2026, 11, 10)]
    assert (vazio.conversas_novas, vazio.tokens, vazio.erros) == (0, 0, 0)
    assert vazio.custo_usd == Decimal(0)
    assert vazio.latencia_llm_media_ms is None
    assert por_dia[date(2026, 11, 12)].conversas_novas == 1


async def test_rankings_e_mapa_horario_passam_do_leitor() -> None:
    atual = TotaisPeriodo(
        modelos_procurados=(ModeloProcurado("iPhone 15", 4),),
        mapa_horario=(CelulaHorario(dia_semana=0, hora=9, mensagens=7),),
    )
    r = await _caso(LeitorFalso({ATUAL: atual})).executar(LOJA, ATUAL.de, ATUAL.ate)
    assert r.modelos_procurados == (ModeloProcurado("iPhone 15", 4),)
    assert r.mapa_horario == (CelulaHorario(0, 9, 7),)
