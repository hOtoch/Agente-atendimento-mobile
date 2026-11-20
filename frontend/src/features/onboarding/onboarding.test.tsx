import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { Onboarding } from "./onboarding"

let params = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  usePathname: () => "/onboarding",
}))

const LOJA = "00000000-0000-4000-8000-00000000de30"

type Resposta = { status?: number; corpo: unknown }
type Rotas = Record<string, Resposta | ((req: Request) => Promise<Resposta> | Resposta)>

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

/** Cliente com fetch falso; rotas no formato "MÉTODO /caminho". Registra as chamadas. */
function apiFalsa(rotas: Rotas) {
  const chamadas: Request[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    chamadas.push(req.clone())
    const { pathname } = new URL(req.url)
    const rota = rotas[`${req.method} ${pathname}`]
    if (!rota) return json({ erros: [{ caminho: "rota", mensagem: `sem rota ${req.method} ${pathname}` }] }, 404)
    const r = typeof rota === "function" ? await rota(req) : rota
    return json(r.corpo, r.status ?? 200)
  })
  return { cliente: criarCliente("http://api.local", fetchFalso), chamadas }
}

const ITENS = [
  { chave: "perfil", rotulo_ptbr: "Perfil da loja", completo: true, detalhe: "Perfil preenchido." },
  { chave: "vendedores", rotulo_ptbr: "Vendedores e distribuição", completo: false, detalhe: "Nenhum vendedor ativo cadastrado." },
  { chave: "regras_preco", rotulo_ptbr: "Regras de preço", completo: true, detalhe: "Até 18x no cartão." },
  { chave: "taxas", rotulo_ptbr: "Taxas da maquininha", completo: false, detalhe: "Faltam taxas." },
  { chave: "tabela_troca", rotulo_ptbr: "Tabela de troca", completo: true, detalhe: "2 linha(s)." },
  { chave: "estoque", rotulo_ptbr: "Estoque", completo: false, detalhe: "Nenhum item." },
  { chave: "mapeamento_sku", rotulo_ptbr: "Mapeamento de SKU", completo: true, detalhe: "Nenhum SKU externo pendente." },
]

const CHECKLIST = `/lojas/${LOJA}/onboarding/checklist`

const LINHA_TROCA = {
  marca: "Apple",
  modelo: "iPhone 16",
  capacidade_gb: 128,
  valor_sem_detalhes: "3100.00",
  desconto_tela: "600.00",
  desconto_tela_sem: false,
  desconto_traseira: "300.00",
  desconto_traseira_sem: false,
  desconto_carcaca: "0.00",
  desconto_carcaca_sem: false,
  desconto_bateria: "190.00",
  desconto_bateria_sem: false,
  limite_bateria_pct: 80,
}

function trocaComDuasLinhas() {
  return { tabela_troca: [LINHA_TROCA, { ...LINHA_TROCA, modelo: "iPhone 15", valor_sem_detalhes: "2500.00" }] }
}

beforeEach(() => {
  params = new URLSearchParams()
})

describe("Onboarding: checklist", () => {
  it("mostra o progresso e o estado de cada passo vindos da API", async () => {
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/perfil`]: { corpo: null },
    })
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    expect(await screen.findByText("4 de 7 itens concluídos")).toBeInTheDocument()
    const nav = screen.getByRole("navigation", { name: /passos/i })
    expect(within(nav).getByRole("link", { name: /vendedores/i })).toHaveAttribute(
      "href",
      "/onboarding?passo=vendedores",
    )
    const vendedores = within(nav).getByRole("link", { name: /vendedores/i })
    expect(within(vendedores).getByText("Pendente")).toBeInTheDocument()
    const perfil = within(nav).getByRole("link", { name: /dados da loja/i })
    expect(within(perfil).getByText("Concluído")).toBeInTheDocument()
    expect(within(nav).getByRole("link", { name: /whatsapp/i })).toBeInTheDocument()
    expect(within(nav).getByRole("link", { name: /conversa de teste/i })).toBeInTheDocument()
  })

  it("sem ?passo= abre o primeiro passo pendente (progresso persiste ao recarregar)", async () => {
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/vendedores`]: { corpo: { vendedores: [] } },
    })
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    expect(await screen.findByRole("heading", { name: "Vendedores e distribuição", level: 2 })).toBeInTheDocument()
    expect(
      within(screen.getByRole("navigation", { name: /passos/i })).getByRole("link", { name: /vendedores/i }),
    ).toHaveAttribute("aria-current", "step")
  })

  it("o passo do WhatsApp é um placeholder e o de teste leva ao simulador", async () => {
    const { cliente } = apiFalsa({ [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } } })
    params = new URLSearchParams("passo=whatsapp")
    const { unmount } = render(<Onboarding cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByText(/em breve/i)).toBeInTheDocument()
    unmount()

    params = new URLSearchParams("passo=teste")
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)
    expect(await screen.findByRole("link", { name: /abrir o simulador/i })).toHaveAttribute("href", "/simulador")
  })
})

