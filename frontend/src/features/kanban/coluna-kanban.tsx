"use client"

import { useDroppable } from "@dnd-kit/core"

import { EtapaBadge } from "@/components/ui/badge"
import type { ColunaKanban } from "@/lib/api"
import { cn } from "@/lib/utils"

import { CardDoLead } from "./card-lead"

export type EstadoAlvo = "neutro" | "permitido" | "proibido"

export function ColunaDoKanban({
  coluna,
  agora,
  alvo,
  motivoProibido,
  sobre,
}: {
  coluna: ColunaKanban
  agora: Date
  /** Como a coluna se comporta para o card que está sendo arrastado. */
  alvo: EstadoAlvo
  motivoProibido?: string
  /** O ponteiro está sobre esta coluna. */
  sobre: boolean
}) {
  const { setNodeRef } = useDroppable({ id: coluna.etapa })
  const total = coluna.leads.length
  return (
    <section
      aria-label={`${coluna.nome}, ${total} ${total === 1 ? "lead" : "leads"}`}
      data-etapa={coluna.etapa}
      data-alvo={alvo}
      className="flex w-72 shrink-0 flex-col gap-2 lg:w-auto lg:min-w-56 lg:flex-1"
    >
      <header className="flex items-center justify-between gap-2 px-1">
        <EtapaBadge etapa={coluna.etapa} />
        <span className="font-mono text-xs text-muted-foreground">{total}</span>
      </header>
      <div
        ref={setNodeRef}
        className={cn(
          "flex min-h-32 flex-1 flex-col gap-2 rounded-lg border border-dashed border-transparent bg-muted/50 p-2 transition-colors",
          alvo === "permitido" && sobre && "border-primary bg-primary/10",
          alvo === "proibido" && "border-danger/50 bg-danger/5 opacity-70",
          alvo === "proibido" && sobre && "border-danger bg-danger/15 opacity-100",
        )}
      >
        {alvo === "proibido" && sobre && motivoProibido ? (
          <p role="status" className="rounded-md bg-danger/15 px-2 py-1 text-xs font-medium text-foreground">
            {motivoProibido}
          </p>
        ) : null}
        {total === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">Nenhum lead</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {coluna.leads.map((lead) => (
              <CardDoLead key={lead.id} lead={lead} agora={agora} />
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
