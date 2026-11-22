import { render, screen, waitFor, within } from "@testing-library/react"
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

type Acoes = {
  put?: (corpo: unknown) => Resposta
  testar?: () => Resposta
  sincronizar?: () => Resposta
}

function apiFalsa(get: Resposta, acoes: Acoes | ((corpo: unknown) => Resposta) = {}) {
  const { put, testar, sincronizar }: Acoes = typeof acoes === "function" ? { put: acoes } : acoes
  const puts: unknown[] = []
  const posts: string[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    const { pathname } = new URL(req.url)
    if (req.method === "POST" && pathname === `${ROTA}/testar`) {
      posts.push("testar")
      const r = testar?.() ?? { corpo: { ok: true, mensagem: "Conexão ok: a unidade 12 existe na chave do ERP." } }
      return json(r.corpo, r.status ?? 200)
    }
    if (req.method === "POST" && pathname === `${ROTA}/sincronizar`) {
      posts.push("sincronizar")
      const r = sincronizar?.() ?? { corpo: SAIDA }
      return json(r.corpo, r.status ?? 200)
    }
    if (pathname !== ROTA) return json({ erros: [{ caminho: "rota", mensagem: "sem rota" }] }, 404)
    if (req.method === "GET") return json(get.corpo, get.status ?? 200)
    const corpo = await req.json()
    puts.push(corpo)
    const r: Resposta = put ? put(corpo) : { corpo: { ...SAIDA, ...(corpo as object) } }
    return json(r.corpo, r.status ?? 200)
  })
  return { cliente: criarCliente("http://api.local", fetchFalso), puts, posts }
}

const RELATORIO_OK = {
  lidos: 2664,
  importados: 1087,
  outra_loja: 1500,
  descartados: 77,
  por_motivo: { sem_preco: 70, nao_e_celular: 7 },
  duracao_s: 21.3,
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

  it("mostra o status e o relatório da última sincronização, só leitura", async () => {
    const { cliente } = apiFalsa({
      corpo: {
        ...SAIDA,
        ultima_sincronizacao_em: "2026-11-22T15:30:00Z",
        ultimo_status: "ok",
        ultimo_relatorio: RELATORIO_OK,
      },
    })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    expect(screen.getByText("Sincronizada")).toBeInTheDocument()
    expect(screen.getByText(/22\/11\/2026/)).toBeInTheDocument()
    const relatorio = screen.getByRole("region", { name: "Última sincronização" })
    expect(within(relatorio).getByText("Itens lidos do ERP").nextSibling).toHaveTextContent("2.664")
    expect(within(relatorio).getByText("Importados").nextSibling).toHaveTextContent("1.087")
    expect(within(relatorio).getByText("De outra loja").nextSibling).toHaveTextContent("1.500")
    expect(within(relatorio).getByText("Sem preço").nextSibling).toHaveTextContent("70")
    expect(within(relatorio).getByText("Não é celular").nextSibling).toHaveTextContent("7")
    expect(within(relatorio).getByText("Duração").nextSibling).toHaveTextContent("21,3 s")
  })

  it("mostra a mensagem de erro da última sincronização e que o estoque anterior ficou", async () => {
    const { cliente } = apiFalsa({
      corpo: {
        ...SAIDA,
        ultima_sincronizacao_em: "2026-11-22T15:30:00Z",
        ultimo_status: "erro",
        ultimo_relatorio: { erro: "ERP indisponível no momento: timeout", duracao_s: 15 },
      },
    })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    expect(screen.getByText("Falhou")).toBeInTheDocument()
    expect(screen.getByText(/ERP indisponível no momento: timeout/)).toBeInTheDocument()
    expect(screen.getByText(/estoque anterior foi mantido/i)).toBeInTheDocument()
  })

  it("loja sem conexão salva não pode testar nem sincronizar", async () => {
    const { cliente } = apiFalsa({ corpo: VAZIA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    expect(screen.getByRole("button", { name: "Testar conexão" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Sincronizar agora" })).toBeDisabled()
  })

  it("Testar conexão chama a API e mostra o resultado", async () => {
    const user = userEvent.setup()
    const { cliente, posts } = apiFalsa({ corpo: SAIDA })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    await user.click(screen.getByRole("button", { name: "Testar conexão" }))
    expect(await screen.findByText(/a unidade 12 existe na chave do ERP/)).toBeInTheDocument()
    expect(posts).toEqual(["testar"])
  })

  it("Testar conexão mostra a falha quando a unidade não existe na chave", async () => {
    const user = userEvent.setup()
    const { cliente } = apiFalsa(
      { corpo: SAIDA },
      { testar: () => ({ corpo: { ok: false, mensagem: "A unidade 12 não existe na chave do ERP." } }) },
    )
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    await user.click(screen.getByRole("button", { name: "Testar conexão" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("A unidade 12 não existe na chave do ERP.")
  })

  it("Sincronizar agora atualiza o status e o relatório com a resposta da API", async () => {
    const user = userEvent.setup()
    const { cliente, posts } = apiFalsa(
      { corpo: SAIDA },
      {
        sincronizar: () => ({
          corpo: {
            ...SAIDA,
            ultima_sincronizacao_em: "2026-11-22T15:30:00Z",
            ultimo_status: "ok",
            ultimo_relatorio: RELATORIO_OK,
          },
        }),
      },
    )
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    expect(screen.getByText("Ainda não sincronizou.")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Sincronizar agora" }))
    expect(await screen.findByText("Sincronizada")).toBeInTheDocument()
    expect(screen.getByText("2.664")).toBeInTheDocument()
    expect(posts).toEqual(["sincronizar"])
    expect(screen.queryByText("Ainda não sincronizou.")).not.toBeInTheDocument()
  })

  it("Sincronizar agora fica desabilitado enquanto roda (a leitura leva alguns segundos)", async () => {
    const user = userEvent.setup()
    let liberar: () => void = () => {}
    const espera = new Promise<void>((r) => (liberar = r))
    const fetchFalso = vi.fn(async (req: Request) => {
      const { pathname } = new URL(req.url)
      if (req.method === "POST") {
        await espera
        return json(SAIDA)
      }
      return pathname === ROTA ? json(SAIDA) : json({}, 404)
    })
    const cliente = criarCliente("http://api.local", fetchFalso)
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    await user.click(screen.getByRole("button", { name: "Sincronizar agora" }))
    expect(await screen.findByRole("button", { name: "Sincronizando…" })).toBeDisabled()
    liberar()
    expect(await screen.findByRole("button", { name: "Sincronizar agora" })).toBeEnabled()
  })

  it("Sincronizar agora mostra o erro da API (ex.: ERP não configurado no servidor)", async () => {
    const user = userEvent.setup()
    const { cliente } = apiFalsa(
      { corpo: SAIDA },
      {
        sincronizar: () => ({
          status: 409,
          corpo: { erros: [{ caminho: "erp", mensagem: "Integração com o ERP não configurada no servidor." }] },
        }),
      },
    )
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Unidade do ERP")
    await user.click(screen.getByRole("button", { name: "Sincronizar agora" }))
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Integração com o ERP não configurada no servidor.",
    )
  })

  it("avisa quando não consegue carregar", async () => {
    const { cliente } = apiFalsa({ status: 500, corpo: { erros: [] } })
    render(<ErpConfig cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar")
  })
})
