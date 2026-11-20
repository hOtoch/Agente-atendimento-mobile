import { Suspense } from "react"

import { PageHeader } from "@/components/ui/page-header"
import { InboxDaPagina } from "@/features/inbox/inbox-da-pagina"
import { LOJA_ID } from "@/lib/loja"

export default function Page() {
  return (
    <section>
      <PageHeader
        title="Conversas"
        description="Acompanhe os atendimentos, assuma uma conversa ou devolva para a IA."
      />
      <Suspense fallback={null}>
        <InboxDaPagina lojaId={LOJA_ID} />
      </Suspense>
    </section>
  )
}
