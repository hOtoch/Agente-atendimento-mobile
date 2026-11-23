import { cn } from "@/lib/utils"

/** Barra de proporção (0 a 1) sobre uma trilha neutra; use para "quanto de um total". */
export function Medidor({
  fracao,
  rotulo,
  className,
}: {
  fracao: number
  rotulo: string
  className?: string
}) {
  const pct = Math.round(Math.min(1, Math.max(0, fracao)) * 100)
  return (
    <div
      role="meter"
      aria-label={rotulo}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-valuetext={`${pct}%`}
      className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      <div className="h-full rounded-full bg-chart-1" style={{ width: `${pct}%` }} />
    </div>
  )
}
