import { Desempenho } from "@/features/desempenho/desempenho"
import { LOJA_ID } from "@/lib/loja"

export default function Page() {
  return (
    <section>
      <Desempenho lojaId={LOJA_ID} />
    </section>
  )
}
