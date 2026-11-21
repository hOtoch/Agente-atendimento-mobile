import { PageHeader } from "@/components/ui/page-header"
import { Configuracoes } from "@/features/configuracoes/configuracoes"
import { LOJA_ID } from "@/lib/loja"

export default function Page() {
  return (
    <section>
      <PageHeader title="Configurações" description="Preferências e regras da loja." />
      <Configuracoes lojaId={LOJA_ID} />
    </section>
  )
}
