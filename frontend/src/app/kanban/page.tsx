"use client"

import { PageHeader } from "@/components/ui/page-header"
import { KanbanBoard } from "@/features/kanban/kanban-board"
import { useSessao } from "@/lib/sessao"

export default function Page() {
  const { lojaId } = useSessao()
  return (
    <section className="flex flex-col gap-4">
      <PageHeader title="Kanban" description="Funil de leads por etapa, atualizado em tempo real." />
      <KanbanBoard lojaId={lojaId} />
    </section>
  )
}
