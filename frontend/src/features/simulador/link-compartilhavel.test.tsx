import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { LinkCompartilhavel } from "./link-compartilhavel"

const LOJA = "11111111-1111-1111-1111-111111111111"
const sucesso = vi.fn()
const erro = vi.fn()
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ sucesso, erro, aviso: vi.fn(), info: vi.fn(), fechar: vi.fn() }),
}))

beforeEach(() => {
  sucesso.mockReset()
  erro.mockReset()
})

describe("LinkCompartilhavel", () => {
  it("mostra o link público /chat/{loja} na origem atual", () => {
    render(<LinkCompartilhavel lojaId={LOJA} />)
    expect(screen.getByRole("textbox", { name: /link/i })).toHaveValue(
      `${window.location.origin}/chat/${LOJA}`,
    )
  })

  it("copia o link para a área de transferência e avisa", async () => {
    const user = userEvent.setup()
    const escrever = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined)
    render(<LinkCompartilhavel lojaId={LOJA} />)

    await user.click(screen.getByRole("button", { name: /copiar/i }))

    expect(escrever).toHaveBeenCalledWith(`${window.location.origin}/chat/${LOJA}`)
    await waitFor(() => expect(sucesso).toHaveBeenCalled())
  })

  it("avisa quando não consegue copiar", async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("negado"))
    render(<LinkCompartilhavel lojaId={LOJA} />)
    await user.click(screen.getByRole("button", { name: /copiar/i }))
    await waitFor(() => expect(erro).toHaveBeenCalled())
  })
})
