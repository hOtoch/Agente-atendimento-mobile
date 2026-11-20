import { useId, type ReactNode } from "react"

import { cn } from "@/lib/utils"

export type CampoControle = {
  id: string
  /** Nome acessível também para controles que não são `<input>` (ex.: gatilho do Select). */
  "aria-labelledby": string
  "aria-invalid"?: true
  "aria-describedby"?: string
}

/**
 * Rótulo + controle + dica + erro, com as associações de acessibilidade já ligadas.
 * `children` recebe as props do controle: `<Campo label="Nome">{(p) => <Input {...p} />}</Campo>`.
 */
export function Campo({
  label,
  erro,
  dica,
  className,
  children,
}: {
  label: string
  erro?: string
  dica?: string
  className?: string
  children: (controle: CampoControle) => ReactNode
}) {
  const base = useId()
  const id = `${base}-campo`
  const labelId = `${base}-rotulo`
  const dicaId = `${base}-dica`
  const erroId = `${base}-erro`
  const descritoPor = [erro ? erroId : null, dica ? dicaId : null].filter(Boolean).join(" ")
  return (
    <div data-slot="campo" className={cn("flex flex-col gap-1", className)}>
      <label id={labelId} htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children({
        id,
        "aria-labelledby": labelId,
        "aria-invalid": erro ? true : undefined,
        "aria-describedby": descritoPor || undefined,
      })}
      {dica ? (
        <p id={dicaId} className="text-xs text-muted-foreground">
          {dica}
        </p>
      ) : null}
      {erro ? (
        <p id={erroId} className="text-xs text-danger">
          {erro}
        </p>
      ) : null}
    </div>
  )
}
