"""Schemas da API de metricas do agente (tela de desempenho da IA do painel)."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from app.application.metricas import (
    CustoModelo,
    ErrosPeriodo,
    Indicador,
    Kpis,
    MetricasResultado,
    PontoDiario,
)
from app.domain.metricas import FUSO_NOME

_QUATRO = Decimal("0.0001")
_SEIS = Decimal("0.000001")
_DOIS = Decimal("0.01")


class IndicadorSchema(BaseModel):
    """Um numero do periodo, o mesmo numero no periodo anterior e a variacao %."""

    valor: float | None
    """`null` quando nao ha base para calcular (ex.: taxa sem conversas, latencia sem amostra)."""
    anterior: float | None
    variacao_pct: float | None
    """(valor - anterior) / anterior x 100, 1 casa; `null` se o anterior for zero e o valor nao."""


class IndicadorUsdSchema(BaseModel):
    """Como `IndicadorSchema`, para US$ (valores `Decimal` como texto, ate 6 casas)."""

    valor: Decimal | None
    anterior: Decimal | None
    variacao_pct: float | None


class PeriodoSchema(BaseModel):
    de: date
    ate: date
    """Inclusivo. Os dias sao os de America/Sao_Paulo."""
    dias: int
    fuso: str
    anterior_de: date
    anterior_ate: date
    """Periodo imediatamente anterior, do mesmo tamanho (base da variacao %)."""


class KpisSchema(BaseModel):
    conversas_novas: IndicadorSchema
    """Leads criados no periodo."""
    conversas_ativas: IndicadorSchema
    """Conversas com ao menos uma mensagem no periodo (base das taxas e do custo por conversa)."""
    mensagens_recebidas: IndicadorSchema
    mensagens_enviadas: IndicadorSchema
    mensagens_por_conversa: IndicadorSchema
    """(recebidas + enviadas) / conversas ativas."""
    handoffs: IndicadorSchema
    """Passagens da IA ao vendedor (a IA chamou o vendedor)."""
    taxa_handoff: IndicadorSchema
    """Leads com handoff / conversas ativas (0 a 1)."""
    acordos_fechados: IndicadorSchema
    """Leads com acordo fechado pela IA (resumo do handoff com acordo)."""
    taxa_conversao: IndicadorSchema
    """Acordos fechados / conversas ativas (0 a 1)."""
    tokens_total: IndicadorSchema
    taxa_cache: IndicadorSchema
    """Parte do prompt servida pelo cache: lido / (entrada + lido + escrito) (0 a 1)."""
    custo_total_usd: IndicadorUsdSchema
    """So modelos com preco cadastrado; ver `custo.completo`."""
    custo_por_conversa_usd: IndicadorUsdSchema
    custo_por_acordo_usd: IndicadorUsdSchema
    latencia_llm_media_ms: IndicadorSchema
    """Soma das chamadas ao LLM por rodada, media."""
    latencia_llm_p95_ms: IndicadorSchema
    tempo_resposta_media_ms: IndicadorSchema
    """Da primeira mensagem do cliente atendida ate a resposta enviada, media."""
    tempo_resposta_p95_ms: IndicadorSchema
    erros: IndicadorSchema
    """Erros do LLM + ferramentas com erro + limite de iteracoes + respostas descartadas."""
    respostas_descartadas: IndicadorSchema


class EtapaFunilSchema(BaseModel):
    etapa: str
    """Valor da etapa do kanban (`novo_contato`...), na ordem do funil."""
    nome: str
    leads: int
    """Leads criados no periodo que estao hoje nesta etapa."""
    leads_anterior: int


class MotivoHandoffSchema(BaseModel):
    motivo: str
    """`pedido_cliente`, `acordo_fechado`, `falha_tecnica` ou `outros`."""
    nome: str
    quantidade: int
    anterior: int


class HandoffsSchema(BaseModel):
    total: int
    por_motivo: list[MotivoHandoffSchema]


class TokensSchema(BaseModel):
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int
    total: int
    chamadas: int


class CustoModeloSchema(BaseModel):
    modelo: str
    custo_usd: Decimal | None
    """`null`: modelo sem preco cadastrado (custo nao calculado)."""
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int
    chamadas: int


class CustoSchema(BaseModel):
    total_usd: Decimal
    completo: bool
    """`false` quando algum modelo usado nao tem preco (o total o deixa de fora)."""
    modelos_sem_preco: list[str]
    por_modelo: list[CustoModeloSchema]


class ErroPorTipoSchema(BaseModel):
    tipo: str
    quantidade: int


class ErrosAgenteSchema(BaseModel):
    total: int
    llm: int
    ferramentas: int
    limite_iteracoes: int
    respostas_descartadas: int
    llm_por_tipo: list[ErroPorTipoSchema]


class FerramentaSchema(BaseModel):
    nome: str
    execucoes: int
    erros: int


class ModeloProcuradoSchema(BaseModel):
    modelo: str
    leads: int
    """Leads distintos que perguntaram ou registraram interesse no modelo."""


class CelulaHorarioSchema(BaseModel):
    dia_semana: int
    """0 = segunda ... 6 = domingo (America/Sao_Paulo)."""
    hora: int
    """0 a 23. Mensagens RECEBIDAS do cliente; so as celulas com mensagens vem na lista."""
    mensagens: int


class PontoDiarioSchema(BaseModel):
    dia: date
    conversas_novas: int
    conversas_ativas: int
    mensagens_recebidas: int
    tokens: int
    custo_usd: Decimal
    latencia_llm_media_ms: float | None
    latencia_llm_p95_ms: float | None
    tempo_resposta_media_ms: float | None
    tempo_resposta_p95_ms: float | None
    erros: int


class MetricasSchema(BaseModel):
    periodo: PeriodoSchema
    kpis: KpisSchema
    funil: list[EtapaFunilSchema]
    handoffs: HandoffsSchema
    tokens: TokensSchema
    custo: CustoSchema
    erros: ErrosAgenteSchema
    ferramentas: list[FerramentaSchema]
    """Mais usadas primeiro."""
    modelos_procurados: list[ModeloProcuradoSchema]
    """Top 10, mais procurados primeiro."""
    mapa_horario: list[CelulaHorarioSchema]
    series: list[PontoDiarioSchema] = Field(min_length=1)
    """Um ponto por dia do periodo, em ordem, inclusive os dias sem atividade (zeros)."""


# --- dominio -> schema ------------------------------------------------------------------------


def _float(v: Decimal | None, casas: Decimal = _QUATRO) -> float | None:
    return None if v is None else float(v.quantize(casas, rounding=ROUND_HALF_UP))


def _usd(v: Decimal | None) -> Decimal | None:
    """Ate 6 casas, mas nunca menos que 2 (`2.00`, `0.006007`)."""
    if v is None:
        return None
    q = v.quantize(_SEIS, rounding=ROUND_HALF_UP)
    centavos = q.quantize(_DOIS)
    return centavos if centavos == q else q.normalize()


def _ind(i: Indicador) -> IndicadorSchema:
    return IndicadorSchema(
        valor=_float(i.valor), anterior=_float(i.anterior), variacao_pct=_float(i.variacao_pct)
    )


def _ind_usd(i: Indicador) -> IndicadorUsdSchema:
    return IndicadorUsdSchema(
        valor=_usd(i.valor), anterior=_usd(i.anterior), variacao_pct=_float(i.variacao_pct)
    )


def _kpis(k: Kpis) -> KpisSchema:
    return KpisSchema(
        conversas_novas=_ind(k.conversas_novas),
        conversas_ativas=_ind(k.conversas_ativas),
        mensagens_recebidas=_ind(k.mensagens_recebidas),
        mensagens_enviadas=_ind(k.mensagens_enviadas),
        mensagens_por_conversa=_ind(k.mensagens_por_conversa),
        handoffs=_ind(k.handoffs),
        taxa_handoff=_ind(k.taxa_handoff),
        acordos_fechados=_ind(k.acordos_fechados),
        taxa_conversao=_ind(k.taxa_conversao),
        tokens_total=_ind(k.tokens_total),
        taxa_cache=_ind(k.taxa_cache),
        custo_total_usd=_ind_usd(k.custo_total_usd),
        custo_por_conversa_usd=_ind_usd(k.custo_por_conversa_usd),
        custo_por_acordo_usd=_ind_usd(k.custo_por_acordo_usd),
        latencia_llm_media_ms=_ind(k.latencia_llm_media_ms),
        latencia_llm_p95_ms=_ind(k.latencia_llm_p95_ms),
        tempo_resposta_media_ms=_ind(k.tempo_resposta_media_ms),
        tempo_resposta_p95_ms=_ind(k.tempo_resposta_p95_ms),
        erros=_ind(k.erros),
        respostas_descartadas=_ind(k.respostas_descartadas),
    )


def _custo_modelo(m: CustoModelo) -> CustoModeloSchema:
    return CustoModeloSchema(
        modelo=m.modelo,
        custo_usd=_usd(m.custo_usd),
        entrada=m.entrada,
        saida=m.saida,
        cache_leitura=m.cache_leitura,
        cache_escrita=m.cache_escrita,
        chamadas=m.chamadas,
    )


def _erros(e: ErrosPeriodo) -> ErrosAgenteSchema:
    return ErrosAgenteSchema(
        total=e.total,
        llm=e.llm,
        ferramentas=e.ferramentas,
        limite_iteracoes=e.limite_iteracoes,
        respostas_descartadas=e.respostas_descartadas,
        llm_por_tipo=[
            ErroPorTipoSchema(tipo=t.tipo, quantidade=t.quantidade) for t in e.llm_por_tipo
        ],
    )


def _ponto(p: PontoDiario) -> PontoDiarioSchema:
    return PontoDiarioSchema(
        dia=p.dia,
        conversas_novas=p.conversas_novas,
        conversas_ativas=p.conversas_ativas,
        mensagens_recebidas=p.mensagens_recebidas,
        tokens=p.tokens,
        custo_usd=_usd(p.custo_usd) or Decimal(0),
        latencia_llm_media_ms=_float(p.latencia_llm_media_ms),
        latencia_llm_p95_ms=_float(p.latencia_llm_p95_ms),
        tempo_resposta_media_ms=_float(p.tempo_resposta_media_ms),
        tempo_resposta_p95_ms=_float(p.tempo_resposta_p95_ms),
        erros=p.erros,
    )


def metricas_para_schema(r: MetricasResultado) -> MetricasSchema:
    return MetricasSchema(
        periodo=PeriodoSchema(
            de=r.periodo.de,
            ate=r.periodo.ate,
            dias=r.periodo.dias,
            fuso=FUSO_NOME,
            anterior_de=r.periodo_anterior.de,
            anterior_ate=r.periodo_anterior.ate,
        ),
        kpis=_kpis(r.kpis),
        funil=[
            EtapaFunilSchema(
                etapa=e.etapa, nome=e.nome, leads=e.leads, leads_anterior=e.leads_anterior
            )
            for e in r.funil
        ],
        handoffs=HandoffsSchema(
            total=r.total_handoffs,
            por_motivo=[
                MotivoHandoffSchema(
                    motivo=h.motivo, nome=h.nome, quantidade=h.quantidade, anterior=h.anterior
                )
                for h in r.handoffs
            ],
        ),
        tokens=TokensSchema(
            entrada=r.tokens.entrada,
            saida=r.tokens.saida,
            cache_leitura=r.tokens.cache_leitura,
            cache_escrita=r.tokens.cache_escrita,
            total=r.tokens.total,
            chamadas=r.tokens.chamadas,
        ),
        custo=CustoSchema(
            total_usd=_usd(r.custo.total_usd) or Decimal(0),
            completo=r.custo.completo,
            modelos_sem_preco=list(r.custo.modelos_sem_preco),
            por_modelo=[_custo_modelo(m) for m in r.custo.por_modelo],
        ),
        erros=_erros(r.erros),
        ferramentas=[
            FerramentaSchema(nome=f.nome, execucoes=f.execucoes, erros=f.erros)
            for f in r.ferramentas
        ],
        modelos_procurados=[
            ModeloProcuradoSchema(modelo=m.modelo, leads=m.leads) for m in r.modelos_procurados
        ],
        mapa_horario=[
            CelulaHorarioSchema(dia_semana=c.dia_semana, hora=c.hora, mensagens=c.mensagens)
            for c in r.mapa_horario
        ],
        series=[_ponto(p) for p in r.series],
    )
