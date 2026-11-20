import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ETAPAS } from "@/lib/etapas"

import { Badge, DonoBadge, EtapaBadge } from "./badge"

describe("Badge", () => {
  it("renderiza o texto e aceita variantes semânticas", () => {
    render(<Badge variant="success">Ativo</Badge>)
    const badge = screen.getByText("Ativo")
    expect(badge).toHaveAttribute("data-variant", "success")
    expect(badge.className).toMatch(/success/)
  })
})

describe("EtapaBadge", () => {
  it("tem uma variante para cada uma das 5 etapas do kanban, só com tokens stage-*", () => {
    expect(ETAPAS.map((e) => e.valor)).toEqual([
      "novo_contato",
      "interesse_identificado",
      "interesse_qualificado",
      "com_o_vendedor",
      "venda_fechada",
    ])
    for (const { valor, rotulo, token } of ETAPAS) {
      const { unmount } = render(<EtapaBadge etapa={valor} />)
      const badge = screen.getByText(rotulo)
      expect(badge).toHaveAttribute("data-etapa", valor)
      expect(badge.className).toContain(`stage-${token}`)
      unmount()
    }
  })

  it("usa rótulos em pt-BR", () => {
    render(<EtapaBadge etapa="com_o_vendedor" />)
    expect(screen.getByText("Com o vendedor")).toBeInTheDocument()
  })
})

describe("DonoBadge", () => {
  it("distingue IA de vendedor", () => {
    const { rerender } = render(<DonoBadge dono="ia" />)
    expect(screen.getByText("IA")).toHaveAttribute("data-dono", "ia")
    rerender(<DonoBadge dono="vendedor" />)
    expect(screen.getByText("Vendedor")).toHaveAttribute("data-dono", "vendedor")
  })
})
