"""Leitura agregada das metricas do agente (SQL sobre `eventos`, `leads` e `mensagens`).

Todo recorte de dia e feito no fuso America/Sao_Paulo. Os campos dos eventos sao lidos com
tolerancia: evento antigo sem o campo simplesmente nao entra na amostra (latencia) ou vale zero.
Percentil p95 via `percentile_cont` (interpolacao linear), arredondado a 1 casa em `numeric`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.metricas import (
    CelulaHorario,
    ContagemPorTipo,
    DiaBruto,
    Latencia,
    ModeloProcurado,
    TotaisPeriodo,
    UsoFerramenta,
    UsoModelo,
)
from app.domain.metricas import FUSO_NOME, Periodo

LIMITE_MODELOS_PROCURADOS = 10

_PERIODO = "loja_id = :loja AND criado_em >= :ini AND criado_em < :fim"
_DIA_LOCAL = "(criado_em AT TIME ZONE :tz)::date"


def _num(campo: str) -> str:
    """Valor numerico do campo do payload; NULL se ausente (evento antigo) ou nao numerico."""
    return (
        f"CASE WHEN jsonb_typeof(payload->'{campo}') = 'number' "
        f"THEN (payload->>'{campo}')::numeric END"
    )


_ERRO_FERRAMENTA = "(tipo = 'ferramenta' AND payload->>'erro' = 'true')"
_EVENTO_DE_ERRO = (
    f"(tipo IN ('erro_llm', 'limite_iteracoes', 'resposta_descartada') OR {_ERRO_FERRAMENTA})"
)

_SQL_LATENCIAS = f"""
SELECT
  count(llm), round(avg(llm), 1), round((percentile_cont(0.95) WITHIN GROUP
    (ORDER BY llm::double precision))::numeric, 1),
  count(rodada), round(avg(rodada), 1), round((percentile_cont(0.95) WITHIN GROUP
    (ORDER BY rodada::double precision))::numeric, 1),
  count(resposta), round(avg(resposta), 1), round((percentile_cont(0.95) WITHIN GROUP
    (ORDER BY resposta::double precision))::numeric, 1)
FROM (
  SELECT {_num("latencia_llm_ms")} AS llm, {_num("latencia_rodada_ms")} AS rodada,
         {_num("tempo_resposta_ms")} AS resposta
  FROM eventos WHERE {_PERIODO} AND tipo = 'llm_uso'
) amostras
"""

_SQL_LATENCIAS_DIA = f"""
SELECT dia,
  count(llm), round(avg(llm), 1), round((percentile_cont(0.95) WITHIN GROUP
    (ORDER BY llm::double precision))::numeric, 1),
  count(resposta), round(avg(resposta), 1), round((percentile_cont(0.95) WITHIN GROUP
    (ORDER BY resposta::double precision))::numeric, 1)
FROM (
  SELECT {_DIA_LOCAL} AS dia, {_num("latencia_llm_ms")} AS llm,
         {_num("tempo_resposta_ms")} AS resposta
  FROM eventos WHERE {_PERIODO} AND tipo = 'llm_uso'
) amostras GROUP BY dia
"""

_SQL_USO = f"""
SELECT coalesce(payload->>'modelo', '') AS modelo,
  coalesce(sum({_num("entrada")}), 0), coalesce(sum({_num("saida")}), 0),
  coalesce(sum({_num("cache_leitura")}), 0), coalesce(sum({_num("cache_escrita")}), 0),
  coalesce(sum({_num("chamadas")}), 0)
FROM eventos WHERE {_PERIODO} AND tipo = 'llm_uso'
GROUP BY 1 ORDER BY 1
"""

_SQL_USO_DIA = f"""
SELECT {_DIA_LOCAL} AS dia, coalesce(payload->>'modelo', '') AS modelo,
  coalesce(sum({_num("entrada")}), 0), coalesce(sum({_num("saida")}), 0),
  coalesce(sum({_num("cache_leitura")}), 0), coalesce(sum({_num("cache_escrita")}), 0),
  coalesce(sum({_num("chamadas")}), 0)
FROM eventos WHERE {_PERIODO} AND tipo = 'llm_uso'
GROUP BY 1, 2 ORDER BY 1, 2
"""

_SQL_MENSAGENS = f"""
SELECT count(*) FILTER (WHERE direcao = 'entrada'),
       count(*) FILTER (WHERE direcao = 'saida'),
       count(*) FILTER (WHERE direcao = 'saida' AND autor = 'ia'),
       count(DISTINCT conversa_id)
