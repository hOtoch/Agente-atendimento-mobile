import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { notificarNaoAutorizado } from "@/lib/api"

import { SessaoProvider, useSessao } from "./sessao"

const nav = vi.hoisted(() => ({ pathname: "/kanban", replace: vi.fn() }))

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace, push: nav.replace }),
}))

const LOJA = "00000000-0000-4000-8000-00000000de30"
const IDENTIDADE = { loja_id: LOJA, loja_nome: "Loja Demo", email: "dono@loja.com", senha_provisoria: false }

const cliente = { GET: vi.fn(), POST: vi.fn() }

function resposta(status: number, data?: unknown) {
  return {
    data: status === 200 ? data : undefined,
    error: status === 200 ? undefined : { erros: [{ caminho: "sessao", mensagem: "Sem sessão." }] },
    response: new Response(null, { status }),
  }
}

function Sonda() {
  const { lojaId, lojaNome, email, senhaProvisoria, sair } = useSessao()
  return (
    <div>
      <p>{`loja=${lojaId};nome=${lojaNome};email=${email};prov=${String(senhaProvisoria)}`}</p>
      <button onClick={() => void sair()}>sair</button>
    </div>
  )
}

function montar() {
  return render(
    <SessaoProvider cliente={cliente as never}>
      <Sonda />
    </SessaoProvider>,
  )
}

beforeEach(() => {
  nav.pathname = "/kanban"
  nav.replace.mockReset()
  cliente.GET.mockReset()
  cliente.POST.mockReset()
})

describe("SessaoProvider", () => {
  it("mostra esqueleto enquanto carrega e depois expõe a sessão", async () => {
    let liberar: (v: unknown) => void = () => {}
    cliente.GET.mockReturnValue(new Promise((r) => (liberar = r)))
    montar()

    expect(screen.getByRole("status", { name: /carregando/i })).toBeInTheDocument()
    expect(screen.queryByText(/loja=/)).toBeNull()

    liberar(resposta(200, IDENTIDADE))
    expect(
      await screen.findByText(`loja=${LOJA};nome=Loja Demo;email=dono@loja.com;prov=false`),
    ).toBeInTheDocument()
    expect(cliente.GET).toHaveBeenCalledWith("/auth/eu")
    expect(nav.replace).not.toHaveBeenCalled()
  })

  it("401 manda para /login com a rota de origem em `volta`", async () => {
    cliente.GET.mockResolvedValue(resposta(401))
    montar()
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?volta=/kanban"))
    expect(screen.queryByText(/loja=/)).toBeNull()
  })

  it("403 também é sessão inválida para esta loja", async () => {
    cliente.GET.mockResolvedValue(resposta(403))
    montar()
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?volta=/kanban"))
  })

  it("com senha provisória, qualquer rota cai em /conta/senha sem mostrar a página", async () => {
    cliente.GET.mockResolvedValue(resposta(200, { ...IDENTIDADE, senha_provisoria: true }))
    montar()
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/conta/senha"))
    expect(screen.queryByText(/loja=/)).toBeNull()
  })

  it("em /conta/senha com senha provisória a página abre normalmente", async () => {
    nav.pathname = "/conta/senha"
    cliente.GET.mockResolvedValue(resposta(200, { ...IDENTIDADE, senha_provisoria: true }))
    montar()
    expect(await screen.findByText(/prov=true/)).toBeInTheDocument()
    expect(nav.replace).not.toHaveBeenCalled()
  })

  it.each(["/login", "/chat/abc"])("rota pública %s não chama /auth/eu nem redireciona", async (rota) => {
    nav.pathname = rota
    render(
      <SessaoProvider cliente={cliente as never}>
        <p>pública</p>
      </SessaoProvider>,
    )
    expect(await screen.findByText("pública")).toBeInTheDocument()
    expect(cliente.GET).not.toHaveBeenCalled()
    expect(nav.replace).not.toHaveBeenCalled()
  })

  it("sair chama POST /auth/logout, limpa a sessão e vai para /login", async () => {
    cliente.GET.mockResolvedValue(resposta(200, IDENTIDADE))
    cliente.POST.mockResolvedValue({ response: new Response(null, { status: 204 }) })
    montar()
    await userEvent.click(await screen.findByRole("button", { name: "sair" }))

    expect(cliente.POST).toHaveBeenCalledWith("/auth/logout")
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login"))
    expect(screen.queryByText(/loja=/)).toBeNull()
  })

  it("qualquer 401 da API depois do login limpa a sessão e vai para /login?volta=", async () => {
    cliente.GET.mockResolvedValue(resposta(200, IDENTIDADE))
    montar()
    await screen.findByText(/loja=/)

    act(() => notificarNaoAutorizado())

    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?volta=/kanban"))
    expect(screen.queryByText(/loja=/)).toBeNull()
  })

  it("useSessao fora do provider avisa o erro de uso", () => {
    const erro = vi.spyOn(console, "error").mockImplementation(() => {})
    expect(() => render(<Sonda />)).toThrow(/SessaoProvider/)
    erro.mockRestore()
  })
})
