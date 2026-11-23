import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export type VariacaoTile = {
  /** Texto curto exibido (ex.: "+12,5%"). */
  texto: string
  /** Cor semântica: bom (success), ruim (danger) ou neutro. */
  tom: "bom" | "ruim" | "neutro"
  direcao: "alta" | "baixa" | "estavel"
  /** Frase completa para leitor de tela (ex.: "aumento de 12,5% em relação ao período anterior"). */
  descricao: string
}

const TOM = {
  bom: "text-success",
  ruim: "text-danger",
  neutro: "text-muted-foreground",
} as const

const SETA = { alta: ArrowUp, baixa: ArrowDown, estavel: Minus } as const

/**
 * Cartão de um número (KPI): rótulo, valor, variação contra o período anterior e um slot
 * opcional (ex.: `Medidor`). `variacao={null}` diz que não há comparação; `undefined` oculta a linha.
 */
export function StatTile({
  rotulo,
  valor,
  dica,
  dicaSemValor,
  variacao,
  children,
  className,
}: {
  rotulo: string
  /** Valor já formatado; `null` mostra "—" com `dicaSemValor`. */
  valor: string | null
  /** Explicação curta do indicador, em linguagem simples (tooltip nativo). */
  dica?: string
  dicaSemValor?: string
  variacao?: VariacaoTile | null
  children?: ReactNode
  className?: string
}) {
  const Seta = variacao ? SETA[variacao.direcao] : null
  return (
    <Card size="sm" role="group" aria-label={rotulo} data-slot="stat-tile" className={cn("min-w-0", className)}>
      <div className="flex min-w-0 flex-col gap-1 px-(--card-spacing)">
        <p className="text-xs font-medium text-muted-foreground" title={dica}>
          {rotulo}
        </p>
        <p className="truncate text-2xl leading-tight font-semibold">
          {valor === null ? (
            <span title={dicaSemValor}>
              —
              {dicaSemValor ? <span className="sr-only">{dicaSemValor}</span> : null}
            </span>
          ) : (
            valor
          )}
        </p>
        {variacao ? (
          <p data-tom={variacao.tom} className={cn("flex flex-wrap items-center gap-x-1 text-xs font-medium", TOM[variacao.tom])}>
            {Seta ? <Seta aria-hidden="true" className="size-3.5 shrink-0" /> : null}
            <span>{variacao.texto}</span>
            <span aria-hidden="true" className="font-normal text-muted-foreground">
              vs. anterior
            </span>
            <span className="sr-only">{variacao.descricao}</span>
          </p>
        ) : variacao === null ? (
          <p className="text-xs text-muted-foreground">Sem comparação</p>
        ) : null}
        {children}
      </div>
    </Card>
  )
}
