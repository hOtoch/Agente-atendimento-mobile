import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { PassoPreco } from "./passo-preco"

const LOJA = "00000000-0000-4000-8000-00000000de30"
const ROTA = `/lojas/${LOJA}/config/preco`

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
}

const PRECO = {
  max_parcelas: 12,
  repassa_taxa: true,
  desconto_pix_tipo: "nenhum",
  desconto_pix_valor: null,
  aceita_entrada_mais_cartao: true,
  desconto_teto: "100.00",
  desconto_degrau: "50.00",
  oportunidade_ativa: false,
  oportunidade_dias_minimos: 0,
  oportunidade_valor: "0.00",
  oportunidade_conta_no_teto: false,
}

function preparar() {
  const enviados: Record<string, unknown>[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    if (new URL(req.url).pathname !== ROTA) return json({}, 404)
    if (req.method === "PUT") {
      enviados.push(await req.json())
      return json(PRECO)
    }
    return json(PRECO)
  })
  render(<PassoPreco cliente={criarCliente("http://api.local", fetchFalso)} lojaId={LOJA} aoSalvar={vi.fn()} />)
  return { enviados }
}

describe("PassoPreco: escada de desconto", () => {
  it("mostra os rótulos do degrau e do teto com os valores da loja", async () => {
    preparar()
    expect(await screen.findByLabelText("Desconto por pedido (degrau)")).toHaveValue("50")
    expect(screen.getByLabelText("Desconto máximo (teto)")).toHaveValue("100")
  })

  it("explica o que acontece depois do teto e com pedido de brinde", async () => {
    preparar()
    await screen.findByLabelText("Desconto máximo (teto)")
    expect(
      screen.getByText(
        "A IA libera o degrau a cada pedido do cliente até o teto. Se ele pedir mais que o teto, ou brinde/benefício, o atendimento vai para o vendedor com um resumo.",
      ),
    ).toBeInTheDocument()
  })

  it("salva o degrau e o teto editados", async () => {
    const { enviados } = preparar()
    const degrau = await screen.findByLabelText("Desconto por pedido (degrau)")
    await userEvent.clear(degrau)
    await userEvent.type(degrau, "25")
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }))
    await vi.waitFor(() => expect(enviados).toHaveLength(1))
    expect(enviados[0]).toMatchObject({ desconto_degrau: 25, desconto_teto: 100 })
  })
})
