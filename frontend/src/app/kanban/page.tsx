import { PageHeader } from "@/components/ui/page-header"
import { KanbanBoard } from "@/features/kanban/kanban-board"

export default function Page() {
  return (
    <section className="flex flex-col gap-4">
      <PageHeader title="Kanban" description="Funil de leads por etapa, atualizado em tempo real." />
      <KanbanBoard />
    </section>
  )
}