describe("Onboarding: tabela de troca (grade editável)", () => {
  it("edita uma célula e salva com PUT; depois atualiza o checklist", async () => {
    params = new URLSearchParams("passo=troca")
    let salvo: unknown = null
    const { cliente, chamadas } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/troca`]: { corpo: trocaComDuasLinhas() },
      [`PUT /lojas/${LOJA}/config/troca`]: async (req) => {
        salvo = await req.json()
        return { corpo: salvo }
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    const campo = await screen.findByLabelText("Valor sem detalhes (R$), linha 2")
    expect(campo).toHaveValue("2500")
    await user.clear(campo)
    await user.type(campo, "2600,50")
    await user.click(screen.getByRole("button", { name: "Salvar" }))

    await waitFor(() => expect(salvo).not.toBeNull())
    const corpo = salvo as { tabela_troca: Record<string, unknown>[] }
    expect(corpo.tabela_troca).toHaveLength(2)
    expect(corpo.tabela_troca[1]).toMatchObject({ modelo: "iPhone 15", valor_sem_detalhes: 2600.5 })
    expect(corpo.tabela_troca[0]).toMatchObject({ desconto_tela: 600, desconto_tela_sem: false })
    await waitFor(() =>
      expect(chamadas.filter((c) => c.method === "GET" && c.url.endsWith("/onboarding/checklist"))).toHaveLength(2),
    )
  })

  it("erro de validação da API aparece na célula certa (linha e coluna)", async () => {
    params = new URLSearchParams("passo=troca")
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/troca`]: { corpo: trocaComDuasLinhas() },
      [`PUT /lojas/${LOJA}/config/troca`]: {
        status: 422,
        corpo: {
          erros: [{ caminho: "tabela_troca[1].desconto_tela", mensagem: "Desconto maior que o valor base." }],
        },
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    await screen.findByLabelText("Desconto tela, linha 2")
    await user.click(screen.getByRole("button", { name: "Salvar" }))

    const celula = await screen.findByLabelText("Desconto tela, linha 2")
    await waitFor(() => expect(celula).toHaveAttribute("aria-invalid", "true"))
    expect(celula).toHaveAccessibleDescription("Desconto maior que o valor base.")
    expect(screen.getByLabelText("Desconto tela, linha 1")).not.toHaveAttribute("aria-invalid")
    expect(screen.getByLabelText("Valor sem detalhes (R$), linha 2")).not.toHaveAttribute("aria-invalid")
  })

  it("erro de taxas na API vai para a célula da bandeira correta", async () => {
    params = new URLSearchParams("passo=taxas")
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/taxas`]: {
        corpo: {
          taxas: [
            { chave: 1, bandeira: "mastercard", taxa_pct: "3.10" },
            { chave: 1, bandeira: "visa", taxa_pct: "3.20" },
            { chave: 2, bandeira: "mastercard", taxa_pct: "4.00" },
          ],
        },
      },
      [`PUT /lojas/${LOJA}/config/taxas`]: {
        status: 422,
        corpo: { erros: [{ caminho: "taxas[2].taxa_pct", mensagem: "Taxa deve estar entre 0 e 100 (%)." }] },
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    await screen.findByLabelText("Mastercard, linha 1")
    await user.click(screen.getByRole("button", { name: "Salvar" }))

    // item 2 enviado = (linha 2, Mastercard): 1x mastercard, 1x visa, 2x mastercard
    await waitFor(() =>
      expect(screen.getByLabelText("Mastercard, linha 2")).toHaveAttribute("aria-invalid", "true"),
    )
    expect(screen.getByLabelText("Visa, linha 1")).not.toHaveAttribute("aria-invalid")
  })
})

describe("Onboarding: vendedores e percentuais", () => {
  const VENDEDORES = {
    vendedores: [
      { id: "11111111-1111-4111-8111-111111111111", nome: "Ana", telefone: null, peso_percentual: "60.00", ativo: true },
      { id: "22222222-2222-4222-8222-222222222222", nome: "Bruno", telefone: null, peso_percentual: "40.00", ativo: true },
    ],
  }

  it("não salva quando a soma dos % não dá 100 e mostra quanto falta", async () => {
    params = new URLSearchParams("passo=vendedores")
    const { cliente, chamadas } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/vendedores`]: { corpo: VENDEDORES },
      [`PUT /lojas/${LOJA}/config/vendedores`]: { corpo: VENDEDORES },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    const bruno = await screen.findByLabelText("Percentual (%), linha 2")
    expect(screen.getByText(/soma: 100%/i)).toBeInTheDocument()
    await user.clear(bruno)
    await user.type(bruno, "30")
    expect(screen.getByText(/soma: 90%/i)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Salvar" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(/somar 100/i)
    expect(chamadas.some((c) => c.method === "PUT")).toBe(false)
  })

  it("com soma 100 envia a lista mantendo o id dos existentes e criando os novos", async () => {
    params = new URLSearchParams("passo=vendedores")
    let corpoPut: { vendedores: Record<string, unknown>[] } | null = null
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/vendedores`]: { corpo: VENDEDORES },
      [`PUT /lojas/${LOJA}/config/vendedores`]: async (req) => {
        corpoPut = await req.json()
        return { corpo: VENDEDORES }
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    const bruno = await screen.findByLabelText("Percentual (%), linha 2")
    await user.clear(bruno)
    await user.type(bruno, "30")
    await user.click(screen.getByRole("button", { name: "Adicionar vendedor" }))
    await user.type(screen.getByLabelText("Nome, linha 3"), "Carla")
    await user.type(screen.getByLabelText("Percentual (%), linha 3"), "10")
    await user.click(screen.getByRole("button", { name: "Salvar" }))

    await waitFor(() => expect(corpoPut).not.toBeNull())
    const lista = corpoPut!.vendedores
    expect(lista.map((v) => v.nome)).toEqual(["Ana", "Bruno", "Carla"])
    expect(lista[0].id).toBe("11111111-1111-4111-8111-111111111111")
    expect(lista[2].id).toBeNull()
    expect(lista.map((v) => v.peso_percentual)).toEqual([60, 30, 10])
  })

  it("erro do servidor no percentual cai na célula da linha", async () => {
    params = new URLSearchParams("passo=vendedores")
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/vendedores`]: { corpo: VENDEDORES },
      [`PUT /lojas/${LOJA}/config/vendedores`]: {
        status: 422,
        corpo: { erros: [{ caminho: "vendedores[1].nome", mensagem: "Informe o nome do vendedor." }] },
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)
    await screen.findByLabelText("Nome, linha 2")
    await user.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(screen.getByLabelText("Nome, linha 2")).toHaveAttribute("aria-invalid", "true"))
    expect(screen.getByLabelText("Nome, linha 1")).not.toHaveAttribute("aria-invalid")
  })
})

