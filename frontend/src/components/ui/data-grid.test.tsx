import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { describe, expect, it, vi } from "vitest"

import { DataGrid, errosDeCelulas, type DataGridColumn, type DataGridRow } from "./data-grid"

const colunas: DataGridColumn[] = [
  { key: "modelo", header: "Modelo", type: "text" },
  { key: "taxa", header: "Taxa (%)", type: "number" },
  {
    key: "bandeira",
    header: "Bandeira",
    type: "select",
    options: [
      { value: "visa", label: "Visa" },
      { value: "master", label: "Mastercard" },
    ],
  },
  { key: "codigo", header: "Código", type: "text", readOnly: true },
]

const linhas: DataGridRow[] = [
  { modelo: "iPhone 15", taxa: 2.5, bandeira: "visa", codigo: "A1" },
  { modelo: "iPhone 14", taxa: 3, bandeira: "master", codigo: "A2" },
]

describe("DataGrid", () => {
  it("expõe uma tabela nomeada com cabeçalhos e uma célula editável por coluna", () => {
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={linhas} onChange={() => {}} />)
    const tabela = screen.getByRole("table", { name: "Taxas" })
    for (const h of ["Modelo", "Taxa (%)", "Bandeira", "Código"]) {
      expect(within(tabela).getByRole("columnheader", { name: h })).toBeInTheDocument()
    }
    expect(screen.getByRole("textbox", { name: "Modelo, linha 1" })).toHaveValue("iPhone 15")
    expect(screen.getByRole("textbox", { name: "Taxa (%), linha 1" })).toHaveValue("2.5")
    expect(screen.getByRole("combobox", { name: "Bandeira, linha 2" })).toHaveValue("master")
  })

  it("coluna readOnly não vira campo editável", () => {
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={linhas} onChange={() => {}} />)
    expect(screen.queryByRole("textbox", { name: "Código, linha 1" })).not.toBeInTheDocument()
    expect(screen.getByRole("cell", { name: "A1" })).toBeInTheDocument()
  })

  it("edita uma célula de texto e avisa onChange com linha, coluna e valor", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={linhas} onChange={onChange} />)

    const campo = screen.getByRole("textbox", { name: "Modelo, linha 2" })
    await user.clear(campo)
    expect(onChange).toHaveBeenLastCalledWith({
      rowIndex: 1,
      columnKey: "modelo",
      value: "",
      row: expect.objectContaining({ modelo: "" }),
    })
    await user.type(campo, "X")
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowIndex: 1, columnKey: "modelo", value: "X" }),
    )
  })

  it("coluna numérica entrega número (aceita vírgula) ou null quando vazia", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={linhas} onChange={onChange} />)

    const campo = screen.getByRole("textbox", { name: "Taxa (%), linha 1" })
    await user.clear(campo)
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ columnKey: "taxa", value: null }))
    await user.type(campo, "4,75")
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ columnKey: "taxa", value: 4.75 }))
  })

  it("select de coluna tipada notifica o valor escolhido", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={linhas} onChange={onChange} />)
    await user.selectOptions(screen.getByRole("combobox", { name: "Bandeira, linha 1" }), "master")
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowIndex: 0, columnKey: "bandeira", value: "master" }),
    )
  })

  it("exibe erro por célula com aria-invalid e mensagem associada", () => {
    render(
      <DataGrid
        aria-label="Taxas"
        columns={colunas}
        rows={linhas}
        errors={{ 1: { taxa: "Taxa inválida" } }}
        onChange={() => {}}
      />,
    )
    const invalida = screen.getByRole("textbox", { name: "Taxa (%), linha 2" })
    expect(invalida).toHaveAttribute("aria-invalid", "true")
    expect(invalida).toHaveAccessibleDescription("Taxa inválida")
    expect(screen.getByText("Taxa inválida")).toBeInTheDocument()

    const valida = screen.getByRole("textbox", { name: "Taxa (%), linha 1" })
    expect(valida).not.toHaveAttribute("aria-invalid", "true")
  })

  it("errosDeCelulas agrupa erros da API por linha e coluna", () => {
    expect(
      errosDeCelulas([
        { linha: 0, coluna: "modelo", mensagem: "Obrigatório" },
        { linha: 2, coluna: "taxa", mensagem: "Negativa" },
        { linha: 2, coluna: "bandeira", mensagem: "Desconhecida" },
      ]),
    ).toEqual({
      0: { modelo: "Obrigatório" },
      2: { taxa: "Negativa", bandeira: "Desconhecida" },
    })
  })

  it("adiciona e remove linhas por callbacks", async () => {
    const user = userEvent.setup()
    const onAddRow = vi.fn()
    const onRemoveRow = vi.fn()
    render(
      <DataGrid
        aria-label="Taxas"
        columns={colunas}
        rows={linhas}
        onChange={() => {}}
        onAddRow={onAddRow}
        onRemoveRow={onRemoveRow}
      />,
    )
    await user.click(screen.getByRole("button", { name: "Adicionar linha" }))
    expect(onAddRow).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole("button", { name: "Remover linha 2" }))
    expect(onRemoveRow).toHaveBeenCalledWith(1)
  })

  it("sem callbacks de linha não mostra botões de adicionar/remover", () => {
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={linhas} onChange={() => {}} />)
    expect(screen.queryByRole("button", { name: "Adicionar linha" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Remover linha/ })).not.toBeInTheDocument()
  })

  it("mostra estado vazio quando não há linhas", () => {
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={[]} onChange={() => {}} emptyMessage="Nenhuma taxa" />)
    expect(screen.getByText("Nenhuma taxa")).toBeInTheDocument()
  })

  it("funciona controlado por estado do pai", async () => {
    const user = userEvent.setup()
    function Pai() {
      const [rows, setRows] = useState<DataGridRow[]>(linhas)
      return (
        <DataGrid
          aria-label="Taxas"
          columns={colunas}
          rows={rows}
          onChange={({ rowIndex, columnKey, value }) =>
            setRows((atual) => atual.map((r, i) => (i === rowIndex ? { ...r, [columnKey]: value } : r)))
          }
          onAddRow={() => setRows((a) => [...a, { modelo: "", taxa: null, bandeira: "visa", codigo: "" }])}
        />
      )
    }
    render(<Pai />)
    const campo = screen.getByRole("textbox", { name: "Taxa (%), linha 1" })
    await user.clear(campo)
    await user.type(campo, "1,5")
    expect(campo).toHaveValue("1,5")
    await user.tab()
    expect(campo).toHaveValue("1.5")
    await user.click(screen.getByRole("button", { name: "Adicionar linha" }))
    expect(screen.getAllByRole("textbox", { name: /^Modelo, linha/ })).toHaveLength(3)
  })
})
