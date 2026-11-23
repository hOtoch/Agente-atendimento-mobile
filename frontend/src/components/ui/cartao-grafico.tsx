import { useId, type ReactNode } from "react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"

export type TabelaDeDados = {
  colunas: string[]
  linhas: (string | number | null)[][]
}

/**
 * Moldura de um gráfico: título (h3), descrição curta e a alternativa em tabela (`<details>`).
 * O gráfico em si é decorativo para leitor de tela; a tabela traz os mesmos números.
 */
export function CartaoGrafico({
  titulo,
  descricao,
  tabela,
  children,
  className,
}: {
  titulo: string
  descricao: string
  tabela?: TabelaDeDados
  children: ReactNode
  className?: string
}) {
  const id = useId()
  return (
    <Card data-slot="cartao-grafico" role="region" aria-labelledby={id} className={cn("min-w-0", className)}>
      <CardHeader>
        <CardTitle>
          <h3 id={id}>{titulo}</h3>
        </CardTitle>
        <CardDescription>{descricao}</CardDescription>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {children}
        {tabela ? (
          <details className="group text-sm">
            <summary className="w-fit cursor-pointer rounded-sm text-xs text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
              Ver dados em tabela
            </summary>
            <div className="mt-2 max-h-64 overflow-auto rounded-md border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {tabela.colunas.map((coluna, i) => (
                      <TableHead key={coluna} className={cn(i > 0 && "text-right")}>
                        {coluna}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tabela.linhas.map((linha, r) => (
                    <TableRow key={r}>
                      {linha.map((celula, c) => (
                        <TableCell key={c} className={cn(c > 0 && "text-right font-mono tabular-nums")}>
                          {celula ?? "—"}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </details>
        ) : null}
      </CardContent>
    </Card>
  )
}
