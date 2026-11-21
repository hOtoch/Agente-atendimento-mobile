import { useId, type ComponentProps } from "react"

import { cn } from "@/lib/utils"

type Props = Omit<ComponentProps<"input">, "type" | "onChange" | "checked"> & {
  checked: boolean
  onCheckedChange: (marcado: boolean) => void
  /** Texto ao lado da caixa. Sem ele, o nome vem de `aria-labelledby` (ex.: dentro de `Campo`). */
  rotulo?: string
  /** Explicação curta abaixo do rótulo; fica ligada ao controle (`aria-describedby`). */
  descricao?: string
}

/** Caixa de seleção nativa (acessível por teclado e leitor de tela), só com tokens do tema. */
export function Checkbox({
  checked,
  onCheckedChange,
  rotulo,
  descricao,
  className,
  id,
  "aria-describedby": descritoPor,
  ...props
}: Props) {
  const base = useId()
  const idControle = id ?? `${base}-checkbox`
  const idDescricao = `${base}-descricao`
  const caixa = (
    <input
      {...props}
      id={idControle}
      type="checkbox"
      data-slot="checkbox"
      checked={checked}
      onChange={(e) => onCheckedChange(e.target.checked)}
      aria-describedby={[descritoPor, descricao ? idDescricao : null].filter(Boolean).join(" ") || undefined}
      className={cn(
        "size-4 shrink-0 cursor-pointer rounded-sm accent-primary outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
    />
  )
  if (!rotulo) return caixa
  return (
    <div data-slot="checkbox-grupo" className="flex items-start gap-2">
      <span className="mt-0.5 flex">{caixa}</span>
      <div className="flex flex-col gap-0.5">
        <label htmlFor={idControle} className="cursor-pointer text-sm font-medium">
          {rotulo}
        </label>
        {descricao ? (
          <p id={idDescricao} className="text-xs text-muted-foreground">
            {descricao}
          </p>
        ) : null}
      </div>
    </div>
  )
}