describe("Onboarding: importar planilha", () => {
  function arquivo() {
    return new File(["xlsx"], "troca.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    })
  }

  it("valida primeiro e lista os erros por célula, sem oferecer aplicar", async () => {
    params = new URLSearchParams("passo=troca")
    const { cliente, chamadas } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/troca`]: { corpo: trocaComDuasLinhas() },
      [`POST /lojas/${LOJA}/importar/troca`]: {
        status: 422,
        corpo: {
          ok: false,
          erros: [{ caminho: "troca!D7", mensagem: "Desconto maior que o valor base." }],
          resumo: {},
        },
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    await screen.findByLabelText("Modelo, linha 1")
    await user.upload(screen.getByLabelText("Arquivo da planilha"), arquivo())

    const lista = await screen.findByRole("list", { name: /erros da planilha/i })
    const item = within(lista).getByRole("listitem")
    expect(item).toHaveTextContent("linha 7")
    expect(item).toHaveTextContent("Desconto tela")
    expect(item).toHaveTextContent("D7")
    expect(item).toHaveTextContent("Desconto maior que o valor base.")
    expect(screen.queryByRole("button", { name: /aplicar importação/i })).not.toBeInTheDocument()
    const post = chamadas.find((c) => c.method === "POST")!
    expect(new URL(post.url).searchParams.get("modo")).toBe("validar")
  })

  it("planilha válida: mostra o resumo e só grava ao aplicar; depois recarrega a grade", async () => {
    params = new URLSearchParams("passo=troca")
    const modos: string[] = []
    const { cliente, chamadas } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/troca`]: { corpo: trocaComDuasLinhas() },
      [`POST /lojas/${LOJA}/importar/troca`]: (req) => {
        modos.push(new URL(req.url).searchParams.get("modo") ?? "")
        return { corpo: { ok: true, erros: [], resumo: { linhas: 12, apple: 12, outras_marcas: 0 } } }
      },
    })
    const user = userEvent.setup()
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)

    await screen.findByLabelText("Modelo, linha 1")
    await user.upload(screen.getByLabelText("Arquivo da planilha"), arquivo())
    expect(await screen.findByText(/planilha válida/i)).toBeInTheDocument()
    expect(screen.getByText(/12 linhas/i)).toBeInTheDocument()
    expect(modos).toEqual(["validar"])

    await user.click(screen.getByRole("button", { name: /aplicar importação/i }))
    await waitFor(() => expect(modos).toEqual(["validar", "aplicar"]))
    await waitFor(() =>
      expect(chamadas.filter((c) => c.method === "GET" && c.url.endsWith("/config/troca"))).toHaveLength(2),
    )
    expect(screen.queryByRole("button", { name: /aplicar importação/i })).not.toBeInTheDocument()
  })

  it("oferece o download do modelo vazio", async () => {
    params = new URLSearchParams("passo=estoque")
    const { cliente } = apiFalsa({
      [`GET ${CHECKLIST}`]: { corpo: { itens: ITENS } },
      [`GET /lojas/${LOJA}/config/estoque`]: { corpo: { estoque: [] } },
      [`GET /lojas/${LOJA}/config/mapeamento-sku`]: { corpo: { mapeamento_sku: [] } },
    })
    render(<Onboarding cliente={cliente} lojaId={LOJA} />)
    const link = await screen.findByRole("link", { name: /baixar modelo/i })
    expect(link.getAttribute("href")).toMatch(/\/modelos\/estoque$/)
  })
})
