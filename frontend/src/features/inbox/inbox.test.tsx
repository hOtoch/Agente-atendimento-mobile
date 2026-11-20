import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { criarCliente, type CardLead, type DetalheLead, type EventoPainel } from "@/lib/api"

import {
  CARD_JOAO,
  CARD_MARIA,
  DETALHE_MARIA,
  LEAD_JOAO,
  LEAD_MARIA,
  LEAD_SUMIDO,
  LOJA,
  VENDEDORES,
  VENDEDOR_ANA,
  VENDEDOR_BRUNO,
  card,
  detalhe,
  mensagem,
} from "./fixtures"
import { Inbox } from "./inbox"

const toast = vi.hoisted(() => ({ erro: vi.fn(), aviso: vi.fn(), sucesso: vi.fn(), info: vi.fn(), fechar: vi.fn() }))
vi.mock("@/components/ui/toast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/ui/toast")>()),
  useToast: () => toast,
}))

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
}

/** API falsa com estado: assumir/devolver/mensagens alteram o que o GET devolve. */
function montarApi(opcoes: { cards?: CardLead[]; detalhes?: Record<string, DetalheLead> } = {}) {
  const cards = opcoes.cards ?? [CARD_MARIA, CARD_JOAO]
  const detalhes: Record<string, DetalheLead> = opcoes.detalhes ?? {
    [LEAD_MARIA]: structuredClone(DETALHE_MARIA),
    [LEAD_JOAO]: detalhe({ card: CARD_JOAO }),
  }
  const chamadas: { metodo: string; caminho: string; corpo?: unknown }[] = []
  const respostas: Record<string, { status: number; corpo: unknown } | undefined> = {}
  let enviada = true

  const fetchFalso = vi.fn(async (req: Request) => {
    const { pathname } = new URL(req.url)
    const texto = req.method === "POST" ? await req.clone().text() : ""
    const corpo = texto ? JSON.parse(texto) : undefined
    chamadas.push({ metodo: req.method, caminho: pathname, corpo })
    const chave = `${req.method} ${pathname.replace(`/lojas/${LOJA}`, "")}`

    const fixa = respostas[chave]
    if (fixa) return json(fixa.corpo, fixa.status)

    if (chave === "GET /leads") {
      const atuais = Object.values(detalhes).map((d) => d.card)
      const lista = opcoes.cards ? cards : atuais
      return json({ etapas: [{ etapa: "novo_contato", nome: "Novo contato", leads: lista }] })
    }
    if (chave === "GET /config/vendedores") return json({ vendedores: VENDEDORES })
    const m = chave.match(/^(GET|POST) \/leads\/([^/]+)(?:\/(\w+))?$/)
    if (m) {
      const [, metodo, id, acao] = m
      const d = detalhes[id]
      if (!d) return json({ erros: [{ caminho: "lead", mensagem: "Lead não encontrado." }] }, 404)
      if (metodo === "GET" && !acao) return json(structuredClone(d))
      if (acao === "assumir") {
        const vendedor = VENDEDORES.find((v) => v.id === corpo.vendedor_id)!
        d.card = { ...d.card, dono: `vendedor:${vendedor.id}`, vendedor_id: vendedor.id, vendedor_nome: vendedor.nome }
        return json(d.card)
      }
      if (acao === "devolver") {
        d.card = { ...d.card, dono: "ia", vendedor_id: null, vendedor_nome: null }
        return json(d.card)
      }
      if (acao === "mensagens") {
        const nova = mensagem({ id: `real-${d.mensagens.length}`, autor: "vendedor", texto: corpo.texto, criada_em: new Date().toISOString() })
        d.mensagens.push(nova)
        return json({ mensagem: nova, enviada }, 201)
      }
    }
    return json({ erros: [{ caminho: "rota", mensagem: `sem rota ${chave}` }] }, 404)
  })

  return {
    cliente: criarCliente("http://api.local", fetchFalso),
    chamadas,
    detalhes,
    responder: (chave: string, status: number, corpo: unknown) => (respostas[chave] = { status, corpo }),
    canalSemEnvio: () => (enviada = false),
    quantas: (chave: string) => chamadas.filter((c) => `${c.metodo} ${c.caminho.replace(`/lojas/${LOJA}`, "")}` === chave).length,
  }
}

