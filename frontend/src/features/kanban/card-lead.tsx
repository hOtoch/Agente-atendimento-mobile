"use client"

import { useDraggable } from "@dnd-kit/core"
import Link from "next/link"

import { DonoBadge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { CardLead } from "@/lib/api"
import { contatoDoLead } from "@/lib/lead"
import { cn } from "@/lib/utils"

import { formatarValor, tempoNaEtapa } from "./regras"

/** Conteúdo visual do card (também usado no overlay durante o arrasto). */
export function ConteudoCard({ lead, agora, link = true }: { lead: CardLead; agora: Date; link?: boolean }) {
  const { titulo, detalhe } = contatoDoLead(lead)
  const valor = formatarValor(lead.valor_estimado)
  const dono = lead.dono === "ia" ? "ia" : "vendedor"
  return (
    <>
      <div className="flex items-start justify-between gap-2">
        {link ? (
          <Link
            href={`/conversas?lead=${lead.id}`}
            className="truncate text-sm font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {titulo}
          </Link>
        ) : (
          <span className="truncate text-sm font-medium text-foreground">{titulo}</span>
        )}
        {valor ? <span className="shrink-0 font-mono text-xs text-foreground">{valor}</span> : null}
      </div>
      <span className="font-mono text-xs text-muted-foreground">{detalhe}</span>
      <span className={cn("truncate text-xs", lead.aparelho_desejado ? "text-foreground" : "text-muted-foreground")}>
        {lead.aparelho_desejado ?? "Aparelho não definido"}
      </span>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <DonoBadge dono={dono} />
          {lead.vendedor_nome ? (
            <span className="truncate text-xs text-muted-foreground">{lead.vendedor_nome}</span>
          ) : null}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground" title="Tempo na etapa">
          {tempoNaEtapa(lead.etapa_desde, agora)}
        </span>
      </div>
    </>
  )
}

export function CardDoLead({ lead, agora }: { lead: CardLead; agora: Date }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: lead.id })
  return (
    <li>
      <Card
        size="sm"
        ref={setNodeRef}
        {...attributes}
        {...listeners}
        role="group"
        aria-label={contatoDoLead(lead).titulo}
        data-lead-id={lead.id}
        data-arrastando={isDragging || undefined}
        className={cn(
          "cursor-grab touch-manipulation gap-1 px-3 outline-none focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing",
          isDragging && "opacity-40",
        )}
      >
        <ConteudoCard lead={lead} agora={agora} />
      </Card>
    </li>
  )
}
