import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Campo } from "./campo"
import { Input } from "./input"

describe("Campo", () => {
  it("liga rótulo, dica e erro ao controle", () => {
    render(
      <Campo label="Nome da loja" dica="Como aparece para o cliente." erro="Informe o nome.">
        {(p) => <Input {...p} />}
      </Campo>,
    )
    const input = screen.getByLabelText("Nome da loja")
    expect(input).toHaveAttribute("aria-invalid", "true")
    expect(input).toHaveAccessibleDescription("Informe o nome. Como aparece para o cliente.")
  })

  it("sem erro nem dica o controle não fica inválido nem descrito", () => {
    render(<Campo label="Endereço">{(p) => <Input {...p} />}</Campo>)
    const input = screen.getByLabelText("Endereço")
    expect(input).not.toHaveAttribute("aria-invalid")
    expect(input).not.toHaveAttribute("aria-describedby")
  })
})
