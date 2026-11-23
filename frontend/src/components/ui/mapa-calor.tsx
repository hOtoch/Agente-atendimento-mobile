import { cn } from "@/lib/utils"

/** Degraus do mapa: 0 = vazio; 1 a 4 = fatias do valor máximo (uma cor, mais forte = mais). */
const NIVEIS = ["bg-muted", "bg-chart-1/20", "bg-chart-1/40", "bg-chart-1/65", "bg-chart-1"] as const

export function nivelDoMapa(valor: number, maximo: number): 0 | 1 | 2 | 3 | 4 {
  if (valor <= 0 || maximo <= 0) return 0
  const razao = valor / maximo
  if (razao <= 0.25) return 1
  if (razao <= 0.5) return 2
  if (razao <= 0.75) return 3
  return 4
}

/**
 * Mapa de calor linhas x colunas (ex.: dia da semana x hora). É uma `<table>` de verdade: leitor de
 * tela lê o número de cada célula e o mouse mostra o texto de `descreverCelula` no `title`.
 */
export function MapaCalor({
  legenda,
  linhas,
  linhasCurtas,
  colunas,
  valores,
  descreverCelula,
  className,
}: {
  /** Nome acessível da tabela (caption invisível). */
  legenda: string
  linhas: string[]
  /** Rótulos visíveis das linhas (padrão: `linhas`). */
  linhasCurtas?: string[]
  colunas: string[]
  valores: number[][]
  descreverCelula: (linha: string, coluna: string, valor: number) => string
  className?: string
}) {
  const maximo = Math.max(0, ...valores.flat())
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[30rem] table-fixed border-separate border-spacing-0.5 text-xs">
          <caption className="sr-only">{legenda}</caption>
          <thead>
            <tr>
              <th scope="col" className="w-9">
                <span className="sr-only">Dia</span>
              </th>
              {colunas.map((coluna, c) => (
                <th key={coluna} scope="col" className="font-normal text-muted-foreground">
                  <span className={cn(c % 3 !== 0 && "sr-only")}>{coluna}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {linhas.map((linha, l) => (
              <tr key={linha}>
                <th scope="row" className="pr-1 text-left font-normal text-muted-foreground">
                  <span aria-hidden="true">{linhasCurtas?.[l] ?? linha}</span>
                  <span className="sr-only">{linha}</span>
                </th>
                {colunas.map((coluna, c) => {
                  const valor = valores[l]?.[c] ?? 0
                  return (
                    <td
                      key={coluna}
                      title={descreverCelula(linha, coluna, valor)}
                      className={cn("h-5 rounded-sm", NIVEIS[nivelDoMapa(valor, maximo)])}
                    >
                      <span className="sr-only">{valor}</span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div aria-hidden="true" className="flex items-center justify-end gap-1.5 text-xs text-muted-foreground">
        Menos
        {NIVEIS.map((n) => (
          <span key={n} className={cn("size-3 rounded-sm", n)} />
        ))}
        Mais
      </div>
    </div>
  )
}
