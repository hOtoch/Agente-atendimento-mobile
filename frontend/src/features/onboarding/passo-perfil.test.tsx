import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { PassoPerfil } from "./passo-perfil"

const LOJA = "00000000-0000-4000-8000-00000000de30"
const ROTA = `/lojas/${LOJA}/config/perfil`

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
}

function preparar(perfil: Record<string, unknown>) {
  const enviados: unknown[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    if (new URL(req.url).pathname !== ROTA) return json({}, 404)
    if (req.method === "PUT") {
      const corpo = await req.json()
      enviados.push(corpo)
      return json(corpo)
    }
    return json(perfil)
  })
  const aoSalvar = vi.fn()
  render(<PassoPerfil cliente={criarCliente("http://api.local", fetchFalso)} lojaId={LOJA} aoSalvar={aoSalvar} />)
  return { enviados, aoSalvar }
}

const PERFIL = {
  nome_exibicao: "Loja Centro",
  tom_de_voz: "",
  endereco: "",
  horarios: {},
  whatsapp_contato: "",
  responder_em_audio: true,
}

describe("PassoPerfil: resposta em áudio", () => {
  it("mostra a opção ligada como veio da API", async () => {
    preparar(PERFIL)
    const caixa = await screen.findByRole("checkbox", { name: /responder em áudio/i })
    expect(caixa).toBeChecked()
  })

  it("desligar a opção e salvar envia responder_em_audio=false", async () => {
    const { enviados } = preparar(PERFIL)
    await userEvent.click(await screen.findByRole("checkbox", { name: /responder em áudio/i }))
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(enviados).toHaveLength(1))
    expect(enviados[0]).toMatchObject({ responder_em_audio: false })
  })

  it("sem perfil salvo ainda, a opção começa ligada", async () => {
    preparar(null as unknown as Record<string, unknown>)
    expect(await screen.findByRole("checkbox", { name: /responder em áudio/i })).toBeChecked()
  })
})
