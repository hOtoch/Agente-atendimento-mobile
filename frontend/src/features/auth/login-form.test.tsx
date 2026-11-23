import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { LoginForm } from "./login-form"

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  volta: null as string | null,
  definir: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => ({ get: (k: string) => (k === "volta" ? mocks.volta : null) }),
}))

vi.mock("@/lib/sessao", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/sessao")>()),
  useSessao: () => ({ definirIdentidade: mocks.definir }),
}))

const IDENTIDADE = {
  loja_id: "00000000-0000-4000-8000-00000000de30",
  loja_nome: "Loja Demo",
  email: "dono@loja.com",
  senha_provisoria: false,
}

const cliente = { POST: vi.fn() }

function ok() {
  cliente.POST.mockResolvedValue({ data: IDENTIDADE, response: new Response(null, { status: 200 }) })
}

function falha(status: number, headers: Record<string, string> = {}) {
  cliente.POST.mockResolvedValue({
    error: { erros: [{ caminho: "credenciais", mensagem: "Credenciais inválidas." }] },
    response: new Response(null, { status, headers }),
  })
}

async function entrar() {
  render(<LoginForm cliente={cliente as never} />)
  await userEvent.type(screen.getByLabelText("E-mail"), "dono@loja.com")
  await userEvent.type(screen.getByLabelText("Senha"), "segredo-12345")
  await userEvent.click(screen.getByRole("button", { name: "Entrar" }))
}

beforeEach(() => {
  mocks.replace.mockReset()
  mocks.definir.mockReset()
  mocks.volta = null
  cliente.POST.mockReset()
})

describe("LoginForm", () => {
  it("login ok envia e-mail e senha, guarda a identidade e vai para o kanban", async () => {
    ok()
    await entrar()

    expect(cliente.POST).toHaveBeenCalledWith("/auth/login", {
      body: { email: "dono@loja.com", senha: "segredo-12345" },
    })
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/kanban"))
    expect(mocks.definir).toHaveBeenCalledWith(IDENTIDADE)
  })

  it("volta para a rota pedida em `volta`", async () => {
    mocks.volta = "/conversas?lead=1"
    ok()
    await entrar()
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/conversas?lead=1"))
  })

  it.each(["https://evil.com/x", "//evil.com"])("`volta` externo (%s) é ignorado", async (externo) => {
    mocks.volta = externo
    ok()
    await entrar()
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/kanban"))
  })

  it("credencial errada mostra o erro genérico e não navega", async () => {
    falha(401)
    await entrar()
    expect(await screen.findByText("E-mail ou senha incorretos")).toBeInTheDocument()
    expect(mocks.replace).not.toHaveBeenCalled()
    expect(mocks.definir).not.toHaveBeenCalled()
  })

  it("429 mostra a espera em minutos, arredondada para cima", async () => {
    falha(429, { "Retry-After": "125" })
    await entrar()
    expect(await screen.findByText("Muitas tentativas, tente em 3 min")).toBeInTheDocument()
  })

  it("429 com poucos segundos mostra no mínimo 1 min", async () => {
    falha(429, { "Retry-After": "20" })
    await entrar()
    expect(await screen.findByText("Muitas tentativas, tente em 1 min")).toBeInTheDocument()
  })

  it("falha de rede mostra mensagem própria", async () => {
    cliente.POST.mockRejectedValue(new TypeError("Failed to fetch"))
    await entrar()
    expect(await screen.findByText(/não foi possível entrar/i)).toBeInTheDocument()
  })

  it("sem preencher não envia", async () => {
    render(<LoginForm cliente={cliente as never} />)
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }))
    expect(cliente.POST).not.toHaveBeenCalled()
  })
})
