import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { Configuracoes } from "./configuracoes"

const LOJA = "00000000-0000-4000-8000-00000000de30"

const FOLLOWUP = {
  ligado: false,
  horas_por_etapa: {},
  max_tentativas: 2,
  intervalo_horas: 24,
  hora_inicio: "09:00",
  hora_fim: "18:00",
  max_dias_parado: 7,
}

const ERP = {
  configurada: false,
  provedor: "mercadophone",
  system_unit_id: null,
  filtro_loja: null,
  ativo: false,
  intervalo_min: 15,
  exportar_handoff: false,
  ultima_sincronizacao_em: null,
  ultimo_status: null,
  ultimo_relatorio: null,
}

function clienteFalso() {
  const fetchFalso = vi.fn(async (req: Request) => {
    const corpo = new URL(req.url).pathname.endsWith("/erp") ? ERP : FOLLOWUP
    return new Response(JSON.stringify(corpo), { headers: { "Content-Type": "application/json" } })
  })
  return criarCliente("http://api.local", fetchFalso)
}

describe("Configuracoes", () => {
  it("mostra a seção de follow-up automático", async () => {
    render(<Configuracoes lojaId={LOJA} cliente={clienteFalso()} />)
    expect(screen.getByRole("heading", { name: "Follow-up automático" })).toBeInTheDocument()
    expect(await screen.findByLabelText("Máximo de tentativas")).toBeInTheDocument()
  })

  it("mostra a seção de conexão com o ERP", async () => {
    render(<Configuracoes lojaId={LOJA} cliente={clienteFalso()} />)
    expect(screen.getByRole("heading", { name: "Conexão com o ERP" })).toBeInTheDocument()
    expect(await screen.findByLabelText("Unidade do ERP")).toBeInTheDocument()
  })
})
