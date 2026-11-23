import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { MapaCalor, nivelDoMapa } from "./mapa-calor"

describe("nivelDoMapa", () => {
  it("zero é sempre o nível 0, mesmo quando o máximo é zero", () => {
    expect(nivelDoMapa(0, 10)).toBe(0)
    expect(nivelDoMapa(0, 0)).toBe(0)
  })

  it("divide o resto em 4 degraus proporcionais ao máximo", () => {
    expect(nivelDoMapa(1, 100)).toBe(1)
    expect(nivelDoMapa(40, 100)).toBe(2)
    expect(nivelDoMapa(60, 100)).toBe(3)
    expect(nivelDoMapa(100, 100)).toBe(4)
  })
})

describe("MapaCalor", () => {
  it("é uma tabela com legenda, uma linha por rótulo e um título em cada célula", () => {
    render(
      <MapaCalor
        legenda="Mapa de teste"
        linhas={["A", "B"]}
        colunas={["0h", "1h", "2h"]}
        valores={[
          [0, 5, 10],
          [1, 0, 0],
        ]}
        descreverCelula={(l, c, v) => `${l} ${c}: ${v}`}
      />,
    )
    const tabela = screen.getByRole("table", { name: "Mapa de teste" })
    expect(within(tabela).getAllByRole("row")).toHaveLength(3)
    expect(within(tabela).getByTitle("A 2h: 10")).toBeInTheDocument()
    expect(within(tabela).getByTitle("B 1h: 0")).toBeInTheDocument()
  })
})
