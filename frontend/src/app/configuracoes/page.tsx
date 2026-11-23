"use client"

import { PageHeader } from "@/components/ui/page-header"
import { Configuracoes } from "@/features/configuracoes/configuracoes"
import { useSessao } from "@/lib/sessao"

export default function Page() {
  const { lojaId } = useSessao()
  return (
    <section>
      <PageHeader title="Configurações" description="Preferências e regras da loja." />
      <Configuracoes lojaId={lojaId} />
    </section>
  )
}
