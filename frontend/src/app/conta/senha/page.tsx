import { PageHeader } from "@/components/ui/page-header"
import { TrocarSenhaForm } from "@/features/auth/trocar-senha-form"

export default function Page() {
  return (
    <section>
      <PageHeader title="Trocar senha" description="Use uma senha que só você conhece." />
      <TrocarSenhaForm />
    </section>
  )
}
