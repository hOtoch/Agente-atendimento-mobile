"""Metricas de desempenho do agente num periodo (caso de uso `MetricasAgente`).

A porta `LeitorMetricas` entrega contagens e somas ja agregadas (o SQL fica no adaptador); aqui
o codigo monta os KPIs, a variacao contra o periodo anterior de mesmo tamanho, o custo (tabela de
precos do dominio) e as series diarias completas (todos os dias, inclusive os zerados). Eventos
antigos nao tem os campos de latencia: sem amostra a latencia e `None`, nunca zero.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.application.config.modelos import ErroCampo, ErrosDeValidacao, LojaNaoEncontrada
from app.application.config.portas import RepositorioLojas
from app.domain.kanban import Etapa
from app.domain.metricas import (
    FUSO,
    MotivoHandoff,
    Periodo,
    classificar_motivo_handoff,
    razao,
    taxa_cache,
    variacao_pct,
)
from app.domain.precos import custo_usd

DIAS_PADRAO = 30
LIMITE_DIAS = 366


# --- o que a porta de leitura devolve (bruto, por periodo) -----------------------------------


@dataclass(frozen=True, slots=True)
class UsoModelo:
    """Tokens somados dos eventos `llm_uso` de um modelo."""

    modelo: str
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int
    chamadas: int

    @property
    def tokens(self) -> int:
        return self.entrada + self.saida + self.cache_leitura + self.cache_escrita


@dataclass(frozen=True, slots=True)
class Latencia:
    """Media e p95 (ms) das amostras existentes; `None` quando nenhum evento trouxe o campo."""

    media_ms: Decimal | None = None
    p95_ms: Decimal | None = None
    amostras: int = 0


@dataclass(frozen=True, slots=True)
class ContagemPorTipo:
    tipo: str
    quantidade: int


@dataclass(frozen=True, slots=True)
class UsoFerramenta:
    nome: str
    execucoes: int
    erros: int


@dataclass(frozen=True, slots=True)
class ModeloProcurado:
    modelo: str
    leads: int
    """Leads distintos que consultaram ou registraram interesse no modelo."""


@dataclass(frozen=True, slots=True)
class CelulaHorario:
    """Mensagens recebidas do cliente num dia da semana (0 = segunda) e hora (0-23) locais."""

    dia_semana: int
    hora: int
    mensagens: int


@dataclass(frozen=True, slots=True)
class TotaisPeriodo:
    conversas_novas: int = 0
    conversas_ativas: int = 0
    mensagens_recebidas: int = 0
    mensagens_enviadas: int = 0
    mensagens_enviadas_ia: int = 0
    leads_por_etapa: Mapping[str, int] = field(default_factory=dict)
    handoffs_por_motivo: Mapping[str, int] = field(default_factory=dict)
    """Motivo (como gravado) -> quantidade de passagens da IA ao vendedor."""
    leads_com_handoff: int = 0
    acordos_fechados: int = 0
    uso_por_modelo: tuple[UsoModelo, ...] = ()
    latencia_llm: Latencia = Latencia()
    latencia_rodada: Latencia = Latencia()
    tempo_resposta: Latencia = Latencia()
    erros_llm_por_tipo: tuple[ContagemPorTipo, ...] = ()
    limite_iteracoes: int = 0
    respostas_descartadas: int = 0
    ferramentas: tuple[UsoFerramenta, ...] = ()
    modelos_procurados: tuple[ModeloProcurado, ...] = ()
    mapa_horario: tuple[CelulaHorario, ...] = ()


@dataclass(frozen=True, slots=True)
class DiaBruto:
    """Um dia com atividade (dias sem nada nao vem; o caso de uso completa com zeros)."""

    dia: date
    conversas_novas: int = 0
    conversas_ativas: int = 0
    mensagens_recebidas: int = 0
    uso_por_modelo: tuple[UsoModelo, ...] = ()
    latencia_llm: Latencia = Latencia()
    tempo_resposta: Latencia = Latencia()
    erros: int = 0


class LeitorMetricas(Protocol):
    async def totais(self, loja_id: UUID, periodo: Periodo) -> TotaisPeriodo: ...

    async def dias(self, loja_id: UUID, periodo: Periodo) -> Sequence[DiaBruto]: ...


# --- o que o caso de uso devolve --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Indicador:
    """Valor do periodo, o do periodo anterior e a variacao % (None se nao calculavel)."""

    valor: Decimal | None
    anterior: Decimal | None
    variacao_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class Kpis:
    conversas_novas: Indicador
    conversas_ativas: Indicador
    mensagens_recebidas: Indicador
    mensagens_enviadas: Indicador
    mensagens_por_conversa: Indicador
    handoffs: Indicador
    taxa_handoff: Indicador
    acordos_fechados: Indicador
    taxa_conversao: Indicador
    tokens_total: Indicador
    taxa_cache: Indicador
    custo_total_usd: Indicador
    custo_por_conversa_usd: Indicador
    custo_por_acordo_usd: Indicador
    latencia_llm_media_ms: Indicador
    latencia_llm_p95_ms: Indicador
    tempo_resposta_media_ms: Indicador
    tempo_resposta_p95_ms: Indicador
    erros: Indicador
    respostas_descartadas: Indicador


@dataclass(frozen=True, slots=True)
class EtapaFunil:
    etapa: str
    nome: str
    leads: int
    leads_anterior: int


@dataclass(frozen=True, slots=True)
class LinhaHandoff:
    motivo: str
    nome: str
    quantidade: int
    anterior: int


@dataclass(frozen=True, slots=True)
class TokensPeriodo:
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int
    chamadas: int

    @property
    def total(self) -> int:
        return self.entrada + self.saida + self.cache_leitura + self.cache_escrita


@dataclass(frozen=True, slots=True)
class CustoModelo:
    modelo: str
    custo_usd: Decimal | None
    """`None`: modelo sem preco cadastrado (custo nao calculado)."""
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int
    chamadas: int


@dataclass(frozen=True, slots=True)
class CustoPeriodo:
    total_usd: Decimal
    """Soma dos modelos COM preco; ver `completo`."""
    completo: bool
    modelos_sem_preco: tuple[str, ...]
    por_modelo: tuple[CustoModelo, ...]


@dataclass(frozen=True, slots=True)
class ErrosPeriodo:
    total: int
    llm: int
    ferramentas: int
    limite_iteracoes: int
    respostas_descartadas: int
    llm_por_tipo: tuple[ContagemPorTipo, ...]


@dataclass(frozen=True, slots=True)
class PontoDiario:
    dia: date
    conversas_novas: int
    conversas_ativas: int
    mensagens_recebidas: int
    tokens: int
    custo_usd: Decimal
    latencia_llm_media_ms: Decimal | None
    latencia_llm_p95_ms: Decimal | None
    tempo_resposta_media_ms: Decimal | None
    tempo_resposta_p95_ms: Decimal | None
    erros: int


@dataclass(frozen=True, slots=True)
class MetricasResultado:
    periodo: Periodo
    periodo_anterior: Periodo
    kpis: Kpis
    funil: tuple[EtapaFunil, ...]
    handoffs: tuple[LinhaHandoff, ...]
    total_handoffs: int
    tokens: TokensPeriodo
    custo: CustoPeriodo
    erros: ErrosPeriodo
    ferramentas: tuple[UsoFerramenta, ...]
    modelos_procurados: tuple[ModeloProcurado, ...]
    mapa_horario: tuple[CelulaHorario, ...]
    series: tuple[PontoDiario, ...]


# --- calculo ----------------------------------------------------------------------------------


def _hoje() -> date:
    return datetime.now(FUSO).date()


def _custo(uso: Sequence[UsoModelo]) -> CustoPeriodo:
    total = Decimal(0)
    sem_preco: list[str] = []
    linhas: list[CustoModelo] = []
    for u in uso:
        custo = custo_usd(u.modelo, u.entrada, u.saida, u.cache_leitura, u.cache_escrita)
        if custo is None:
            sem_preco.append(u.modelo)
        else:
            total += custo
        linhas.append(
            CustoModelo(
                u.modelo, custo, u.entrada, u.saida, u.cache_leitura, u.cache_escrita, u.chamadas
            )
        )
    return CustoPeriodo(total, not sem_preco, tuple(sem_preco), tuple(linhas))


def _tokens(uso: Sequence[UsoModelo]) -> TokensPeriodo:
    return TokensPeriodo(
        entrada=sum(u.entrada for u in uso),
        saida=sum(u.saida for u in uso),
        cache_leitura=sum(u.cache_leitura for u in uso),
        cache_escrita=sum(u.cache_escrita for u in uso),
        chamadas=sum(u.chamadas for u in uso),
    )


def _erros(t: TotaisPeriodo) -> ErrosPeriodo:
    llm = sum(e.quantidade for e in t.erros_llm_por_tipo)
    ferramentas = sum(f.erros for f in t.ferramentas)
    return ErrosPeriodo(
        total=llm + ferramentas + t.limite_iteracoes + t.respostas_descartadas,
        llm=llm,
        ferramentas=ferramentas,
        limite_iteracoes=t.limite_iteracoes,
        respostas_descartadas=t.respostas_descartadas,
        llm_por_tipo=t.erros_llm_por_tipo,
    )


def _total_handoffs(t: TotaisPeriodo) -> int:
    return sum(t.handoffs_por_motivo.values())


def _valores(t: TotaisPeriodo) -> dict[str, Decimal | None]:
    """Valor de cada KPI de um periodo (mesma conta para o atual e o anterior)."""
    tokens = _tokens(t.uso_por_modelo)
    custo = _custo(t.uso_por_modelo).total_usd
    return {
        "conversas_novas": Decimal(t.conversas_novas),
        "conversas_ativas": Decimal(t.conversas_ativas),
        "mensagens_recebidas": Decimal(t.mensagens_recebidas),
        "mensagens_enviadas": Decimal(t.mensagens_enviadas),
        "mensagens_por_conversa": razao(
            t.mensagens_recebidas + t.mensagens_enviadas, t.conversas_ativas
        ),
        "handoffs": Decimal(_total_handoffs(t)),
        "taxa_handoff": razao(t.leads_com_handoff, t.conversas_ativas),
        "acordos_fechados": Decimal(t.acordos_fechados),
        "taxa_conversao": razao(t.acordos_fechados, t.conversas_ativas),
        "tokens_total": Decimal(tokens.total),
        "taxa_cache": taxa_cache(
            entrada=tokens.entrada,
            cache_leitura=tokens.cache_leitura,
            cache_escrita=tokens.cache_escrita,
        ),
        "custo_total_usd": custo,
        "custo_por_conversa_usd": razao(custo, t.conversas_ativas),
        "custo_por_acordo_usd": razao(custo, t.acordos_fechados),
        "latencia_llm_media_ms": t.latencia_llm.media_ms,
        "latencia_llm_p95_ms": t.latencia_llm.p95_ms,
        "tempo_resposta_media_ms": t.tempo_resposta.media_ms,
        "tempo_resposta_p95_ms": t.tempo_resposta.p95_ms,
        "erros": Decimal(_erros(t).total),
        "respostas_descartadas": Decimal(t.respostas_descartadas),
    }


def _kpis(atual: TotaisPeriodo, anterior: TotaisPeriodo) -> Kpis:
    a, b = _valores(atual), _valores(anterior)
    return Kpis(**{k: Indicador(a[k], b[k], variacao_pct(a[k], b[k])) for k in a})


def _funil(atual: TotaisPeriodo, anterior: TotaisPeriodo) -> tuple[EtapaFunil, ...]:
    return tuple(
        EtapaFunil(
            e.value,
            e.nome_exibicao,
            atual.leads_por_etapa.get(e.value, 0),
            anterior.leads_por_etapa.get(e.value, 0),
        )
        for e in Etapa
    )


def _por_categoria(t: TotaisPeriodo) -> dict[MotivoHandoff, int]:
    soma = dict.fromkeys(MotivoHandoff, 0)
    for motivo, quantidade in t.handoffs_por_motivo.items():
        soma[classificar_motivo_handoff(motivo)] += quantidade
    return soma


def _handoffs(atual: TotaisPeriodo, anterior: TotaisPeriodo) -> tuple[LinhaHandoff, ...]:
    a, b = _por_categoria(atual), _por_categoria(anterior)
    return tuple(LinhaHandoff(m.value, m.nome_exibicao, a[m], b[m]) for m in MotivoHandoff)


def _series(periodo: Periodo, brutos: Sequence[DiaBruto]) -> tuple[PontoDiario, ...]:
    por_dia = {d.dia: d for d in brutos}
    pontos: list[PontoDiario] = []
    for dia in periodo.listar_dias():
        d = por_dia.get(dia, DiaBruto(dia))
        pontos.append(
            PontoDiario(
                dia=dia,
                conversas_novas=d.conversas_novas,
                conversas_ativas=d.conversas_ativas,
                mensagens_recebidas=d.mensagens_recebidas,
                tokens=sum(u.tokens for u in d.uso_por_modelo),
                custo_usd=_custo(d.uso_por_modelo).total_usd,
                latencia_llm_media_ms=d.latencia_llm.media_ms,
                latencia_llm_p95_ms=d.latencia_llm.p95_ms,
                tempo_resposta_media_ms=d.tempo_resposta.media_ms,
                tempo_resposta_p95_ms=d.tempo_resposta.p95_ms,
                erros=d.erros,
            )
        )
    return tuple(pontos)


class MetricasAgente:
    """Metricas do agente de uma loja num periodo (padrao: ultimos 30 dias)."""

    def __init__(
        self,
        lojas: RepositorioLojas,
        leitor: LeitorMetricas,
        *,
        hoje: Callable[[], date] = _hoje,
    ) -> None:
        self._lojas = lojas
        self._leitor = leitor
        self._hoje = hoje

    def _periodo(self, de: date | None, ate: date | None) -> Periodo:
        fim = ate or self._hoje()
        inicio = de or fim - timedelta(days=DIAS_PADRAO - 1)
        if inicio > fim:
            raise ErrosDeValidacao(
                [ErroCampo("de", "A data inicial não pode ser depois da final.")]
            )
        if (fim - inicio).days + 1 > LIMITE_DIAS:
            raise ErrosDeValidacao(
                [ErroCampo("de", f"O período não pode passar de {LIMITE_DIAS} dias.")]
            )
        return Periodo(inicio, fim)

    async def executar(
        self, loja_id: UUID, de: date | None = None, ate: date | None = None
    ) -> MetricasResultado:
        if not await self._lojas.existe(loja_id):
            raise LojaNaoEncontrada(loja_id)
        periodo = self._periodo(de, ate)
        anterior = periodo.anterior()
        atual = await self._leitor.totais(loja_id, periodo)
        antes = await self._leitor.totais(loja_id, anterior)
        dias = await self._leitor.dias(loja_id, periodo)
        return MetricasResultado(
            periodo=periodo,
            periodo_anterior=anterior,
            kpis=_kpis(atual, antes),
            funil=_funil(atual, antes),
            handoffs=_handoffs(atual, antes),
            total_handoffs=_total_handoffs(atual),
            tokens=_tokens(atual.uso_por_modelo),
            custo=_custo(atual.uso_por_modelo),
            erros=_erros(atual),
            ferramentas=atual.ferramentas,
            modelos_procurados=atual.modelos_procurados,
            mapa_horario=atual.mapa_horario,
            series=_series(periodo, dias),
        )
