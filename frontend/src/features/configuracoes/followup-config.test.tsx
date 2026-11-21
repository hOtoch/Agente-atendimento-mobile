import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { FollowupConfig } from "./followup-config"

const LOJA = "00000000-0000-4000-8000-00000000de30"
const ROTA = `/lojas/${LOJA}/config/followup`

const CORPO = {
  ligado: false,
  horas_por_etapa: { interesse_qualificado: 2, interesse_identificado: 24 },
  max_tentativas: 2,
  intervalo_horas: 24,
  hora_inicio: "09:00",
  hora_fim: "18:00",
  max_dias_parado: 7,
}

type Resposta = { status?: number; corpo: unknown }

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
}

function apiFalsa(get: Resposta, put?: (corpo: unknown) => Resposta) {
  const puts: unknown[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    const { pathname } = new URL(req.url)
    if (pathname !== ROTA) return json({ erros: [{ caminho: "rota", mensagem: "sem rota" }] }, 404)
    if (req.method === "GET") return json(get.corpo, get.status ?? 200)
    const corpo = await req.json()
    puts.push(corpo)
    const r: Resposta = put ? put(corpo) : { corpo }
    return json(r.corpo, r.status ?? 200)
  })
  return { cliente: criarCliente("http://api.local", fetchFalso), puts }
}

describe("FollowupConfig", () => {
  it("carrega a configuração da loja e mostra os campos", async () => {
    const { cliente } = apiFalsa({ corpo: CORPO })
    render(<FollowupConfig cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByLabelText("Máximo de tentativas")).toHaveValue(2)
    expect(screen.getByLabelText("Interesse qualificado (horas)")).toHaveValue(2)
    expect(screen.getByLabelText("Interesse identificado (horas)")).toHaveValue(24)
    expect(screen.getByLabelText("Novo contato (horas)")).toHaveValue(null)
    expect(screen.getByLabelText("Início do horário comercial")).toHaveValue("09:00")
    expect(screen.getByLabelText("Fim do horário comercial")).toHaveValue("18:00")
  })

  it("salva as alterações com PUT no formato da API", async () => {
    const user = userEvent.setup()
    const { cliente, puts } = apiFalsa({ corpo: CORPO })
    render(<FollowupConfig cliente={cliente} lojaId={LOJA} />)
    const tentativas = await screen.findByLabelText("Máximo de tentativas")
    await user.clear(tentativas)
    await user.type(tentativas, "3")
    const qualificado = screen.getByLabelText("Interesse qualificado (horas)")
    await user.clear(qualificado)
    await user.type(qualificado, "4")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]).toEqual({
      ...CORPO,
      max_tentativas: 3,
      horas_por_etapa: { interesse_qualificado: 4, interesse_identificado: 24 },
    })
  })

  it("não envia e mostra o erro quando o formulário é inválido", async () => {
    const user = userEvent.setup()
    const { cliente, puts } = apiFalsa({ corpo: CORPO })
    render(<FollowupConfig cliente={cliente} lojaId={LOJA} />)
    const tentativas = await screen.findByLabelText("Máximo de tentativas")
    await user.clear(tentativas)
    await user.type(tentativas, "9")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    expect(await screen.findByText(/entre 1 e 5/)).toBeInTheDocument()
    expect(puts).toHaveLength(0)
  })

  it("mostra o erro por campo devolvido pela API", async () => {
    const user = userEvent.setup()
    const { cliente } = apiFalsa({ corpo: CORPO }, () => ({
      status: 422,
      corpo: { erros: [{ caminho: "intervalo_horas", mensagem: "deve ser >= 1" }] },
    }))
    render(<FollowupConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Máximo de tentativas")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    expect(await screen.findByText("deve ser >= 1")).toBeInTheDocument()
  })

  it("avisa quando não consegue carregar", async () => {
    const { cliente } = apiFalsa({ status: 500, corpo: { erros: [] } })
    render(<FollowupConfig cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar")
  })

  it("liga o follow-up pelo seletor", async () => {
    const user = userEvent.setup()
    const { cliente, puts } = apiFalsa({ corpo: CORPO })
    render(<FollowupConfig cliente={cliente} lojaId={LOJA} />)
    await user.click(await screen.findByRole("combobox", { name: "Follow-up automático" }))
    await user.click(await screen.findByRole("option", { name: "Ligado" }))
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect((puts[0] as { ligado: boolean }).ligado).toBe(true)
  })
})