FROM mensagens WHERE {_PERIODO}
"""

_SQL_MENSAGENS_DIA = f"""
SELECT {_DIA_LOCAL} AS dia, count(*) FILTER (WHERE direcao = 'entrada'),
       count(DISTINCT conversa_id)
FROM mensagens WHERE {_PERIODO} GROUP BY 1
"""

_SQL_MAPA = f"""
SELECT extract(isodow FROM criado_em AT TIME ZONE :tz)::int - 1 AS dia_semana,
       extract(hour FROM criado_em AT TIME ZONE :tz)::int AS hora, count(*)
FROM mensagens WHERE {_PERIODO} AND direcao = 'entrada'
GROUP BY 1, 2 ORDER BY 1, 2
"""

_SQL_LEADS_NOVOS = f"SELECT count(*) FROM leads WHERE {_PERIODO}"
_SQL_LEADS_NOVOS_DIA = (
    f"SELECT {_DIA_LOCAL} AS dia, count(*) FROM leads WHERE {_PERIODO} GROUP BY 1"
)
_SQL_FUNIL = f"SELECT etapa, count(*) FROM leads WHERE {_PERIODO} GROUP BY etapa"

_SQL_HANDOFFS = f"""
SELECT payload->>'motivo', count(*), count(DISTINCT lead_id)
FROM eventos WHERE {_PERIODO} AND tipo = 'dono_mudou' AND payload->>'motivo' IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC, 1
"""

_SQL_LEADS_COM_HANDOFF = f"""
SELECT count(DISTINCT lead_id) FROM eventos
WHERE {_PERIODO} AND tipo = 'dono_mudou' AND payload->>'motivo' IS NOT NULL
"""

_SQL_ACORDOS = f"""
SELECT count(DISTINCT lead_id) FROM eventos
WHERE {_PERIODO} AND lead_id IS NOT NULL AND (
  (tipo = 'handoff_resumo' AND jsonb_typeof(payload->'acordo') = 'object')
  OR (tipo = 'dono_mudou' AND payload->>'motivo' = 'acordo_fechado')
)
"""

_SQL_ERROS_LLM = f"""
SELECT coalesce(payload->>'tipo', 'desconhecido'), count(*)
FROM eventos WHERE {_PERIODO} AND tipo = 'erro_llm' GROUP BY 1 ORDER BY 2 DESC, 1
"""

_SQL_ATRITOS = f"""
SELECT tipo, count(*) FROM eventos
WHERE {_PERIODO} AND tipo IN ('limite_iteracoes', 'resposta_descartada') GROUP BY tipo
"""

_SQL_FERRAMENTAS = f"""
SELECT payload->>'nome', count(*), count(*) FILTER (WHERE payload->>'erro' = 'true')
FROM eventos WHERE {_PERIODO} AND tipo = 'ferramenta' AND payload->>'nome' IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC, 1
"""

_SQL_MODELOS_PROCURADOS = f"""
SELECT min(btrim(payload#>>'{{entrada,modelo}}') COLLATE "C"),
       count(DISTINCT coalesce(lead_id::text, id::text)) AS leads
FROM eventos
WHERE {_PERIODO} AND tipo = 'ferramenta'
  AND payload->>'nome' IN ('registrar_interesse', 'consultar_estoque')
  AND btrim(coalesce(payload#>>'{{entrada,modelo}}', '')) <> ''
GROUP BY lower(btrim(payload#>>'{{entrada,modelo}}'))
ORDER BY leads DESC, 1 LIMIT {LIMITE_MODELOS_PROCURADOS}
"""

_SQL_ERROS_DIA = f"""
SELECT {_DIA_LOCAL} AS dia, count(*) FROM eventos
WHERE {_PERIODO} AND {_EVENTO_DE_ERRO} GROUP BY 1
"""


def _int(valor: Any) -> int:
    return int(valor or 0)


def _latencia(amostras: Any, media: Decimal | None, p95: Decimal | None) -> Latencia:
    if not amostras:
        return Latencia()
    return Latencia(media, p95, int(amostras))


def _uso(linha: Any) -> UsoModelo:
    modelo, entrada, saida, cache_leitura, cache_escrita, chamadas = linha
    return UsoModelo(
        modelo or "",
        _int(entrada),
        _int(saida),
        _int(cache_leitura),
        _int(cache_escrita),
        _int(chamadas),
    )


class LeitorMetricasSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def _linhas(self, sql: str, loja_id: UUID, periodo: Periodo) -> list[Any]:
        resultado = await self._s.execute(
            text(sql),
            {
                "loja": loja_id,
                "ini": periodo.inicio,
                "fim": periodo.fim_exclusivo,
                "tz": FUSO_NOME,
            },
        )
        return list(resultado.all())

    async def totais(self, loja_id: UUID, periodo: Periodo) -> TotaisPeriodo:
        async def q(sql: str) -> list[Any]:
            return await self._linhas(sql, loja_id, periodo)

        recebidas, enviadas, enviadas_ia, ativas = (await q(_SQL_MENSAGENS))[0]
        lat = (await q(_SQL_LATENCIAS))[0]
        handoffs = await q(_SQL_HANDOFFS)
        atritos = dict(await q(_SQL_ATRITOS))
        return TotaisPeriodo(
            conversas_novas=_int((await q(_SQL_LEADS_NOVOS))[0][0]),
            conversas_ativas=_int(ativas),
            mensagens_recebidas=_int(recebidas),
            mensagens_enviadas=_int(enviadas),
            mensagens_enviadas_ia=_int(enviadas_ia),
            leads_por_etapa={etapa: _int(n) for etapa, n in await q(_SQL_FUNIL)},
            handoffs_por_motivo={motivo: _int(n) for motivo, n, _ in handoffs},
            leads_com_handoff=_int((await q(_SQL_LEADS_COM_HANDOFF))[0][0]),
            acordos_fechados=_int((await q(_SQL_ACORDOS))[0][0]),
            uso_por_modelo=tuple(_uso(linha) for linha in await q(_SQL_USO)),
            latencia_llm=_latencia(*lat[0:3]),
            latencia_rodada=_latencia(*lat[3:6]),
            tempo_resposta=_latencia(*lat[6:9]),
            erros_llm_por_tipo=tuple(
                ContagemPorTipo(tipo, _int(n)) for tipo, n in await q(_SQL_ERROS_LLM)
            ),
            limite_iteracoes=_int(atritos.get("limite_iteracoes")),
            respostas_descartadas=_int(atritos.get("resposta_descartada")),
            ferramentas=tuple(
                UsoFerramenta(nome, _int(n), _int(erros))
                for nome, n, erros in await q(_SQL_FERRAMENTAS)
            ),
            modelos_procurados=tuple(
                ModeloProcurado(modelo, _int(n)) for modelo, n in await q(_SQL_MODELOS_PROCURADOS)
            ),
            mapa_horario=tuple(
                CelulaHorario(_int(dia), _int(hora), _int(n)) for dia, hora, n in await q(_SQL_MAPA)
            ),
        )

    async def dias(self, loja_id: UUID, periodo: Periodo) -> list[DiaBruto]:
        async def q(sql: str) -> list[Any]:
            return await self._linhas(sql, loja_id, periodo)

        novas = {dia: _int(n) for dia, n in await q(_SQL_LEADS_NOVOS_DIA)}
        mensagens = {dia: (_int(r), _int(a)) for dia, r, a in await q(_SQL_MENSAGENS_DIA)}
        erros = {dia: _int(n) for dia, n in await q(_SQL_ERROS_DIA)}
        usos: dict[date, list[UsoModelo]] = defaultdict(list)
        for dia, *resto in await q(_SQL_USO_DIA):
            usos[dia].append(_uso(resto))
        latencias = {
            dia: (_latencia(n_llm, m_llm, p_llm), _latencia(n_resp, m_resp, p_resp))
            for dia, n_llm, m_llm, p_llm, n_resp, m_resp, p_resp in await q(_SQL_LATENCIAS_DIA)
        }
        todos = sorted(set(novas) | set(mensagens) | set(erros) | set(usos) | set(latencias))
        vazio = (Latencia(), Latencia())
        return [
            DiaBruto(
                dia=dia,
                conversas_novas=novas.get(dia, 0),
                conversas_ativas=mensagens.get(dia, (0, 0))[1],
                mensagens_recebidas=mensagens.get(dia, (0, 0))[0],
                uso_por_modelo=tuple(usos.get(dia, ())),
                latencia_llm=latencias.get(dia, vazio)[0],
                tempo_resposta=latencias.get(dia, vazio)[1],
                erros=erros.get(dia, 0),
            )
            for dia in todos
        ]
