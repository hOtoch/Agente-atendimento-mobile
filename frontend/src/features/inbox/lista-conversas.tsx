"use client"

import { DonoBadge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty-state"
import { Button } from "@/components/ui/button"
import type { CardLead } from "@/lib/api"
import { contatoDoLead } from "@/lib/lead"
import { cn } from "@/lib/utils"

import type { StatusCarga } from "./use-inbox"

type Props = {
  conversas: CardLead[]
  status: StatusCarga
  leadId: string | null
  onSelecionar: (leadId: string) => void
  onRecarregar: () => void
  className?: string
}

export function ListaConversas({ conversas, status, leadId, onSelecionar, onRecarregar, className }: Props) {
  let corpo
  if (status === "carregando") {
    corpo = (
      <div className="flex flex-col gap-2" role="status" aria-label="Carregando conversas">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    )
  } else if (status === "erro") {
    corpo = (
      <EmptyState
        title="Não foi possível carregar as conversas"
        description="Verifique a conexão com o servidor."
        action={
          <Button variant="outline" size="sm" onClick={onRecarregar}>
            Tentar de novo
          </Button>
        }
      />
    )
  } else if (conversas.length === 0) {
    corpo = (
      <EmptyState
        title="Nenhuma conversa ainda"
        description="Os leads aparecem aqui assim que alguém chamar a loja."
      />
    )
  } else {
    corpo = (
      <ul aria-label="Conversas" className="flex flex-col gap-1">
        {conversas.map((c) => {
          const contato = contatoDoLead(c)
          const selecionada = c.id === leadId
          return (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onSelecionar(c.id)}
                aria-current={selecionada ? "true" : undefined}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-lg border border-transparent px-3 py-2 text-left outline-none",
                  "hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
                  selecionada && "border-border bg-muted",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-foreground">{contato.titulo}</span>
                  <DonoBadge dono={c.dono === "ia" ? "ia" : "vendedor"} />
                </span>
                <span className="truncate text-xs text-muted-foreground">{contato.detalhe}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {c.aparelho_desejado ?? "Aparelho não definido"}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <section aria-label="Lista de conversas" className={cn("min-h-0 flex-col gap-2 overflow-y-auto", className)}>
      {corpo}
    </section>
  )
}
