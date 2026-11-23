import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StatTile } from "./stat-tile"

describe("StatTile", () => {
  it("expõe rótulo e valor num grupo nomeado", () => {
    render(<StatTile rotulo="Conversas atendidas" valor="120" />)
    const grupo = screen.getByRole("group", { name: "Conversas atendidas" })
    expect(within(grupo).getByText("120")).toBeInTheDocument()
  })

  it("mostra a variação com tom e texto para leitor de tela", () => {
    render(
      <StatTile
        rotulo="Gasto"
        valor="US$ 15,30"
        variacao={{ texto: "+50%", tom: "ruim", direcao: "alta", descricao: "aumento de 50% em relação ao período anterior" }}
      />,
    )
    const variacao = screen.getByText("+50%").closest("[data-tom]")
    expect(variacao).toHaveAttribute("data-tom", "ruim")
    expect(screen.getByText(/aumento de 50% em relação ao período anterior/)).toHaveClass("sr-only")
  })

  it("sem variação diz que não há comparação", () => {
    render(<StatTile rotulo="Erros" valor="0" variacao={null} />)
    expect(screen.getByText("Sem comparação")).toBeInTheDocument()
  })

  it("valor nulo vira traço com a dica", () => {
    render(<StatTile rotulo="Latência" valor={null} dicaSemValor="sem medição no período" />)
    expect(screen.getByTitle("sem medição no período")).toHaveTextContent("—")
  })
})
