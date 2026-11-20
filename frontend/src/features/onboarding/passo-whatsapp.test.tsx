import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { PassoWhatsapp } from "./passo-whatsapp"

const LOJA = "00000000-0000-4000-8000-00000000de30"
const STATUS = `/lojas/${LOJA}/whatsapp/status`
const CONECTAR = `/lojas/${LOJA}/whatsapp/conectar`
const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

type EstadoConexao = "conectado" | "conectando" | "desconectado" | "inexistente"
type Resposta = { status?: number; corpo: unknown }
type Rota = Resposta | (() => Resposta)

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
}

/** Cliente com fetch falso; rotas "MÉTODO /caminho" (valor fixo ou função chamada a cada request). */
function apiFalsa(rotas: Record<string, Rota>) {
  const chamadas: string[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    const chave = `${req.method} ${new URL(req.url).pathname}`
    chamadas.push(chave)
    const rota = rotas[chave]
    if (!rota) return json({ erros: [{ caminho: "rota", mensagem: `sem rota ${chave}` }] }, 404)
    const r = typeof rota === "function" ? rota() : rota
    return json(r.corpo, r.status ?? 200)
  })
  const quantas = (chave: string) => chamadas.filter((c) => c === chave).length
  return { cliente: criarCliente("http://api.local", fetchFalso), chamadas, quantas }
}

const status = (s: EstadoConexao): Rota => ({ corpo: { status: s } })
const conexao = (s: EstadoConexao, qr: string | null): Rota => ({ corpo: { status: s, qr_base64: qr } })

async function avancar(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false })
})

afterEach(() => {
  vi.useRealTimers()
})

function preparar(rotas: Record<string, Rota>) {
  const api = apiFalsa(rotas)
  // fireEvent: o `asyncWrapper` do user-event/RTL trava com os timers falsos do vitest
  const user = { click: async (el: HTMLElement) => void fireEvent.click(el) }
  const tela = render(<PassoWhatsapp cliente={api.cliente} lojaId={LOJA} />)
  return { ...api, user, ...tela }
}