let emitir: (e: EventoPainel) => void
const assinar = vi.fn((_l: string, onEvento: (e: EventoPainel) => void) => {
  emitir = (e) => act(() => onEvento(e))
  return vi.fn()
})

function Harness({ api, inicial = null }: { api: ReturnType<typeof montarApi>; inicial?: string | null }) {
  const [leadId, setLeadId] = useState<string | null>(inicial)
  return <Inbox lojaId={LOJA} leadId={leadId} onSelecionar={setLeadId} cliente={api.cliente} assinar={assinar} />
}

async function abrirConversa(api = montarApi(), inicial: string | null = LEAD_MARIA) {
  render(<Harness api={api} inicial={inicial} />)
  if (inicial) await screen.findByRole("heading", { name: /Maria Souza|Visitante/ })
  return api
}

const conversa = () => screen.getByRole("region", { name: "Conversa" })
const campo = () => screen.getByRole("textbox", { name: "Resposta ao cliente" })

beforeEach(() => {
  vi.clearAllMocks()
  try {
    window.localStorage.clear()
  } catch {
    // ignora
  }
})

describe("lista de conversas", () => {
  it("lista os leads e abre a conversa ao clicar", async () => {
    const user = userEvent.setup()
    const api = montarApi()
    render(<Harness api={api} />)
    const lista = await screen.findByRole("list", { name: "Conversas" })
    expect(within(lista).getAllByRole("button")).toHaveLength(2)
    expect(screen.getByText("Selecione uma conversa")).toBeInTheDocument()

    await user.click(within(lista).getByRole("button", { name: /Maria Souza/ }))
    expect(await screen.findByText("Oi, quero um iPhone 13")).toBeInTheDocument()
  })

  it("abre direto a conversa indicada pela URL", async () => {
    await abrirConversa()
    expect(screen.getByRole("heading", { name: "Maria Souza" })).toBeInTheDocument()
  })

  it("mostra estado vazio sem conversas", async () => {
    const api = montarApi({ cards: [], detalhes: {} })
    render(<Harness api={api} />)
    expect(await screen.findByText("Nenhuma conversa ainda")).toBeInTheDocument()
  })

  it("lead do chat web mostra 'Chat web' no lugar do telefone", async () => {
    const sessao = "f".repeat(32)
    const web = card({ id: LEAD_JOAO, canal: "webchat", telefone: sessao })
    const api = montarApi({ cards: [web], detalhes: { [LEAD_JOAO]: detalhe({ card: web }) } })
    render(<Harness api={api} inicial={LEAD_JOAO} />)
    expect(await screen.findByRole("heading", { name: "Visitante do chat web" })).toBeInTheDocument()
    expect(screen.queryByText(sessao)).not.toBeInTheDocument()
    expect(screen.getAllByText("Chat web").length).toBeGreaterThan(0)
  })
})

describe("conversa aberta", () => {
  it("renderiza balões de texto e áudio", async () => {
    await abrirConversa()
    expect(screen.getByText("Olá! Qual capacidade você procura?")).toBeInTheDocument()
    expect(document.querySelector("audio")).toHaveAttribute("src", "http://api.local/midias/a.ogg")
    const baloes = screen.getAllByTestId("balao")
    // cliente à esquerda, IA (lado atendente) à direita
    expect(baloes[0]).toHaveAttribute("data-alinhamento", "esquerda")
    expect(baloes[1]).toHaveAttribute("data-alinhamento", "direita")
  })

  it("lead inexistente mostra erro sem quebrar", async () => {
    const api = montarApi()
    render(<Harness api={api} inicial={LEAD_SUMIDO} />)
    expect(await screen.findByText("Não foi possível abrir a conversa")).toBeInTheDocument()
  })
})

