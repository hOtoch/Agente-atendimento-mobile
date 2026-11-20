import { PageHeader } from "@/components/ui/page-header"
import { ChatWeb } from "@/features/simulador/chat-web"
import { LinkCompartilhavel } from "@/features/simulador/link-compartilhavel"
import { LOJA_ID } from "@/lib/loja"

export default function Page() {
  return (
    <section>
      <PageHeader
        title="Simulador"
        description="Converse como cliente: cada conversa nova vira um lead no kanban."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
        <ChatWeb
          lojaId={LOJA_ID}
          titulo="Cliente (simulador)"
          className="mx-0 h-[calc(100dvh-14rem)] min-h-96 rounded-lg border border-border"
        />
        <div>
          <LinkCompartilhavel lojaId={LOJA_ID} />
        </div>
      </div>
    </section>
  )
}
