"use client"

import type { CampoControle } from "@/components/ui/campo"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export type ItemSeletor = { value: string; label: string }

/**
 * Select de lista fechada pronto para dentro de um `Campo`:
 * `<Campo label="Tipo">{(p) => <SeletorCampo controle={p} valor={v} itens={itens} aoMudar={set} />}</Campo>`.
 */
export function SeletorCampo({
  controle,
  valor,
  itens,
  aoMudar,
}: {
  controle: CampoControle
  valor: string
  itens: ItemSeletor[]
  aoMudar: (valor: string) => void
}) {
  return (
    <Select value={valor} items={itens} onValueChange={(v) => aoMudar(String(v))}>
      <SelectTrigger
        id={controle.id}
        aria-labelledby={controle["aria-labelledby"]}
        aria-invalid={controle["aria-invalid"]}
        aria-describedby={controle["aria-describedby"]}
        className="w-full"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {itens.map((i) => (
          <SelectItem key={i.value} value={i.value}>
            {i.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
