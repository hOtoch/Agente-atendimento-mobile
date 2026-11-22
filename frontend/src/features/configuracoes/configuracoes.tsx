"use client"

import type { Cliente } from "@/features/onboarding/grades"
import { api } from "@/lib/api"

import { ErpConfig } from "./erp-config"
import { FollowupConfig } from "./followup-config"

/** Tela Configurações: preferências da loja que não fazem parte do onboarding. */
export function Configuracoes({ lojaId, cliente = api }: { lojaId: string; cliente?: Cliente }) {
  return (
    <div className="flex flex-col gap-6">
      <FollowupConfig cliente={cliente} lojaId={lojaId} />
      <ErpConfig cliente={cliente} lojaId={lojaId} />
    </div>
  )
}