describe("PassoWhatsapp", () => {
  it("mostra o estado atual ao abrir e oferece o botão Conectar", async () => {
    preparar({ [`GET ${STATUS}`]: status("desconectado") })
    await avancar(0)
    expect(screen.getByText("Desconectado")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Conectar" })).toBeEnabled()
    expect(screen.queryByRole("img")).not.toBeInTheDocument()
  })

  it("já conectado: mostra Conectado e não oferece QR", async () => {
    preparar({ [`GET ${STATUS}`]: status("conectado") })
    await avancar(0)
    expect(screen.getByText("Conectado")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Conectar" })).not.toBeInTheDocument()
  })

  it("Conectar mostra o QR com texto alternativo e o estado Conectando", async () => {
    const { user, quantas } = preparar({
      [`GET ${STATUS}`]: status("desconectado"),
      [`POST ${CONECTAR}`]: conexao("conectando", `data:image/png;base64,${PNG}`),
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)

    const qr = screen.getByRole("img", { name: /qr code/i })
    expect(qr).toHaveAttribute("src", `data:image/png;base64,${PNG}`)
    expect(screen.getByText("Conectando")).toBeInTheDocument()
    expect(quantas(`POST ${CONECTAR}`)).toBe(1)
  })

  it("não duplica o prefixo data: e acrescenta quando o base64 vem cru", async () => {
    const { user } = preparar({
      [`GET ${STATUS}`]: status("desconectado"),
      [`POST ${CONECTAR}`]: conexao("conectando", PNG),
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)
    expect(screen.getByRole("img", { name: /qr code/i })).toHaveAttribute(
      "src",
      `data:image/png;base64,${PNG}`,
    )
  })

  it("sem QR ainda (logo após criar): avisa que está gerando e tenta de novo no próximo ciclo", async () => {
    let n = 0
    const { user } = preparar({
      [`GET ${STATUS}`]: status("conectando"),
      [`POST ${CONECTAR}`]: () => (++n === 1 ? { corpo: { status: "conectando", qr_base64: null } } : { corpo: { status: "conectando", qr_base64: PNG } }),
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)
    expect(screen.queryByRole("img")).not.toBeInTheDocument()
    expect(screen.getByText(/gerando o qr code/i)).toBeInTheDocument()
    await avancar(3000)
    expect(screen.getByRole("img", { name: /qr code/i })).toBeInTheDocument()
  })

  it("consulta o status a cada 3 s e para quando conectar", async () => {
    let estado: EstadoConexao = "conectando"
    const { user, quantas } = preparar({
      [`GET ${STATUS}`]: () => ({ corpo: { status: estado } }),
      [`POST ${CONECTAR}`]: conexao("conectando", PNG),
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)
    const base = quantas(`GET ${STATUS}`)

    await avancar(3000)
    expect(quantas(`GET ${STATUS}`)).toBe(base + 1)
    await avancar(3000)
    expect(quantas(`GET ${STATUS}`)).toBe(base + 2)

    estado = "conectado"
    await avancar(3000)
    expect(screen.getByText("Conectado")).toBeInTheDocument()
    expect(screen.queryByRole("img")).not.toBeInTheDocument()

    const depois = quantas(`GET ${STATUS}`)
    await avancar(30_000)
    expect(quantas(`GET ${STATUS}`)).toBe(depois)
  })

  it("renova o QR a cada ~20 s enquanto não conectar", async () => {
    const { user, quantas } = preparar({
      [`GET ${STATUS}`]: status("conectando"),
      [`POST ${CONECTAR}`]: conexao("conectando", PNG),
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)
    expect(quantas(`POST ${CONECTAR}`)).toBe(1)
    await avancar(19_000)
    expect(quantas(`POST ${CONECTAR}`)).toBe(1)
    await avancar(2_000)
    expect(quantas(`POST ${CONECTAR}`)).toBe(2)
  })

  it("Evolution fora (502): mostra a mensagem e permite tentar de novo", async () => {
    let falhar = true
    const { user } = preparar({
      [`GET ${STATUS}`]: status("desconectado"),
      [`POST ${CONECTAR}`]: () =>
        falhar
          ? { status: 502, corpo: { erros: [{ caminho: "whatsapp", mensagem: "Evolution fora." }] } }
          : { corpo: { status: "conectando", qr_base64: PNG } },
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)
    expect(screen.getByRole("alert")).toHaveTextContent(/evolution indisponível/i)

    falhar = false
    await user.click(screen.getByRole("button", { name: /tentar de novo/i }))
    await avancar(0)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(screen.getByRole("img", { name: /qr code/i })).toBeInTheDocument()
  })

  it("rede caída ao abrir o passo também vira Evolution indisponível", async () => {
    const fetchQuebrado = vi.fn(async () => {
      throw new TypeError("fetch failed")
    })
    render(<PassoWhatsapp cliente={criarCliente("http://api.local", fetchQuebrado)} lojaId={LOJA} />)
    await avancar(0)
    expect(screen.getByRole("alert")).toHaveTextContent(/evolution indisponível/i)
  })

  it("para o polling ao desmontar", async () => {
    const { user, quantas, unmount } = preparar({
      [`GET ${STATUS}`]: status("conectando"),
      [`POST ${CONECTAR}`]: conexao("conectando", PNG),
    })
    await avancar(0)
    await user.click(screen.getByRole("button", { name: "Conectar" }))
    await avancar(0)
    unmount()
    const gets = quantas(`GET ${STATUS}`)
    const posts = quantas(`POST ${CONECTAR}`)
    await avancar(60_000)
    expect(quantas(`GET ${STATUS}`)).toBe(gets)
    expect(quantas(`POST ${CONECTAR}`)).toBe(posts)
  })
})
