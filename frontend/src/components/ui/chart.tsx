"use client"

import * as React from "react"
import * as RechartsPrimitive from "recharts"

import { cn } from "@/lib/utils"

/**
 * Base de gráficos do design system (padrão shadcn/ui sobre recharts).
 *
 * Cores vêm só dos tokens `--chart-1..5` (ou `--stage-*`): cada série declara `cor: "chart-1"` e
 * o container publica `--color-<serie>`; os marcos usam `fill="var(--color-<serie>)"`.
 * Grade, eixos e texto usam os tokens de superfície (`border`, `muted-foreground`, `foreground`).
 */

export type TokenDeCor = `chart-${1 | 2 | 3 | 4 | 5}` | `stage-${string}`

export type ChartConfig = Record<string, { label: string; cor: TokenDeCor }>

const ChartContext = React.createContext<{ config: ChartConfig } | null>(null)

function useChart() {
  const ctx = React.useContext(ChartContext)
  if (!ctx) throw new Error("useChart precisa estar dentro de <ChartContainer />")
  return ctx
}

function ChartContainer({
  id,
  className,
  config,
  rotulo,
  altura,
  style,
  children,
  ...props
}: Omit<React.ComponentProps<"div">, "children"> & {
  config: ChartConfig
  /** Nome acessível do gráfico (`aria-label`); a alternativa completa é a tabela do `CartaoGrafico`. */
  rotulo: string
  /** Altura fixa em px (inclui o eixo X); sem ela vale `h-64`. */
  altura?: number
  children: React.ComponentProps<typeof RechartsPrimitive.ResponsiveContainer>["children"]
}) {
  const uid = React.useId()
  const chartId = `chart-${id ?? uid.replace(/:/g, "")}`
  const estilo = Object.fromEntries(
    Object.entries(config).map(([chave, { cor }]) => [`--color-${chave}`, `var(--${cor})`]),
  ) as React.CSSProperties

  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-slot="chart"
        data-chart={chartId}
        role="img"
        aria-label={rotulo}
        style={{ ...estilo, ...(altura ? { height: altura } : null), ...style }}
        className={cn(
          "flex h-64 w-full justify-center text-xs",
          "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground",
          "[&_.recharts-cartesian-grid_line]:stroke-border",
          "[&_.recharts-cartesian-axis-line]:stroke-border [&_.recharts-cartesian-axis-tick-line]:stroke-border",
          "[&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted",
          "[&_.recharts-layer]:outline-hidden [&_.recharts-surface]:outline-hidden",
          className,
        )}
        {...props}
      >
        <RechartsPrimitive.ResponsiveContainer initialDimension={{ width: 480, height: altura ?? 256 }}>
          {children}
        </RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  )
}

const ChartTooltip = RechartsPrimitive.Tooltip

type PayloadItem = {
  dataKey?: string | number
  name?: string | number
  value?: unknown
  color?: string
  payload?: Record<string, unknown>
}

function ChartTooltipContent({
  active,
  payload,
  label,
  formatarValor,
  formatarRotulo,
  className,
}: {
  active?: boolean
  payload?: readonly PayloadItem[]
  label?: unknown
  formatarValor?: (valor: number | null, chave: string) => string
  formatarRotulo?: (rotulo: unknown) => string
  className?: string
}) {
  const { config } = useChart()
  if (!active || !payload?.length) return null

  const titulo = formatarRotulo ? formatarRotulo(label) : label == null ? null : String(label)

  return (
    <div
      className={cn(
        "grid min-w-32 items-start gap-1.5 rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-xl",
        className,
      )}
    >
      {titulo ? <div className="font-medium">{titulo}</div> : null}
      <div className="grid gap-1">
        {payload.map((item) => {
          const chave = String(item.dataKey ?? item.name ?? "")
          const serie = config[chave]
          const valor = typeof item.value === "number" ? item.value : null
          return (
            <div key={chave} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-[2px]"
                style={{ backgroundColor: item.color ?? `var(--color-${chave})` }}
              />
              <span className="flex-1 text-muted-foreground">{serie?.label ?? String(item.name ?? chave)}</span>
              <span className="font-mono font-medium text-foreground tabular-nums">
                {formatarValor ? formatarValor(valor, chave) : (valor ?? "—")}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const ChartLegend = RechartsPrimitive.Legend

type LegendItem = { dataKey?: unknown; value?: unknown; color?: string }

function ChartLegendContent({
  payload,
  className,
}: {
  payload?: readonly LegendItem[]
  className?: string
}) {
  const { config } = useChart()
  if (!payload?.length) return null
  return (
    <ul className={cn("flex flex-wrap items-center justify-center gap-4 pt-2 text-xs", className)}>
      {payload.map((item) => {
        const chave = String(item.dataKey ?? item.value ?? "")
        return (
          <li key={chave} className="flex items-center gap-1.5 text-muted-foreground">
            <span
              aria-hidden="true"
              className="size-2.5 shrink-0 rounded-[2px]"
              style={{ backgroundColor: `var(--color-${chave})` }}
            />
            {config[chave]?.label ?? String(item.value ?? chave)}
          </li>
        )
      })}
    </ul>
  )
}

export {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  useChart,
}
