import { render, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AppShell } from "./app-shell"
import { NAV_ITEMS } from "./nav-items"

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversas",
}))

describe("AppShell", () => {
  it("renderiza a navegação com todas as seções do painel", () => {
    render(
      <AppShell>
        <p>conteúdo</p>
      </AppShell>,
    )

    const nav = screen.getByRole("navigation", { name: /principal/i })
    for (const label of [
      "Kanban",
      "Conversas",
      "Onboarding",
      "Simulador",
      "Configurações",
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument()
    }
    expect(NAV_ITEMS).toHaveLength(5)
    expect(screen.getByText("conteúdo")).toBeInTheDocument()
  })

  it("aponta cada item para a rota correta e marca a rota ativa", () => {
    render(<AppShell>x</AppShell>)

    expect(screen.getByRole("link", { name: "Kanban" })).toHaveAttribute(
      "href",
      "/kanban",
    )
    expect(screen.getByRole("link", { name: "Conversas" })).toHaveAttribute(
      "aria-current",
      "page",
    )
    expect(screen.getByRole("link", { name: "Kanban" })).not.toHaveAttribute(
      "aria-current",
    )
  })
})