describe("assumir e devolver", () => {
  it("com dono IA: campo desabilitado e 'IA atendendo'", async () => {
    await abrirConversa()
    expect(campo()).toBeDisabled()
    expect(screen.getByText("IA atendendo")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Assumir conversa" })).toBeEnabled()
    expect(screen.queryByRole("button", { name: "Devolver para a IA" })).not.toBeInTheDocument()
  })

  it("assumir troca o dono e habilita o campo", async () => {
    const user = userEvent.setup()
    const api = await abrirConversa()
    await user.click(screen.getByRole("button", { name: "Assumir conversa" }))

    await waitFor(() => expect(campo()).toBeEnabled())
    const chamada = api.chamadas.find((c) => c.caminho.endsWith("/assumir"))
    expect(chamada?.corpo).toEqual({ vendedor_id: VENDEDOR_ANA })
    expect(screen.queryByText("IA atendendo")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Devolver para a IA" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Assumir conversa" })).not.toBeInTheDocument()
  })

  it("assumir usa o vendedor escolhido em 'Atendendo como' (guardado no navegador)", async () => {
    window.localStorage.setItem(`inbox:vendedor-atual:${LOJA}`, VENDEDOR_BRUNO)
    const user = userEvent.setup()
    const api = await abrirConversa()
    await user.click(await screen.findByRole("button", { name: "Assumir conversa" }))
    await waitFor(() => expect(campo()).toBeEnabled())
    expect(api.chamadas.find((c) => c.caminho.endsWith("/assumir"))?.corpo).toEqual({ vendedor_id: VENDEDOR_BRUNO })
  })

  it("trocar o 'Atendendo como' muda quem assume e fica guardado", async () => {
    const user = userEvent.setup()
    const api = await abrirConversa()
    await user.click(await screen.findByRole("combobox", { name: "Atendendo como" }))
    await user.click(await screen.findByRole("option", { name: "Bruno Reis" }))
    expect(screen.queryByRole("option", { name: "Carlos Inativo" })).not.toBeInTheDocument()
    expect(window.localStorage.getItem(`inbox:vendedor-atual:${LOJA}`)).toBe(VENDEDOR_BRUNO)
    await user.click(screen.getByRole("button", { name: "Assumir conversa" }))
    await waitFor(() => expect(campo()).toBeEnabled())
    expect(api.chamadas.find((c) => c.caminho.endsWith("/assumir"))?.corpo).toEqual({ vendedor_id: VENDEDOR_BRUNO })
  })

  it("devolver desabilita o campo e mostra 'IA atendendo'", async () => {
    const user = userEvent.setup()
    const api = await abrirConversa()
    await user.click(screen.getByRole("button", { name: "Assumir conversa" }))
    await waitFor(() => expect(campo()).toBeEnabled())

    await user.click(screen.getByRole("button", { name: "Devolver para a IA" }))
    await waitFor(() => expect(campo()).toBeDisabled())
    expect(screen.getByText("IA atendendo")).toBeInTheDocument()
    expect(api.chamadas.some((c) => c.caminho.endsWith("/devolver"))).toBe(true)
  })

  it("409 ao assumir (outro vendedor pegou antes) avisa e mantém desabilitado", async () => {
    const user = userEvent.setup()
    const api = await abrirConversa()
    api.responder(`POST /leads/${LEAD_MARIA}/assumir`, 409, { erros: [{ caminho: "lead", mensagem: "Outro vendedor já assumiu esta conversa." }] })
    await user.click(screen.getByRole("button", { name: "Assumir conversa" }))
    await waitFor(() => expect(toast.erro).toHaveBeenCalled())
    expect(toast.erro.mock.calls[0][1]).toMatchObject({ descricao: "Outro vendedor já assumiu esta conversa." })
    expect(campo()).toBeDisabled()
  })

  it("dono é outro vendedor: mostra quem e não oferece assumir nem responder", async () => {
    const bruno = { ...CARD_MARIA, dono: `vendedor:${VENDEDOR_BRUNO}`, vendedor_id: VENDEDOR_BRUNO, vendedor_nome: "Bruno Reis" }
    const api = montarApi({ detalhes: { [LEAD_MARIA]: { ...structuredClone(DETALHE_MARIA), card: bruno } } })
    await abrirConversa(api)
    expect(screen.getByText("Atendida por Bruno Reis")).toBeInTheDocument()
    expect(campo()).toBeDisabled()
    expect(screen.queryByRole("button", { name: "Assumir conversa" })).not.toBeInTheDocument()
  })
})

