"use client"

import { Plus, Trash2 } from "lucide-react"
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

export type DataGridValue = string | number | null
export type DataGridRow = Record<string, DataGridValue>

export type DataGridColumn = {
  key: string
  header: string
  /** `text` (padrão), `number` (aceita vírgula decimal; valor `number | null`) ou `select`. */
  type?: "text" | "number" | "select"
  options?: { value: string; label: string }[]
  readOnly?: boolean
  align?: "left" | "right"
  /** Classe de largura (token de espaçamento), ex.: `w-32`. */
  widthClass?: string
}

export type DataGridChange = {
  rowIndex: number
  columnKey: string
  value: DataGridValue
  row: DataGridRow
}

/** Erros por célula: `{ [linha (0-based)]: { [chaveDaColuna]: mensagem } }`. */
export type DataGridErrors = Record<number, Record<string, string>>

export function errosDeCelulas(
  itens: { linha: number; coluna: string; mensagem: string }[],
): DataGridErrors {
  const erros: DataGridErrors = {}
  for (const { linha, coluna, mensagem } of itens) {
    erros[linha] = { ...erros[linha], [coluna]: mensagem }
  }
  return erros
}

export type DataGridProps = {
  "aria-label": string
  columns: DataGridColumn[]
  rows: DataGridRow[]
  onChange: (change: DataGridChange) => void
  errors?: DataGridErrors
  onAddRow?: () => void
  onRemoveRow?: (rowIndex: number) => void
  addRowLabel?: string
  emptyMessage?: string
  className?: string
}

function parseNumero(texto: string): number | null {
  const limpo = texto.trim().replace(",", ".")
  if (limpo === "") return null
  const n = Number(limpo)
  return Number.isNaN(n) ? null : n
}

function paraTexto(valor: DataGridValue | undefined): string {
  return valor === null || valor === undefined ? "" : String(valor)
}

type CellProps = {
  column: DataGridColumn
  value: DataGridValue | undefined
  label: string
  error?: string
  errorId: string
  onCommit: (value: DataGridValue) => void
}

const CAMPO =
  "h-7 rounded-md px-2 text-sm aria-invalid:border-danger aria-invalid:ring-danger/20"

function Cell({ column, value, label, error, errorId, onCommit }: CellProps) {
  // Rascunho local enquanto o campo tem foco: preserva "1," e "1.50" durante a digitação.
  const [rascunho, setRascunho] = useState<string | null>(null)
  const comum = {
    "aria-label": label,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId : undefined,
  } as const

  if (column.type === "select") {
    return (
      <select
        {...comum}
        value={paraTexto(value)}
        onChange={(e) => onCommit(e.target.value)}
        className={cn(
          CAMPO,
          "w-full border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:ring-3",
        )}
      >
        {column.options?.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }

  const numerico = column.type === "number"
  return (
    <Input
      {...comum}
      type="text"
      inputMode={numerico ? "decimal" : undefined}
      value={rascunho ?? paraTexto(value)}
      onChange={(e) => {
        setRascunho(e.target.value)
        onCommit(numerico ? parseNumero(e.target.value) : e.target.value)
      }}
      onBlur={() => setRascunho(null)}
      className={cn(CAMPO, numerico && "text-right font-mono")}
    />
  )
}

export function DataGrid({
  columns,
  rows,
  onChange,
  errors,
  onAddRow,
  onRemoveRow,
  addRowLabel = "Adicionar linha",
  emptyMessage = "Nenhuma linha.",
  className,
  ...rest
}: DataGridProps) {
  const baseId = useId()

  return (
    <div data-slot="data-grid" className={cn("flex flex-col gap-2", className)}>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table aria-label={rest["aria-label"]} className="w-full border-collapse text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={cn(
                    "h-8 border-b border-border px-2 text-left text-xs font-medium whitespace-nowrap",
                    c.align === "right" || c.type === "number" ? "text-right" : "text-left",
                    c.widthClass,
                  )}
                >
                  {c.header}
                </th>
              ))}
              {onRemoveRow ? (
                <th scope="col" className="w-10 border-b border-border">
                  <span className="sr-only">Ações</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length + (onRemoveRow ? 1 : 0)}
                  className="px-2 py-6 text-center text-muted-foreground"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : null}
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-border last:border-b-0">
                {columns.map((column) => {
                  const erro = errors?.[rowIndex]?.[column.key]
                  const errorId = `${baseId}-${rowIndex}-${column.key}-erro`
                  return (
                    <td key={column.key} className="p-1 align-top">
                      {column.readOnly ? (
                        <span
                          className={cn(
                            "block px-2 py-1 text-muted-foreground",
                            column.type === "number" && "text-right font-mono",
                          )}
                        >
                          {paraTexto(row[column.key])}
                        </span>
                      ) : (
                        <>
                          <Cell
                            column={column}
                            value={row[column.key]}
                            label={`${column.header}, linha ${rowIndex + 1}`}
                            error={erro}
                            errorId={errorId}
                            onCommit={(value) =>
                              onChange({
                                rowIndex,
                                columnKey: column.key,
                                value,
                                row: { ...row, [column.key]: value },
                              })
                            }
                          />
                          {erro ? (
                            <p id={errorId} className="mt-0.5 px-1 text-xs text-danger">
                              {erro}
                            </p>
                          ) : null}
                        </>
                      )}
                    </td>
                  )
                })}
                {onRemoveRow ? (
                  <td className="w-10 p-1 text-center align-top">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remover linha ${rowIndex + 1}`}
                      onClick={() => onRemoveRow(rowIndex)}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {onAddRow ? (
        <div>
          <Button variant="outline" size="sm" onClick={onAddRow}>
            <Plus aria-hidden="true" data-icon="inline-start" />
            {addRowLabel}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
