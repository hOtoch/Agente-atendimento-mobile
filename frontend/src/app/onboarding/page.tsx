import { Suspense } from "react"

import { PageHeader } from "@/components/ui/page-header"
import { Onboarding } from "@/features/onboarding/onboarding"
import { LOJA_ID } from "@/lib/loja"

export default function Page() {
  return (
    <section>
      <PageHeader
        title="Onboarding"
        description="Coloque a loja no ar em poucos passos. O que você salva vale já na próxima mensagem."
      />
      <Suspense fallback={null}>
        <Onboarding lojaId={LOJA_ID} />
      </Suspense>
    </section>
  )
}
