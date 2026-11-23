import { CartaoGrafico } from "@/components/ui/cartao-grafico"
import { GraficoBarras, GraficoSerie } from "@/components/ui/graficos"
import { MapaCalor } from "@/components/ui/mapa-calor"
import { Medidor } from "@/components/ui/medidor"
import { StatTile } from "@/components/ui/stat-tile"
import { ETAPAS } from "@/lib/etapas"
import type { Metricas } from "@/lib/api"

import {
  INDICADORES_PRINCIPAIS,
  formatarIndicador,
  variacaoDoIndicador,
  type DefinicaoIndicador,
  type Kpis,
} from "./indicadores"
import {
  formatarCompacto,
  formatarDataCurta,
  formatarDuracao,
  formatarInteiro,
  formatarUsd,
} from "./formatar"
import { DIAS, DIAS_CURTOS, HORAS, horariosDePico, montarMapaHorario } from "./mapa-horario"
import { Secao } from "./secao"

const SEM_MEDICAO = "sem medição no período"

function Tile({ def, kpis }: { def: DefinicaoIndicador; kpis: Kpis }) {
  const ind = kpis[def.chave]
  return (
    <StatTile
      rotulo={def.rotulo}
      dica={def.dica}
      dicaSemValor={SEM_MEDICAO}
      valor={formatarIndicador(def.formato, ind.valor)}
      variacao={variacaoDoIndicador(def.sentido, ind.variacao_pct)}
    />
  )
}

export function VisaoGeral({ m }: { m: Metricas }) {
  return (
    <Secao titulo="Visão geral" colunas={4}>
      {INDICADORES_PRINCIPAIS.map((def) => (
        <Tile key={def.chave} def={def} kpis={m.kpis} />
      ))}
    </Secao>
  )
}

const num = (v: string): number => Number(v)

export function Volume({ m }: { m: Metricas }) {
  const dias = m.series.map((p) => ({ ...p }))
  return (
    <Secao titulo="Volume">
      <CartaoGrafico
        titulo="Conversas por dia"
        descricao="Conversas novas e conversas atendidas (com mensagens) em cada dia."
        tabela={{
          colunas: ["Dia", "Novas", "Atendidas"],
          linhas: m.series.map((p) => [formatarDataCurta(p.dia), p.conversas_novas, p.conversas_ativas]),
        }}
      >
        <GraficoSerie
          rotulo="Gráfico de linhas: conversas novas e atendidas por dia"
          dados={dias}
          chaveX="dia"
          formatarX={formatarDataCurta}
          formatarValor={(v) => formatarInteiro(v)}
          series={[
            { chave: "conversas_ativas", rotulo: "Atendidas", cor: "chart-1" },
            { chave: "conversas_novas", rotulo: "Novas", cor: "chart-2" },
          ]}
        />
      </CartaoGrafico>
      <CartaoGrafico
        titulo="Mensagens recebidas por dia"
        descricao="Mensagens que os clientes enviaram em cada dia."
        tabela={{
          colunas: ["Dia", "Mensagens"],
          linhas: m.series.map((p) => [formatarDataCurta(p.dia), p.mensagens_recebidas]),
        }}
      >
        <GraficoSerie
          rotulo="Gráfico de área: mensagens recebidas por dia"
          dados={dias}
          chaveX="dia"
          formatarX={formatarDataCurta}
          formatarValor={(v) => formatarInteiro(v)}
          formatarEixo={formatarCompacto}
          series={[{ chave: "mensagens_recebidas", rotulo: "Mensagens recebidas", cor: "chart-1" }]}
        />
      </CartaoGrafico>
    </Secao>
  )
}

function tokenDaEtapa(etapa: string) {
  const achada = ETAPAS.find((e) => e.valor === etapa)
  return achada ? (`stage-${achada.token}` as const) : "chart-5"
}

function SemRegistros({ texto }: { texto: string }) {
  return <p className="py-8 text-center text-sm text-muted-foreground">{texto}</p>
}

export function Resultado({ m }: { m: Metricas }) {
  return (
    <Secao titulo="Resultado">
      <CartaoGrafico
        titulo="Funil de vendas"
        descricao="Quantos clientes chegaram a cada etapa do kanban no período."
        tabela={{
          colunas: ["Etapa", "Clientes", "Período anterior"],
          linhas: m.funil.map((e) => [e.nome, e.leads, e.leads_anterior]),
        }}
      >
        <GraficoBarras
          rotulo="Gráfico de barras: clientes em cada etapa do funil"
          nomeDoValor="Clientes"
          formatarValor={formatarInteiro}
          larguraRotulo={170}
          dados={m.funil.map((e) => ({ nome: e.nome, valor: e.leads, cor: tokenDaEtapa(e.etapa) }))}
        />
      </CartaoGrafico>
      <CartaoGrafico
        titulo="Passadas ao vendedor, por motivo"
        descricao="Por que a IA chamou um vendedor para continuar o atendimento."
        tabela={{
          colunas: ["Motivo", "Quantidade", "Período anterior"],
          linhas: m.handoffs.por_motivo.map((x) => [x.nome, x.quantidade, x.anterior]),
        }}
      >
        {m.handoffs.total === 0 ? (
          <SemRegistros texto="Nenhuma conversa foi passada ao vendedor neste período." />
        ) : (
          <GraficoBarras
            rotulo="Gráfico de barras: passadas ao vendedor por motivo"
            nomeDoValor="Passadas"
            formatarValor={formatarInteiro}
            dados={m.handoffs.por_motivo.map((x) => ({ nome: x.nome, valor: x.quantidade }))}
          />
        )}
      </CartaoGrafico>
    </Secao>
  )
}

