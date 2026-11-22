import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { Campo } from "./campo"
import { SeletorCampo } from "./seletor-campo"

const ITENS = [
  { value: "sim", label: "Sim" },
  { value: "nao", label: "Não" },
]

describe("SeletorCampo", () => {
  it("dentro de um Campo, mostra o rótulo do valor e leva o nome acessível do Campo", () => {
    render(
      <Campo label="Aceita?">
        {(p) => <SeletorCampo controle={p} valor="nao" itens={ITENS} aoMudar={() => {}} />}
      </Campo>,
    )
    const gatilho = screen.getByRole("combobox", { name: "Aceita?" })
    expect(gatilho).toHaveTextContent("Não")
  })

  it("escolher uma opção chama aoMudar com o valor", async () => {
    const aoMudar = vi.fn()
    render(
      <Campo label="Aceita?">
        {(p) => <SeletorCampo controle={p} valor="nao" itens={ITENS} aoMudar={aoMudar} />}
      </Campo>,
    )
    await userEvent.click(screen.getByRole("combobox", { name: "Aceita?" }))
    await userEvent.click(await screen.findByRole("option", { name: "Sim" }))
    expect(aoMudar).toHaveBeenCalledWith("sim")
  })

  it("erro do Campo marca o gatilho como inválido", () => {
    render(
      <Campo label="Aceita?" erro="Obrigatório">
        {(p) => <SeletorCampo controle={p} valor="sim" itens={ITENS} aoMudar={() => {}} />}
      </Campo>,
    )
    expect(screen.getByRole("combobox", { name: "Aceita?" })).toHaveAttribute("aria-invalid", "true")
  })
})
