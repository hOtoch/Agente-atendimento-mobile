"use client"

import { PageHeader } from "@/components/ui/page-header"
import { ChatWeb } from "@/features/simulador/chat-web"
import { LinkCompartilhavel } from "@/features/simulador/link-compartilhavel"
import { useSessao } from "@/lib/sessao"

export default function Page() {
  const { lojaId } = useSessao()
  return (
    <section>
      <PageHeader
        title="Simulador"
        description="Converse como cliente: cada conversa nova vira um lead no kanban."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
        <ChatWeb
          lojaId={lojaId}
          titulo="Cliente (simulador)"
          className="mx-0 h-[calc(100dvh-14rem)] min-h-96 rounded-lg border border-border"
        />
        <div>
          <LinkCompartilhavel lojaId={lojaId} />
        </div>
      </div>
    </section>
  )
}