function AvisoCusto({ custo }: { custo: Metricas["custo"] }) {
  if (custo.completo) return null
  return (
    <div
      role="status"
      className="rounded-lg border border-warning bg-warning/10 px-3 py-2 text-sm text-foreground lg:col-span-2"
    >
      O gasto mostrado não inclui os modelos de IA sem preço cadastrado ({custo.modelos_sem_preco.join(", ")}). O
      valor real pode ser maior.
    </div>
  )
}

export function Custo({ m }: { m: Metricas }) {
  const { tokens, kpis } = m
  const cache = kpis.taxa_cache
  const porAcordo = kpis.custo_por_acordo_usd
  const defCache = { sentido: "maior-melhor" as const }
  const defAcordo = { sentido: "menor-melhor" as const }

  return (
    <Secao titulo="Custo e uso">
      <AvisoCusto custo={m.custo} />
      <CartaoGrafico
        titulo="Gasto por dia"
        descricao="Quanto a IA custou em cada dia, em dólares."
        tabela={{
          colunas: ["Dia", "Gasto"],
          linhas: m.series.map((p) => [formatarDataCurta(p.dia), formatarUsd(p.custo_usd)]),
        }}
      >
        <GraficoSerie
          rotulo="Gráfico de área: gasto com a IA por dia"
          dados={m.series.map((p) => ({ dia: p.dia, custo: num(p.custo_usd) }))}
          chaveX="dia"
          formatarX={formatarDataCurta}
          formatarValor={(v) => formatarUsd(v)}
          larguraEixoY={72}
          margemDireita={80}
          series={[{ chave: "custo", rotulo: "Gasto", cor: "chart-1" }]}
        />
      </CartaoGrafico>
      <CartaoGrafico
        titulo="Tokens por tipo"
        descricao="Tokens são as palavras que a IA lê e escreve; são a base do custo."
        tabela={{
          colunas: ["Tipo", "Tokens"],
          linhas: tokensPorTipo(tokens).map((t) => [t.nome, t.valor]),
        }}
      >
        <GraficoBarras
          rotulo="Gráfico de barras: tokens por tipo"
          nomeDoValor="Tokens"
          formatarValor={formatarCompacto}
          larguraRotulo={170}
          dados={tokensPorTipo(tokens)}
        />
      </CartaoGrafico>
      <StatTile
        rotulo="Aproveitamento do cache"
        dica="Parte do que foi enviado à IA que ela já tinha guardado; quanto maior, menor o custo."
        dicaSemValor={SEM_MEDICAO}
        valor={formatarIndicador("percentual", cache.valor)}
        variacao={variacaoDoIndicador(defCache.sentido, cache.variacao_pct)}
      >
        {cache.valor !== null ? <Medidor fracao={Number(cache.valor)} rotulo="Aproveitamento do cache" className="mt-1" /> : null}
      </StatTile>
      <StatTile
        rotulo="Custo por acordo"
        dica="Gasto com a IA dividido pelos acordos fechados."
        dicaSemValor="sem acordos fechados no período"
        valor={formatarIndicador("usd", porAcordo.valor)}
        variacao={variacaoDoIndicador(defAcordo.sentido, porAcordo.variacao_pct)}
      />
    </Secao>
  )
}

function tokensPorTipo(t: Metricas["tokens"]) {
  return [
    { nome: "Texto enviado à IA", valor: t.entrada },
    { nome: "Texto escrito pela IA", valor: t.saida },
    { nome: "Reaproveitado do cache", valor: t.cache_leitura },
    { nome: "Gravado no cache", valor: t.cache_escrita },
  ]
}

const EIXO_DURACAO = { formatarValor: (v: number | null) => formatarDuracao(v), larguraEixoY: 60 }

