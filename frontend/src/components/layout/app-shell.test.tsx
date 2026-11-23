import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AppShell } from "./app-shell"
import { NAV_ITEMS } from "./nav-items"

const rota = vi.hoisted(() => ({ atual: "/conversas", sair: vi.fn() }))

vi.mock("@/lib/sessao", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/sessao")>()),
  useSessao: () => ({ lojaNome: "Loja Demo", email: "dono@loja.com", sair: rota.sair }),
}))

vi.mock("next/navigation", () => ({
  usePathname: () => rota.atual,
}))

beforeEach(() => {
  rota.atual = "/conversas"
  rota.sair.mockReset()
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
      "Desempenho",
      "Configurações",
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument()
    }
    expect(NAV_ITEMS).toHaveLength(6)
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

  it("o item Desempenho leva para /desempenho", () => {
    render(<AppShell>x</AppShell>)
    expect(screen.getByRole("link", { name: "Desempenho" })).toHaveAttribute("href", "/desempenho")
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

  it("mostra o nome da loja da sessão, o item Trocar senha e o botão Sair", async () => {
    render(<AppShell>x</AppShell>)
    expect(screen.getByText("Loja Demo")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Trocar senha" })).toHaveAttribute("href", "/conta/senha")
    await userEvent.click(screen.getByRole("button", { name: "Sair" }))
    expect(rota.sair).toHaveBeenCalledTimes(1)
  })

  it("a barra lateral fica presa à altura da tela, para Sair ficar visível em páginas longas", () => {
    render(<AppShell>x</AppShell>)
    const barra = screen.getByRole("complementary")
    expect(barra).toHaveClass("sticky", "top-0", "h-screen")
    expect(within(barra).getByRole("button", { name: "Sair" })).toBeInTheDocument()
  })

  it("na tela de login renderiza só o conteúdo, sem barra lateral", () => {
    rota.atual = "/login"
    render(<AppShell>entrar</AppShell>)
    expect(screen.getByText("entrar")).toBeInTheDocument()
    expect(screen.queryByRole("navigation")).toBeNull()
    expect(screen.queryByRole("button", { name: "Sair" })).toBeNull()
  })
})
