"use client"

import { Suspense } from "react"

import { PageHeader } from "@/components/ui/page-header"
import { Onboarding } from "@/features/onboarding/onboarding"
import { useSessao } from "@/lib/sessao"

export default function Page() {
  const { lojaId } = useSessao()
  return (
    <section>
      <PageHeader
        title="Onboarding"
        description="Coloque a loja no ar em poucos passos. O que você salva vale já na próxima mensagem."
      />
      <Suspense fallback={null}>
        <Onboarding lojaId={lojaId} />
      </Suspense>
    </section>
  )
}
