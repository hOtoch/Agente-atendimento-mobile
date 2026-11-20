"use client"

import { useCallback, useEffect, useState } from "react"

/**
 * "Atendendo como": sem login até o M7, o vendedor que usa o painel escolhe quem é. A escolha
 * fica no navegador (por loja). Qualquer falha de armazenamento é ignorada.
 */
const chave = (lojaId: string) => `inbox:vendedor-atual:${lojaId}`

function ler(lojaId: string): string | null {
  try {
    return window.localStorage.getItem(chave(lojaId))
  } catch {
    return null
  }
}

function gravar(lojaId: string, vendedorId: string) {
  try {
    window.localStorage.setItem(chave(lojaId), vendedorId)
  } catch {
    // armazenamento indisponível: vale só nesta sessão
  }
}

/** Vendedor atual: o guardado (se ainda ativo) ou, na falta dele, o primeiro vendedor ativo. */
export function useVendedorAtual(lojaId: string, ativos: { id: string }[]) {
  const [guardado, setGuardado] = useState<string | null>(null)

  useEffect(() => {
    // lê do navegador após a hidratação (evita divergência entre servidor e cliente)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGuardado(ler(lojaId))
  }, [lojaId])

  const vendedorId = guardado && ativos.some((v) => v.id === guardado) ? guardado : (ativos[0]?.id ?? null)

  const definir = useCallback(
    (id: string) => {
      setGuardado(id)
      gravar(lojaId, id)
    },
    [lojaId],
  )

  return { vendedorId, definir }
}