export function Qualidade({ m }: { m: Metricas }) {
  const { erros, kpis } = m
  const tiposDeErro = [
    { nome: "Falha da IA", valor: erros.llm },
    { nome: "Falha em ferramenta", valor: erros.ferramentas },
    { nome: "Limite de passos", valor: erros.limite_iteracoes },
    { nome: "Resposta descartada", valor: erros.respostas_descartadas },
  ]
  const descartadas = kpis.respostas_descartadas

  return (
    <Secao titulo="Qualidade">
      <CartaoGrafico
        titulo="Tempo de resposta por dia"
        descricao="Quanto o cliente esperou pela resposta. Os 5% mais lentos mostram os piores casos."
        tabela={{
          colunas: ["Dia", "Média", "5% mais lentos"],
          linhas: m.series.map((p) => [
            formatarDataCurta(p.dia),
            formatarDuracao(p.tempo_resposta_media_ms),
            formatarDuracao(p.tempo_resposta_p95_ms),
          ]),
        }}
      >
        <GraficoSerie
          rotulo="Gráfico de linhas: tempo de resposta médio e dos 5% mais lentos, por dia"
          dados={m.series.map((p) => ({ ...p }))}
          chaveX="dia"
          formatarX={formatarDataCurta}
          {...EIXO_DURACAO}
          series={[
            { chave: "tempo_resposta_media_ms", rotulo: "Média", cor: "chart-1" },
            { chave: "tempo_resposta_p95_ms", rotulo: "5% mais lentos", cor: "chart-2" },
          ]}
        />
      </CartaoGrafico>
      <CartaoGrafico
        titulo="Tempo de processamento da IA por dia"
        descricao="Tempo que a IA levou só para montar a resposta, sem contar esperas do atendimento."
        tabela={{
          colunas: ["Dia", "Média", "5% mais lentos"],
          linhas: m.series.map((p) => [
            formatarDataCurta(p.dia),
            formatarDuracao(p.latencia_llm_media_ms),
            formatarDuracao(p.latencia_llm_p95_ms),
          ]),
        }}
      >
        <GraficoSerie
          rotulo="Gráfico de linhas: tempo de processamento da IA, média e 5% mais lentos, por dia"
          dados={m.series.map((p) => ({ ...p }))}
          chaveX="dia"
          formatarX={formatarDataCurta}
          {...EIXO_DURACAO}
          series={[
            { chave: "latencia_llm_media_ms", rotulo: "Média", cor: "chart-1" },
            { chave: "latencia_llm_p95_ms", rotulo: "5% mais lentos", cor: "chart-2" },
          ]}
        />
      </CartaoGrafico>
      <CartaoGrafico
        titulo="Erros por tipo"
        descricao="Falhas da IA e das ferramentas, limite de passos e respostas bloqueadas."
        tabela={{
          colunas: ["Tipo", "Quantidade"],
          linhas: [
            ...tiposDeErro.map((t) => [t.nome, t.valor]),
            ...erros.llm_por_tipo.map((t) => [`Falha da IA: ${t.tipo}`, t.quantidade]),
          ],
        }}
      >
        {erros.total === 0 ? (
          <SemRegistros texto="Nenhum erro neste período." />
        ) : (
          <GraficoBarras
            rotulo="Gráfico de barras: erros por tipo"
            nomeDoValor="Erros"
            formatarValor={formatarInteiro}
            dados={tiposDeErro}
          />
        )}
      </CartaoGrafico>
      <StatTile
        rotulo="Respostas descartadas"
        dica="Respostas que a IA escreveu mas o sistema bloqueou por não cumprirem as regras da loja."
        dicaSemValor={SEM_MEDICAO}
        valor={formatarIndicador("inteiro", descartadas.valor)}
        variacao={variacaoDoIndicador("menor-melhor", descartadas.variacao_pct)}
      />
    </Secao>
  )
}

function descreverCelula(dia: string, hora: string, mensagens: number) {
  return `${dia}, ${hora}: ${mensagens} ${mensagens === 1 ? "mensagem" : "mensagens"}`
}

export function Demanda({ m }: { m: Metricas }) {
  const pico = horariosDePico(m.mapa_horario, 3)
  return (
    <Secao titulo="Demanda" colunas={1}>
      <CartaoGrafico
        titulo="Modelos mais procurados"
        descricao="Aparelhos que os clientes mais pediram no período (até 10)."
        tabela={{
          colunas: ["Modelo", "Clientes"],
          linhas: m.modelos_procurados.map((x) => [x.modelo, x.leads]),
        }}
      >
        {m.modelos_procurados.length === 0 ? (
          <SemRegistros texto="Nenhum aparelho foi procurado neste período." />
        ) : (
          <GraficoBarras
            rotulo="Gráfico de barras: modelos mais procurados"
            nomeDoValor="Clientes"
            formatarValor={formatarInteiro}
            larguraRotulo={160}
            dados={m.modelos_procurados.map((x) => ({ nome: x.modelo, valor: x.leads }))}
          />
        )}
      </CartaoGrafico>
      <CartaoGrafico
        titulo="Horários de pico"
        descricao="Quando os clientes mais mandam mensagem, por dia da semana e hora (horário de Brasília)."
      >
        <MapaCalor
          legenda="Mapa de horários: mensagens recebidas por dia da semana e hora"
          linhas={[...DIAS]}
          linhasCurtas={[...DIAS_CURTOS]}
          colunas={HORAS}
          valores={montarMapaHorario(m.mapa_horario)}
          descreverCelula={descreverCelula}
        />
        {pico.length > 0 ? (
          <ul className="flex flex-col gap-0.5 text-sm text-muted-foreground">
            {pico.map((p) => (
              <li key={`${p.dia}-${p.hora}`}>{descreverCelula(DIAS[p.dia], `${p.hora}h`, p.mensagens)}</li>
            ))}
          </ul>
        ) : null}
      </CartaoGrafico>
    </Secao>
  )
}
