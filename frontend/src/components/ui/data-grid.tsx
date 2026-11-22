"use client"

import { ChevronLeft, ChevronRight, Plus, Search, Trash2 } from "lucide-react"
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
  /** Linhas por página; sem ele a grade mostra tudo. Os índices dos callbacks seguem globais. */
  pageSize?: number
  /** Mostra um campo que filtra as linhas pelo texto de qualquer coluna (sem acento e caixa). */
  filterable?: boolean
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

function normalizar(texto: string): string {
  return texto.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase()
}

function textoDaCelula(coluna: DataGridColumn, valor: DataGridValue | undefined): string {
  if (coluna.type === "select") {
    return coluna.options?.find((o) => o.value === valor)?.label ?? paraTexto(valor)
  }
  return paraTexto(valor)
}

/** Índices (globais) das linhas que contêm o filtro em alguma coluna. */
function filtrarIndices(rows: DataGridRow[], columns: DataGridColumn[], filtro: string): number[] {
  const alvo = normalizar(filtro.trim())
  return rows.flatMap((row, i) =>
    !alvo || columns.some((c) => normalizar(textoDaCelula(c, row[c.key])).includes(alvo)) ? [i] : [],
  )
}

function linhasComErro(errors: DataGridErrors | undefined): number[] {
  return Object.entries(errors ?? {})
    .filter(([, porColuna]) => Object.keys(porColuna).length > 0)
    .map(([linha]) => Number(linha))
}

const NUMERO = new Intl.NumberFormat("pt-BR")

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
  pageSize,
  filterable = false,
  ...rest
}: DataGridProps) {
  const baseId = useId()
  const paginada = pageSize !== undefined && pageSize > 0
  const porPagina = paginada ? pageSize : Math.max(rows.length, 1)
  const [filtro, setFiltro] = useState("")
  const [pagina, setPagina] = useState(0)
  const [irParaFim, setIrParaFim] = useState(false)
  const [errosVistos, setErrosVistos] = useState(errors)
  // A lista filtrada só muda com o filtro ou o número de linhas: editar uma célula não esconde a
  // linha que está sendo digitada. Os ajustes abaixo são estado derivado durante a renderização.
  const [visao, setVisao] = useState(() => ({
    filtro: "",
    total: rows.length,
    indices: rows.map((_, i) => i),
  }))

  if (irParaFim && rows.length !== visao.total) {
    setIrParaFim(false)
    setPagina(Math.max(0, Math.ceil(rows.length / porPagina) - 1))
  }
  if (errors !== errosVistos) {
    setErrosVistos(errors)
    const antes = new Set(linhasComErro(errosVistos))
    const agora = linhasComErro(errors)
    if (paginada && agora.some((linha) => !antes.has(linha))) {
      // Erros novos (ex.: depois de salvar): mostra o primeiro, mesmo que esteja em outra página.
      setFiltro("")
      setPagina(Math.floor(Math.min(...agora) / porPagina))
    }
  }
  let indices = visao.indices
  if (visao.filtro !== filtro || visao.total !== rows.length) {
    indices = filtrarIndices(rows, columns, filtro)
    setVisao({ filtro, total: rows.length, indices })
  }

  const totalPaginas = Math.max(1, Math.ceil(indices.length / porPagina))
  const paginaAtual = Math.min(pagina, totalPaginas - 1)
  const inicio = paginaAtual * porPagina
  const visiveis = indices.slice(inicio, inicio + porPagina).filter((i) => i < rows.length)
  const filtrando = filtro.trim() !== ""

  return (
    <div data-slot="data-grid" className={cn("flex flex-col gap-2", className)}>
      {filterable ? (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              aria-label={`Filtrar ${rest["aria-label"]}`}
              placeholder="Filtrar…"
              value={filtro}
              onChange={(e) => {
                setFiltro(e.target.value)
                setPagina(0)
              }}
              className="h-8 pl-8"
            />
          </div>
          {filtrando ? (
            <span className="text-sm text-muted-foreground">
              {NUMERO.format(indices.length)} de {NUMERO.format(rows.length)} linhas
            </span>
          ) : null}
        </div>
      ) : null}
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
            {visiveis.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length + (onRemoveRow ? 1 : 0)}
                  className="px-2 py-6 text-center text-muted-foreground"
                >
                  {rows.length === 0 ? emptyMessage : "Nenhuma linha corresponde ao filtro."}
                </td>
              </tr>
            ) : null}
            {visiveis.map((rowIndex) => {
              const row = rows[rowIndex]
              return (
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
              )
            })}
          </tbody>
        </table>
      </div>
      {paginada && indices.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>
            Mostrando {NUMERO.format(inicio + 1)}–{NUMERO.format(inicio + visiveis.length)} de{" "}
            {NUMERO.format(indices.length)}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Página anterior"
              disabled={paginaAtual === 0}
              onClick={() => setPagina(paginaAtual - 1)}
            >
              <ChevronLeft aria-hidden="true" />
            </Button>
            <span>
              Página {NUMERO.format(paginaAtual + 1)} de {NUMERO.format(totalPaginas)}
            </span>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Próxima página"
              disabled={paginaAtual >= totalPaginas - 1}
              onClick={() => setPagina(paginaAtual + 1)}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </div>
        </div>
      ) : null}
      {onAddRow ? (
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              if (paginada || filterable) {
                setFiltro("")
                setIrParaFim(true)
              }
              onAddRow()
            }}
          >
            <Plus aria-hidden="true" data-icon="inline-start" />
            {addRowLabel}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
