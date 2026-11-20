import { render, screen } from "@testing-library/react"
import { Inbox } from "lucide-react"
import { describe, expect, it } from "vitest"

import { Button } from "./button"
import { EmptyState } from "./empty-state"

describe("EmptyState", () => {
  it("mostra título, descrição e ação, com ícone decorativo", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="Nenhuma conversa"
        description="Quando um cliente escrever, ela aparece aqui."
        action={<Button>Abrir simulador</Button>}
      />,
    )
    expect(screen.getByRole("heading", { name: "Nenhuma conversa" })).toBeInTheDocument()
    expect(screen.getByText("Quando um cliente escrever, ela aparece aqui.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Abrir simulador" })).toBeInTheDocument()
    expect(document.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
  })

  it("funciona só com título", () => {
    render(<EmptyState title="Vazio" />)
    expect(screen.getByRole("heading", { name: "Vazio" })).toBeInTheDocument()
  })
})
