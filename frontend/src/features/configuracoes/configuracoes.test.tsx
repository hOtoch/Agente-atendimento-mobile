import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { Configuracoes } from "./configuracoes"

const LOJA = "00000000-0000-4000-8000-00000000de30"

describe("Configuracoes", () => {
  it("mostra a seção de follow-up automático", async () => {
    const corpo = {
      ligado: false,
      horas_por_etapa: {},
      max_tentativas: 2,
      intervalo_horas: 24,
      hora_inicio: "09:00",
      hora_fim: "18:00",
      max_dias_parado: 7,
    }
    const fetchFalso = vi.fn(
      async () => new Response(JSON.stringify(corpo), { headers: { "Content-Type": "application/json" } }),
    )
    render(<Configuracoes lojaId={LOJA} cliente={criarCliente("http://api.local", fetchFalso)} />)
    expect(screen.getByRole("heading", { name: "Follow-up automático" })).toBeInTheDocument()
    expect(await screen.findByLabelText("Máximo de tentativas")).toBeInTheDocument()
  })
})
