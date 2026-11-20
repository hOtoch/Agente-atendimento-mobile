"use client"

import { Copy } from "lucide-react"
import { useSyncExternalStore } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useToast } from "@/components/ui/toast"

const semAssinatura = () => () => {}

/** Link público `/chat/{loja}` (sem login) para o avaliador abrir no celular. */
export function LinkCompartilhavel({ lojaId }: { lojaId: string }) {
  const toast = useToast()
  // A origem só existe no navegador: "" no servidor, valor real após hidratar.
  const origem = useSyncExternalStore(semAssinatura, () => window.location.origin, () => "")

  const link = `${origem}/chat/${lojaId}`

  async function copiar() {
    try {
      await navigator.clipboard.writeText(link)
      toast.sucesso("Link copiado.")
    } catch {
      toast.erro("Não foi possível copiar o link.")
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="link-chat" className="text-sm font-medium">
        Link para o avaliador (sem login)
      </label>
      <div className="flex gap-2">
        <Input id="link-chat" readOnly value={link} className="min-w-0 flex-1 font-mono" />
        <Button variant="outline" onClick={() => void copiar()}>
          <Copy aria-hidden /> Copiar link
        </Button>
      </div>
    </div>
  )
}
