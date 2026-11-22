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

function muitas(n: number): DataGridRow[] {
  return Array.from({ length: n }, (_, i) => ({
    modelo: i % 10 === 0 ? `Galáxia ${i + 1}` : `iPhone ${i + 1}`,
    taxa: i,
    bandeira: i % 2 === 0 ? "visa" : "master",
    codigo: `C${i + 1}`,
  }))
}

function GradeControlada({
  inicial,
  aoMudar,
  aoRemover,
}: {
  inicial: DataGridRow[]
  aoMudar?: (rowIndex: number) => void
  aoRemover?: (rowIndex: number) => void
}) {
  const [rows, setRows] = useState(inicial)
  return (
    <DataGrid
      aria-label="Taxas"
      columns={colunas}
      rows={rows}
      pageSize={10}
      filterable
      onChange={({ rowIndex, row }) => {
        aoMudar?.(rowIndex)
        setRows((a) => a.map((r, i) => (i === rowIndex ? row : r)))
      }}
      onAddRow={() => setRows((a) => [...a, { modelo: "", taxa: null, bandeira: "visa", codigo: "" }])}
      onRemoveRow={(i) => {
        aoRemover?.(i)
        setRows((a) => a.filter((_, j) => j !== i))
      }}
    />
  )
}

describe("DataGrid paginada e filtrável", () => {
  it("mostra só a página atual e navega entre páginas", async () => {
    const user = userEvent.setup()
    render(<GradeControlada inicial={muitas(25)} />)
    expect(screen.getAllByRole("textbox", { name: /^Modelo, linha/ })).toHaveLength(10)
    expect(screen.getByText("Mostrando 1–10 de 25")).toBeInTheDocument()
    expect(screen.getByText("Página 1 de 3")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled()

    await user.click(screen.getByRole("button", { name: "Próxima página" }))
    expect(screen.getByText("Mostrando 11–20 de 25")).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "Modelo, linha 12" })).toHaveValue("iPhone 12")

    await user.click(screen.getByRole("button", { name: "Próxima página" }))
    expect(screen.getAllByRole("textbox", { name: /^Modelo, linha/ })).toHaveLength(5)
    expect(screen.getByRole("button", { name: "Próxima página" })).toBeDisabled()
  })

  it("sem pageSize não pagina nem mostra filtro", () => {
    render(<DataGrid aria-label="Taxas" columns={colunas} rows={muitas(25)} onChange={() => {}} />)
    expect(screen.getAllByRole("textbox", { name: /^Modelo, linha/ })).toHaveLength(25)
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument()
    expect(screen.queryByText(/^Página/)).not.toBeInTheDocument()
  })

  it("filtra sem acento e sem caixa em todas as colunas, inclusive pelo rótulo do select", async () => {
    const user = userEvent.setup()
    render(<GradeControlada inicial={muitas(25)} />)
    const busca = screen.getByRole("searchbox", { name: "Filtrar Taxas" })

    await user.type(busca, "galaxia")
    expect(screen.getAllByRole("textbox", { name: /^Modelo, linha/ })).toHaveLength(3)
    expect(screen.getByText("3 de 25 linhas")).toBeInTheDocument()

    await user.clear(busca)
    await user.type(busca, "mastercard")
    expect(screen.getByText("Mostrando 1–10 de 12")).toBeInTheDocument()

    await user.clear(busca)
    await user.type(busca, "nada assim")
    expect(screen.getByText("Nenhuma linha corresponde ao filtro.")).toBeInTheDocument()
  })

  it("edita e remove pela posição global da linha, mesmo filtrada ou na página 2", async () => {
    const user = userEvent.setup()
    const aoMudar = vi.fn()
    const aoRemover = vi.fn()
    render(<GradeControlada inicial={muitas(25)} aoMudar={aoMudar} aoRemover={aoRemover} />)

    await user.click(screen.getByRole("button", { name: "Próxima página" }))
    await user.type(screen.getByRole("textbox", { name: "Modelo, linha 12" }), "X")
    expect(aoMudar).toHaveBeenLastCalledWith(11)

    await user.type(screen.getByRole("searchbox", { name: "Filtrar Taxas" }), "galaxia")
    await user.click(screen.getByRole("button", { name: "Remover linha 21" }))
    expect(aoRemover).toHaveBeenCalledWith(20)
  })

  it("editar uma célula não tira a linha do filtro enquanto digita", async () => {
    const user = userEvent.setup()
    render(<GradeControlada inicial={muitas(25)} />)
    await user.type(screen.getByRole("searchbox", { name: "Filtrar Taxas" }), "galaxia 11")
    const campo = screen.getByRole("textbox", { name: "Modelo, linha 11" })
    await user.clear(campo)
    await user.type(campo, "Outro")
    expect(screen.getByRole("textbox", { name: "Modelo, linha 11" })).toHaveValue("Outro")
  })

  it("erros novos levam à página do primeiro erro e limpam o filtro", () => {
    const rows = muitas(25)
    const props = { "aria-label": "Taxas", columns: colunas, rows, pageSize: 10, filterable: true }
    const { rerender } = render(<DataGrid {...props} onChange={() => {}} />)
    rerender(<DataGrid {...props} onChange={() => {}} errors={{ 22: { taxa: "Negativa" } }} />)
    expect(screen.getByText("Página 3 de 3")).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "Taxa (%), linha 23" })).toHaveAttribute(
      "aria-invalid",
      "true",
    )
    expect(screen.getByText("Negativa")).toBeInTheDocument()
  })

  it("linha nova aparece na última página, sem filtro", async () => {
    const user = userEvent.setup()
    render(<GradeControlada inicial={muitas(25)} />)
    await user.type(screen.getByRole("searchbox", { name: "Filtrar Taxas" }), "galaxia")
    await user.click(screen.getByRole("button", { name: "Adicionar linha" }))
    expect(screen.getByRole("searchbox", { name: "Filtrar Taxas" })).toHaveValue("")
    expect(screen.getByText("Página 3 de 3")).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "Modelo, linha 26" })).toHaveValue("")
  })
})
