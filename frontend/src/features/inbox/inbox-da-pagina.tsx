"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback } from "react"

import { Inbox } from "./inbox"

/** Liga a inbox à URL: `/conversas?lead=<id>` abre a conversa (o kanban linka assim). */
export function InboxDaPagina({ lojaId }: { lojaId: string }) {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const leadId = params.get("lead")

  const selecionar = useCallback(
    (id: string | null) => router.replace(id ? `${pathname}?lead=${id}` : pathname, { scroll: false }),
    [router, pathname],
  )

  return <Inbox lojaId={lojaId} leadId={leadId} onSelecionar={selecionar} />
}
