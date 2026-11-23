import { useId, type ReactNode } from "react"

const GRADES = {
  1: "grid gap-4",
  2: "grid gap-4 lg:grid-cols-2",
  4: "grid grid-cols-2 gap-3 lg:grid-cols-4",
} as const

/** Seção da tela: título (h2) e grade responsiva dos cartões. */
export function Secao({
  titulo,
  colunas = 2,
  children,
}: {
  titulo: string
  colunas?: 1 | 2 | 4
  children: ReactNode
}) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-base font-semibold">
        {titulo}
      </h2>
      <div className={GRADES[colunas]}>
        {children}
      </div>
    </section>
  )
}
