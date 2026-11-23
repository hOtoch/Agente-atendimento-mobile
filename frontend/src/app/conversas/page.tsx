"use client"

import { Suspense } from "react"

import { PageHeader } from "@/components/ui/page-header"
import { InboxDaPagina } from "@/features/inbox/inbox-da-pagina"
import { useSessao } from "@/lib/sessao"

export default function Page() {
  const { lojaId } = useSessao()
  return (
    <section>
      <PageHeader
        title="Conversas"
        description="Acompanhe os atendimentos, assuma uma conversa ou devolva para a IA."
      />
      <Suspense fallback={null}>
        <InboxDaPagina lojaId={lojaId} />
      </Suspense>
    </section>
  )
}
