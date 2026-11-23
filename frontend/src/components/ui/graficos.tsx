"use client"

import { Area, AreaChart, Bar, BarChart, Cell, CartesianGrid, LabelList, Line, LineChart, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
  type TokenDeCor,
} from "@/components/ui/chart"

export type SerieDoGrafico = { chave: string; rotulo: string; cor: TokenDeCor }

type Linha = Record<string, string | number | null>

/**
 * Evolução ao longo do tempo (um ponto por dia). Uma série: área suave; várias: linhas.
 * Valores `null` abrem uma lacuna (nunca viram zero). O último valor de cada série vem rotulado.
 */
export function GraficoSerie({
  rotulo,
  dados,
  chaveX,
  series,
  formatarValor,
  formatarEixo,
  formatarX,
  larguraEixoY = 52,
  margemDireita = 40,
  altura = 224,
}: {
  rotulo: string
  dados: Linha[]
  chaveX: string
  series: SerieDoGrafico[]
  formatarValor: (valor: number | null) => string
  /** Rótulos do eixo Y (compactos); padrão: `formatarValor`. */
  formatarEixo?: (valor: number) => string
  formatarX: (x: string) => string
  larguraEixoY?: number
  /** Espaço para o rótulo do último valor (cresce com o tamanho do texto). */
  margemDireita?: number
  altura?: number
}) {
  const config: ChartConfig = Object.fromEntries(series.map((s) => [s.chave, { label: s.rotulo, cor: s.cor }]))
  const area = series.length === 1

  const ultimo = (chave: string) => {
    for (let i = dados.length - 1; i >= 0; i--) if (typeof dados[i][chave] === "number") return i
    return -1
  }

  const eixos = (
    <>
      <CartesianGrid vertical={false} />
      <XAxis dataKey={chaveX} tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} tickFormatter={formatarX} />
      <YAxis
        width={larguraEixoY}
        tickLine={false}
        axisLine={false}
        tickMargin={4}
        tickFormatter={(v: number) => (formatarEixo ?? formatarValor)(v)}
      />
      <ChartTooltip
        content={
          <ChartTooltipContent formatarValor={(v) => formatarValor(v)} formatarRotulo={(x) => formatarX(String(x))} />
        }
      />
      {series.length > 1 ? <ChartLegend content={<ChartLegendContent />} /> : null}
    </>
  )

  const margem = { top: 16, right: margemDireita, left: 0, bottom: 0 }

  return (
    <ChartContainer rotulo={rotulo} config={config} altura={altura}>
      {area ? (
        <AreaChart data={dados} margin={margem} accessibilityLayer>
          {eixos}
          {series.map((s) => (
            <Area
              key={s.chave}
              dataKey={s.chave}
              type="monotone"
              stroke={`var(--color-${s.chave})`}
              strokeWidth={2}
              fill={`var(--color-${s.chave})`}
              fillOpacity={0.1}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
              isAnimationActive={false}
              label={rotuloDoUltimo(ultimo(s.chave), formatarValor)}
            />
          ))}
        </AreaChart>
      ) : (
        <LineChart data={dados} margin={margem} accessibilityLayer>
          {eixos}
          {series.map((s) => (
            <Line
              key={s.chave}
              dataKey={s.chave}
              type="monotone"
              stroke={`var(--color-${s.chave})`}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
              isAnimationActive={false}
              label={rotuloDoUltimo(ultimo(s.chave), formatarValor)}
            />
          ))}
        </LineChart>
      )}
    </ChartContainer>
  )
}

type PropsRotulo = { x?: number | string; y?: number | string; value?: unknown; index?: number }

/** Rótulo só no último ponto da série (rotular todos seria ruído). */
function rotuloDoUltimo(indice: number, formatar: (valor: number | null) => string) {
  function RotuloUltimo({ x, y, value, index }: PropsRotulo) {
    if (index !== indice || typeof value !== "number") return null
    return (
      <text
        x={Number(x) + 6}
        y={Number(y)}
        dominantBaseline="middle"
        className="fill-foreground text-xs font-medium"
      >
        {formatar(value)}
      </text>
    )
  }
  return RotuloUltimo
}

export type BarraDoGrafico = { nome: string; valor: number; cor?: TokenDeCor }

/**
 * Barras horizontais ordenadas pelo chamador, com o valor na ponta. Sem `cor` por barra, todas
 * usam `corPadrao` (uma série = uma cor); o funil passa a cor de cada etapa.
 */
export function GraficoBarras({
  rotulo,
  dados,
  nomeDoValor,
  formatarValor,
  corPadrao = "chart-1",
  larguraRotulo = 156,
}: {
  rotulo: string
  dados: BarraDoGrafico[]
  /** Nome do valor no tooltip (ex.: "Leads"). */
  nomeDoValor: string
  formatarValor: (valor: number) => string
  corPadrao?: TokenDeCor
  larguraRotulo?: number
}) {
  const config: ChartConfig = { valor: { label: nomeDoValor, cor: corPadrao } }
  const altura = dados.length * 36 + 12

  return (
    <ChartContainer rotulo={rotulo} config={config} altura={altura}>
      <BarChart data={dados} layout="vertical" margin={{ top: 0, right: 72, left: 0, bottom: 0 }} barCategoryGap={6} accessibilityLayer>
        <XAxis type="number" hide />
        <YAxis dataKey="nome" type="category" width={larguraRotulo} tickLine={false} axisLine={false} tickMargin={4} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent formatarValor={(v) => formatarValor(v ?? 0)} />} />
        <Bar dataKey="valor" radius={[0, 4, 4, 0]} maxBarSize={24} isAnimationActive={false}>
          {dados.map((d) => (
            <Cell key={d.nome} fill={`var(--${d.cor ?? corPadrao})`} />
          ))}
          <LabelList
            dataKey="valor"
            position="right"
            className="fill-foreground text-xs font-medium"
            formatter={(v: unknown) => (typeof v === "number" ? formatarValor(v) : "")}
          />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}
