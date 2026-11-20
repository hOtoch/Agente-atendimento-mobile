import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { Toaster, useToast } from "./toast"

function Gatilho() {
  const toast = useToast()
  return (
    <>
      <button onClick={() => toast.erro("Arrasto proibido", { descricao: "Só o vendedor move para Venda fechada." })}>
        proibir
      </button>
      <button onClick={() => toast.sucesso("Salvo")}>salvar</button>
    </>
  )
}

describe("Toast", () => {
  it("mostra a mensagem e a descrição pelo hook useToast", async () => {
    const user = userEvent.setup()
    render(
      <>
        <Toaster />
        <Gatilho />
      </>,
    )
    await user.click(screen.getByRole("button", { name: "proibir" }))
    expect(await screen.findByText("Arrasto proibido")).toBeInTheDocument()
    expect(screen.getByText("Só o vendedor move para Venda fechada.")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "salvar" }))
    expect(await screen.findByText("Salvo")).toBeInTheDocument()
  })

  it("o contêiner de avisos é uma região acessível", () => {
    render(<Toaster />)
    expect(screen.getByRole("region", { name: /notificações/i })).toBeInTheDocument()
  })
})
