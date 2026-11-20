import { render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AppShell } from "./app-shell"
import { NAV_ITEMS } from "./nav-items"

const rota = vi.hoisted(() => ({ atual: "/conversas" }))

vi.mock("next/navigation", () => ({
  usePathname: () => rota.atual,
}))

beforeEach(() => {
  rota.atual = "/conversas"
})

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

  it("nas rotas públicas /chat renderiza só o conteúdo, sem navegação do painel", () => {
    rota.atual = "/chat/00000000-0000-4000-8000-00000000de30"
    render(
      <AppShell>
        <p>chat público</p>
      </AppShell>,
    )

    expect(screen.getByText("chat público")).toBeInTheDocument()
    expect(screen.queryByRole("navigation")).toBeNull()
    expect(screen.queryByText("Atendimento Mobile")).toBeNull()
  })

  it("não confunde rotas do painel parecidas com /chat", () => {
    rota.atual = "/chatx"
    render(<AppShell>x</AppShell>)
    expect(screen.getByRole("navigation", { name: /principal/i })).toBeInTheDocument()
  })
})
