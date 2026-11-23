"use client"

import { Desempenho } from "@/features/desempenho/desempenho"
import { useSessao } from "@/lib/sessao"

export default function Page() {
  const { lojaId } = useSessao()
  return (
    <section>
      <Desempenho lojaId={lojaId} />
    </section>
  )
}
