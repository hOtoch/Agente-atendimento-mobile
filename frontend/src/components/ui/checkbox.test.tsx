import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { Campo } from "./campo"
import { Checkbox } from "./checkbox"

describe("Checkbox", () => {
  it("é uma caixa de seleção nomeada pelo rótulo e avisa a mudança", async () => {
    const aoMudar = vi.fn()
    render(<Checkbox rotulo="Responder em áudio" checked onCheckedChange={aoMudar} />)
    const caixa = screen.getByRole("checkbox", { name: "Responder em áudio" })
    expect(caixa).toBeChecked()
    await userEvent.click(caixa)
    expect(aoMudar).toHaveBeenCalledWith(false)
  })

  it("mostra a descrição ligada ao controle", () => {
    render(
      <Checkbox
        rotulo="Responder em áudio"
        descricao="O texto sempre vai junto."
        checked={false}
        onCheckedChange={() => {}}
      />,
    )
    expect(screen.getByRole("checkbox")).toHaveAccessibleDescription("O texto sempre vai junto.")
  })

  it("funciona dentro de Campo sem rótulo próprio", () => {
    render(<Campo label="Áudio">{(p) => <Checkbox {...p} checked={false} onCheckedChange={() => {}} />}</Campo>)
    expect(screen.getByRole("checkbox", { name: "Áudio" })).not.toBeChecked()
  })
})
