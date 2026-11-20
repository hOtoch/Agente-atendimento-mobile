import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { Button } from "./button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./dialog"

function Exemplo() {
  return (
    <Dialog>
      <DialogTrigger render={<Button>Abrir</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Excluir lead</DialogTitle>
          <DialogDescription>Esta ação não pode ser desfeita.</DialogDescription>
        </DialogHeader>
        <input aria-label="Motivo" />
        <DialogFooter showCloseButton />
      </DialogContent>
    </Dialog>
  )
}

describe("Dialog", () => {
  it("abre pelo gatilho com nome e descrição acessíveis", async () => {
    const user = userEvent.setup()
    render(<Exemplo />)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Abrir" }))

    const dialog = await screen.findByRole("dialog", { name: "Excluir lead" })
    expect(dialog).toHaveAccessibleDescription("Esta ação não pode ser desfeita.")
  })

  it("move o foco para dentro ao abrir e devolve ao gatilho ao fechar", async () => {
    const user = userEvent.setup()
    render(<Exemplo />)
    const gatilho = screen.getByRole("button", { name: "Abrir" })
    await user.click(gatilho)

    const dialog = await screen.findByRole("dialog")
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))

    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await waitFor(() => expect(gatilho).toHaveFocus())
  })

  it("fecha pelo botão Fechar em pt-BR", async () => {
    const user = userEvent.setup()
    render(<Exemplo />)
    await user.click(screen.getByRole("button", { name: "Abrir" }))
    await screen.findByRole("dialog")

    await user.click(screen.getAllByRole("button", { name: "Fechar" })[0])
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })
})