describe("responder", () => {
  async function assumir(api = montarApi()) {
    const user = userEvent.setup()
    await abrirConversa(api)
    await user.click(screen.getByRole("button", { name: "Assumir conversa" }))
    await waitFor(() => expect(campo()).toBeEnabled())
    return { user, api }
  }

  it("envia a mensagem, limpa o campo e mostra o balão", async () => {
    const { user, api } = await assumir()
    await user.type(campo(), "Bom dia, Maria!")
    await user.click(screen.getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(within(conversa()).getByText("Bom dia, Maria!")).toBeInTheDocument())
    expect(api.chamadas.find((c) => c.caminho.endsWith("/mensagens"))?.corpo).toEqual({ texto: "Bom dia, Maria!" })
    expect(campo()).toHaveValue("")
  })

  it("não envia texto vazio", async () => {
    await assumir()
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled()
  })

  it("canal sem adaptador: balão avisa que não foi entregue ao canal", async () => {
    const api = montarApi()
    api.canalSemEnvio()
    const { user } = await assumir(api)
    await user.type(campo(), "Oi")
    await user.click(screen.getByRole("button", { name: "Enviar" }))
    expect(await screen.findByText("Salva no painel; o canal ainda não envia.")).toBeInTheDocument()
  })

  it("o eco SSE da mensagem enviada não duplica o balão", async () => {
    const { user } = await assumir()
    await user.type(campo(), "Já te ajudo")
    await user.click(screen.getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(within(conversa()).getByText("Já te ajudo")).toBeInTheDocument())
    emitir({
      evento: "MensagemNova", lead_id: LEAD_MARIA, conversa_id: "c", autor: "vendedor", direcao: "saida",
      tipo: "texto", texto: "Já te ajudo", midia_url: null, em: new Date().toISOString(),
    })
    expect(within(conversa()).getAllByText("Já te ajudo")).toHaveLength(1)
  })

  it("409 ao enviar sem ser o dono mostra o erro e preserva o texto", async () => {
    const { user, api } = await assumir()
    api.responder(`POST /leads/${LEAD_MARIA}/mensagens`, 409, { erros: [{ caminho: "lead", mensagem: "Assuma a conversa antes de responder." }] })
    await user.type(campo(), "Oi")
    await user.click(screen.getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(toast.erro).toHaveBeenCalled())
    expect(campo()).toHaveValue("Oi")
  })
})

