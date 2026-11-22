import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { ErpConfig } from "./erp-config"

const LOJA = "00000000-0000-4000-8000-00000000de30"
const ROTA = `/lojas/${LOJA}/config/erp`

const SAIDA = {
  configurada: true,
  provedor: "mercadophone",
  system_unit_id: 12,
  filtro_loja: "Centro",
  ativo: true,
  intervalo_min: 30,
  exportar_handoff: false,
  ultima_sincronizacao_em: null,
  ultimo_status: null,
  ultimo_relatorio: null,
}

const VAZIA = {
  ...SAIDA,
  configurada: false,
  system_unit_id: null,
  filtro_loja: null,
  ativo: false,
  intervalo_min: 15,
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
    const r: Resposta = put ? put(corpo) : { corpo: { ...SAIDA, ...(corpo as object) } }
    return json(r.corpo, r.status ?? 200)
  })
  return { cliente: criarCliente("http://api.local", fetchFalso), puts }
}

describe("ErpConfig", () => {
  it("carrega a conexão da loja e mostra os campos", async () => {
    const { cliente } = apiFalsa({ corpo: SAIDA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByLabelText("Unidade do ERP")).toHaveValue(12)
    expect(screen.getByLabelText("Filtro da loja")).toHaveValue("Centro")
    expect(screen.getByLabelText("Intervalo de sincronização (minutos)")).toHaveValue(30)
    expect(screen.getByRole("checkbox", { name: /Sincronização ativa/ })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: /Exportar handoff/ })).not.toBeChecked()
  })

  it("loja sem conexão mostra o formulário vazio e a sincronização nunca feita", async () => {
    const { cliente } = apiFalsa({ corpo: VAZIA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByLabelText("Unidade do ERP")).toHaveValue(null)
    expect(screen.getByLabelText("Intervalo de sincronização (minutos)")).toHaveValue(15)
    expect(screen.getByRole("checkbox", { name: /Sincronização ativa/ })).not.toBeChecked()
    expect(screen.getByText("Ainda não sincronizou.")).toBeInTheDocument()
  })

  it("nunca pede nem mostra a chave do ERP", async () => {
    const { cliente } = apiFalsa({ corpo: SAIDA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    expect(screen.queryByLabelText(/chave|token|senha/i)).not.toBeInTheDocument()
    expect(screen.getByText(/chave de acesso fica no servidor/i)).toBeInTheDocument()
  })

  it("salva as alterações com PUT no formato da API", async () => {
    const user = userEvent.setup()
    const { cliente, puts } = apiFalsa({ corpo: SAIDA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    const unidade = await screen.findByLabelText("Unidade do ERP")
    await user.clear(unidade)
    await user.type(unidade, "20")
    const filtro = screen.getByLabelText("Filtro da loja")
    await user.clear(filtro)
    await user.click(screen.getByRole("checkbox", { name: /Exportar handoff/ }))
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]).toEqual({
      system_unit_id: 20,
      filtro_loja: null,
      ativo: true,
      intervalo_min: 30,
      exportar_handoff: true,
    })
  })

  it("não envia e mostra o erro quando o intervalo é inválido", async () => {
    const user = userEvent.setup()
    const { cliente, puts } = apiFalsa({ corpo: SAIDA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    const intervalo = await screen.findByLabelText("Intervalo de sincronização (minutos)")
    await user.clear(intervalo)
    await user.type(intervalo, "2")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    expect(await screen.findByText(/entre 5 e 1440/)).toBeInTheDocument()
    expect(puts).toHaveLength(0)
  })

  it("exige a unidade para salvar", async () => {
    const user = userEvent.setup()
    const { cliente, puts } = apiFalsa({ corpo: VAZIA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    expect(await screen.findByText(/Informe a unidade/)).toBeInTheDocument()
    expect(puts).toHaveLength(0)
  })

  it("mostra o erro por campo devolvido pela API", async () => {
    const user = userEvent.setup()
    const { cliente } = apiFalsa({ corpo: SAIDA }, () => ({
      status: 422,
      corpo: { erros: [{ caminho: "system_unit_id", mensagem: "deve ser maior que zero" }] },
    }))
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    expect(await screen.findByText("deve ser maior que zero")).toBeInTheDocument()
  })

  it("mostra o status da última sincronização, só leitura", async () => {
    const { cliente } = apiFalsa({
      corpo: {
        ...SAIDA,
        ultima_sincronizacao_em: "2026-11-22T15:30:00Z",
        ultimo_status: "parcial",
        ultimo_relatorio: { produtos: 10 },
      },
    })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    expect(screen.getByText("Sincronizada com avisos")).toBeInTheDocument()
    expect(screen.getByText(/22\/11\/2026/)).toBeInTheDocument()
    expect(screen.getByText(/produtos/)).toBeInTheDocument()
  })

  it("avisa quando não consegue carregar", async () => {
    const { cliente } = apiFalsa({ status: 500, corpo: { erros: [] } })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar")
  })
})
