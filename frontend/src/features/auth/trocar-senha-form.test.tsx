import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { TrocarSenhaForm } from "./trocar-senha-form"

const mocks = vi.hoisted(() => ({ replace: vi.fn(), definir: vi.fn() }))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
}))

const IDENTIDADE = {
  lojaId: "00000000-0000-4000-8000-00000000de30",
  lojaNome: "Loja Demo",
  email: "dono@loja.com",
  senhaProvisoria: true,
}

vi.mock("@/lib/sessao", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/sessao")>()),
  useSessao: () => ({ ...IDENTIDADE, definirIdentidade: mocks.definir }),
}))

const cliente = { PUT: vi.fn() }

async function preencher(atual: string, nova: string, confirmacao: string) {
  render(<TrocarSenhaForm cliente={cliente as never} />)
  await userEvent.type(screen.getByLabelText("Senha atual"), atual)
  await userEvent.type(screen.getByLabelText("Nova senha"), nova)
  await userEvent.type(screen.getByLabelText("Confirmar nova senha"), confirmacao)
  await userEvent.click(screen.getByRole("button", { name: "Trocar senha" }))
}

function erro400(motivo: string) {
  cliente.PUT.mockResolvedValue({
    error: { erros: [{ caminho: "senha", mensagem: "texto do backend" }], motivo },
    response: new Response(null, { status: 400 }),
  })
}

beforeEach(() => {
  mocks.replace.mockReset()
  mocks.definir.mockReset()
  cliente.PUT.mockReset()
})

describe("TrocarSenhaForm", () => {
  it("nova senha com menos de 10 caracteres não envia", async () => {
    await preencher("provisoria-1", "curta", "curta")
    expect(await screen.findByText("A nova senha precisa ter pelo menos 10 caracteres.")).toBeInTheDocument()
    expect(cliente.PUT).not.toHaveBeenCalled()
  })

  it("confirmação diferente não envia", async () => {
    await preencher("provisoria-1", "senha-nova-123", "senha-nova-124")
    expect(await screen.findByText("A confirmação não é igual à nova senha.")).toBeInTheDocument()
    expect(cliente.PUT).not.toHaveBeenCalled()
  })

  it("sucesso envia as duas senhas, tira a marca de provisória e volta ao painel", async () => {
    cliente.PUT.mockResolvedValue({ response: new Response(null, { status: 204 }) })
    await preencher("provisoria-1", "senha-nova-123", "senha-nova-123")

    expect(cliente.PUT).toHaveBeenCalledWith("/auth/senha", {
      body: { senha_atual: "provisoria-1", senha_nova: "senha-nova-123" },
    })
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/kanban"))
    expect(mocks.definir).toHaveBeenCalledWith({
      loja_id: IDENTIDADE.lojaId,
      loja_nome: IDENTIDADE.lojaNome,
      email: IDENTIDADE.email,
      senha_provisoria: false,
    })
  })

  it.each([
    ["senha_atual_incorreta", "A senha atual está incorreta."],
    ["senha_nova_curta", "A nova senha precisa ter pelo menos 10 caracteres."],
    ["senha_nova_igual", "A nova senha precisa ser diferente da atual."],
  ])("erro do backend %s mostra mensagem própria", async (motivo, mensagem) => {
    erro400(motivo)
    await preencher("provisoria-1", "senha-nova-123", "senha-nova-123")
    expect(await screen.findByText(mensagem)).toBeInTheDocument()
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it("erro sem motivo conhecido usa a mensagem do backend", async () => {
    cliente.PUT.mockResolvedValue({
      error: { erros: [{ caminho: "senha", mensagem: "Algo deu errado." }] },
      response: new Response(null, { status: 500 }),
    })
    await preencher("provisoria-1", "senha-nova-123", "senha-nova-123")
    expect(await screen.findByText("Algo deu errado.")).toBeInTheDocument()
  })
})
