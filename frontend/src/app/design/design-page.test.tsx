import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import DesignPage from "./page"

describe("/design (vitrine)", () => {
  it("mostra todos os componentes base em seções nomeadas", () => {
    render(<DesignPage />)
    for (const nome of [
      "Button",
      "Input, Textarea e Select",
      "Card",
      "Badge",
      "Avatar",
      "Dialog",
      "Sheet",
      "Tabs",
      "Table",
      "DataGrid",
      "Toast",
      "Skeleton",
      "EmptyState",
    ]) {
      expect(screen.getByRole("heading", { name: nome })).toBeInTheDocument()
    }
  })

  it("exibe as 5 etapas e os donos na vitrine de badges", () => {
    render(<DesignPage />)
    for (const rotulo of ["Novo contato", "Interesse identificado", "Interesse qualificado", "Com o vendedor", "Venda fechada"]) {
      expect(screen.getAllByText(rotulo).length).toBeGreaterThan(0)
    }
  })

  it("alterna entre tema claro e escuro", async () => {
    const user = userEvent.setup()
    render(<DesignPage />)
    const alternar = screen.getByRole("button", { name: /tema escuro/i })
    expect(document.documentElement).not.toHaveClass("dark")
    await user.click(alternar)
    expect(document.documentElement).toHaveClass("dark")
    await user.click(screen.getByRole("button", { name: /tema claro/i }))
    expect(document.documentElement).not.toHaveClass("dark")
  })
})