describe("tempo real (SSE)", () => {
  const evento = (parcial: Record<string, unknown>) =>
    ({
      evento: "MensagemNova", lead_id: LEAD_MARIA, conversa_id: "c", autor: "cliente", direcao: "entrada",
      tipo: "texto", texto: null, midia_url: null, em: "2026-11-20T12:30:00Z", ...parcial,
    }) as EventoPainel

  it("mensagem nova da conversa aberta aparece no balão", async () => {
    await abrirConversa()
    emitir(evento({ texto: "Pode parcelar em 10x?" }))
    expect(await screen.findByText("Pode parcelar em 10x?")).toBeInTheDocument()
  })

  it("mensagem de outro lead não entra na conversa aberta", async () => {
    await abrirConversa()
    emitir(evento({ lead_id: LEAD_JOAO, texto: "Mensagem do João" }))
    expect(screen.queryByText("Mensagem do João")).not.toBeInTheDocument()
  })

  it("lead desconhecido recarrega a lista", async () => {
    const api = await abrirConversa()
    const antes = api.quantas("GET /leads")
    emitir(evento({ lead_id: LEAD_SUMIDO }))
    await waitFor(() => expect(api.quantas("GET /leads")).toBe(antes + 1))
  })

  it("mudança de dono por outro lugar habilita o campo ao vendedor atual", async () => {
    const api = await abrirConversa()
    expect(campo()).toBeDisabled()
    const d = api.detalhes[LEAD_MARIA]
    d.card = { ...d.card, dono: `vendedor:${VENDEDOR_ANA}`, vendedor_id: VENDEDOR_ANA, vendedor_nome: "Ana Paula" }
    emitir({ evento: "DonoMudou", lead_id: LEAD_MARIA, dono: `vendedor:${VENDEDOR_ANA}`, vendedor_id: VENDEDOR_ANA, em: "2026-11-20T12:31:00Z" })
    await waitFor(() => expect(campo()).toBeEnabled())
  })

  it("etapa nova aparece na ficha", async () => {
    await abrirConversa()
    const ficha = screen.getByRole("complementary", { name: "Ficha do lead" })
    expect(within(ficha).getByText("Interesse qualificado")).toBeInTheDocument()
    emitir({ evento: "EtapaMudou", lead_id: LEAD_MARIA, de: "interesse_qualificado", para: "com_o_vendedor", ator: "ia", motivo: "x", em: "2026-11-20T12:40:00Z" })
    expect(await within(ficha).findByText("Com o vendedor")).toBeInTheDocument()
  })
})

describe("painel da ficha", () => {
  it("mostra aparelho, troca, data, pagamento, pendências legíveis e proposta", async () => {
    await abrirConversa()
    const ficha = screen.getByRole("complementary", { name: "Ficha do lead" })
    expect(within(ficha).getByText("iPhone 13 · 128 GB · Azul")).toBeInTheDocument()
    expect(within(ficha).getByText("iPhone 11 · 64 GB (tela danificada, bateria 82%)")).toBeInTheDocument()
    expect(within(ficha).getByText("05/12/2026")).toBeInTheDocument()
    expect(within(ficha).getByText("Crédito em 10x · Visa")).toBeInTheDocument()
    expect(within(ficha).getByText("Confirmar o item no estoque")).toBeInTheDocument()
    expect(within(ficha).getByText("Câmera do usado")).toBeInTheDocument()
    expect(within(ficha).queryByText("estoque_confirmado")).not.toBeInTheDocument()
    expect(within(ficha).getByText(/R\$\s*2\.699,90/)).toBeInTheDocument()
  })

  it("no celular a ficha abre num painel lateral", async () => {
    const user = userEvent.setup()
    await abrirConversa()
    await user.click(screen.getByRole("button", { name: "Ver ficha" }))
    const painel = await screen.findByRole("dialog")
    expect(within(painel).getByText("iPhone 13 · 128 GB · Azul")).toBeInTheDocument()
  })

  it("resumo do handoff aparece quando o handoff foi solicitado", async () => {
    const api = montarApi({
      detalhes: {
        [LEAD_MARIA]: { ...structuredClone(DETALHE_MARIA), handoff_solicitado: true, motivo_handoff: "Quer negociar a troca" },
      },
    })
    await abrirConversa(api)
    const resumo = screen.getByRole("region", { name: "Resumo do handoff" })
    expect(within(resumo).getByText("Quer negociar a troca")).toBeInTheDocument()
    expect(within(resumo).getByText("Próximo passo")).toBeInTheDocument()
  })

  it("sem handoff e com a IA, não mostra o resumo", async () => {
    await abrirConversa()
    expect(screen.queryByRole("region", { name: "Resumo do handoff" })).not.toBeInTheDocument()
  })

  it("resumo aparece também quando o dono é vendedor", async () => {
    const user = userEvent.setup()
    await abrirConversa()
    await user.click(screen.getByRole("button", { name: "Assumir conversa" }))
    expect(await screen.findByRole("region", { name: "Resumo do handoff" })).toBeInTheDocument()
  })
})
