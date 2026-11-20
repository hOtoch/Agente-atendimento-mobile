import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { DndContextProps } from "@dnd-kit/core"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { EventoPainel } from "@/lib/api"

import { CARD_A, CARD_B, CARD_C, LEAD_A, LEAD_C, VENDEDOR_ANA, colunas } from "./fixtures"
import { KanbanBoard } from "./kanban-board"

const mocks = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  assinar: vi.fn(),
  toast: { erro: vi.fn(), aviso: vi.fn(), sucesso: vi.fn(), info: vi.fn(), fechar: vi.fn() },
  dnd: { props: null as DndContextProps | null },
}))

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>()
  return { ...real, api: { GET: mocks.GET, POST: mocks.POST }, assinarEventosLoja: mocks.assinar }
})

vi.mock("@/components/ui/toast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/ui/toast")>()),
  useToast: () => mocks.toast,
}))

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const real = await importOriginal<typeof import("@dnd-kit/core")>()
  return {
    ...real,
    DndContext: (props: DndContextProps) => {
      mocks.dnd.props = props
      return <real.DndContext {...props} />
    },
  }
})

const LOJA = "00000000-0000-4000-8000-00000000de30"
let emitir: (e: EventoPainel) => void

function carregar(cards = [CARD_A, CARD_B, CARD_C]) {
  mocks.GET.mockResolvedValue({ data: { etapas: colunas(cards) } })
}

async function abrir() {
  render(<KanbanBoard lojaId={LOJA} />)
  await screen.findByText("Maria Souza")
}

function soltar(leadId: string, etapa: string) {
  return act(async () => {
    const active = { id: leadId } as never
    mocks.dnd.props?.onDragStart?.({ active } as never)
    mocks.dnd.props?.onDragEnd?.({ active, over: { id: etapa } } as never)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.assinar.mockImplementation((_loja: string, cb: (e: EventoPainel) => void) => {
    emitir = cb
    return vi.fn()
  })
  carregar()
})

describe("KanbanBoard", () => {
  it("mostra carregamento e depois as 5 colunas com contagem", async () => {
    await abrir()
    expect(mocks.GET).toHaveBeenCalledWith("/lojas/{loja_id}/leads", { params: { path: { loja_id: LOJA } } })
    for (const nome of [
      "Novo contato",
      "Interesse identificado",
      "Interesse qualificado",
      "Com o vendedor",
      "Venda fechada",
    ]) {
      expect(screen.getByRole("region", { name: new RegExp(`^${nome}`) })).toBeInTheDocument()
    }
    const novo = screen.getByRole("region", { name: /^Novo contato/ })
    expect(within(novo).getByText("1")).toBeInTheDocument()
  })

  it("card mostra nome, telefone, aparelho, valor, dono e tempo na etapa", async () => {
    await abrir()
    const card = screen.getByRole("group", { name: /Maria Souza/ })
    expect(within(card).getByText("5511988887777")).toBeInTheDocument()
    expect(within(card).getByText("iPhone 13 128GB")).toBeInTheDocument()
    expect(within(card).getByText(/R\$\s3\.499,90/)).toBeInTheDocument()
    expect(within(card).getByText("IA")).toBeInTheDocument()
    expect(within(card).getByText(/^há /)).toBeInTheDocument()
    expect(within(card).getByRole("link", { name: "Maria Souza" })).toHaveAttribute(
      "href",
      `/conversas?lead=${LEAD_A}`,
    )
    const joao = screen.getByRole("group", { name: /João Lima/ })
    expect(within(joao).getByText("Vendedor")).toBeInTheDocument()
    expect(within(joao).getByText("Ana Paula")).toBeInTheDocument()
  })

  it("estado vazio por coluna", async () => {
    carregar([CARD_A])
    await abrir()
    const col = screen.getByRole("region", { name: /^Venda fechada/ })
    expect(within(col).getByText("Nenhum lead")).toBeInTheDocument()
  })

  it("erro ao carregar mostra aviso com botão para tentar de novo", async () => {
    mocks.GET.mockResolvedValueOnce({ error: { erros: [{ caminho: "", mensagem: "Falhou." }] } })
    render(<KanbanBoard lojaId={LOJA} />)
    await userEvent.click(await screen.findByRole("button", { name: "Tentar de novo" }))
    expect(await screen.findByText("Maria Souza")).toBeInTheDocument()
  })

  it("evento SSE EtapaMudou move o card de coluna sozinho", async () => {
    await abrir()
    expect(mocks.assinar).toHaveBeenCalledWith(LOJA, expect.any(Function), expect.anything())
    act(() =>
      emitir({
        evento: "EtapaMudou",
        lead_id: LEAD_A,
        de: "novo_contato",
        para: "interesse_identificado",
        ator: "ia",
        motivo: "x",
        em: new Date().toISOString(),
      } as EventoPainel),
    )
    const destino = screen.getByRole("region", { name: /^Interesse identificado/ })
    expect(within(destino).getByText("Maria Souza")).toBeInTheDocument()
    const origem = screen.getByRole("region", { name: /^Novo contato/ })
    expect(within(origem).queryByText("Maria Souza")).not.toBeInTheDocument()
  })

  it("evento de lead desconhecido recarrega a lista", async () => {
    await abrir()
    carregar([CARD_A, CARD_B, CARD_C, { ...CARD_A, id: "novo-lead", nome: "Pedro Novo" }])
    act(() => emitir({ evento: "MensagemNova", lead_id: "novo-lead" } as unknown as EventoPainel))
    expect(await screen.findByText("Pedro Novo")).toBeInTheDocument()
  })

  it("DonoMudou atualiza o dono do card", async () => {
    await abrir()
    act(() =>
      emitir({
        evento: "DonoMudou",
        lead_id: LEAD_A,
        dono: `vendedor:${VENDEDOR_ANA}`,
        vendedor_id: VENDEDOR_ANA,
        em: new Date().toISOString(),
      } as EventoPainel),
    )
    const card = screen.getByRole("group", { name: /Maria Souza/ })
    expect(within(card).getByText("Vendedor")).toBeInTheDocument()
    expect(within(card).getByText("Ana Paula")).toBeInTheDocument()
  })

  it("arrasto permitido move o card na hora e confirma na API", async () => {
    mocks.POST.mockResolvedValue({ data: { ...CARD_A, etapa: "com_o_vendedor" } })
    await abrir()
    await soltar(LEAD_A, "com_o_vendedor")
    const destino = screen.getByRole("region", { name: /^Com o vendedor/ })
    expect(within(destino).getByText("Maria Souza")).toBeInTheDocument()
    expect(mocks.POST).toHaveBeenCalledWith("/lojas/{loja_id}/leads/{lead_id}/etapa", {
      params: { path: { loja_id: LOJA, lead_id: LEAD_A } },
      body: { etapa: "com_o_vendedor" },
    })
    expect(mocks.toast.erro).not.toHaveBeenCalled()
  })

  it("soltar na mesma coluna não faz nada", async () => {
    await abrir()
    await soltar(LEAD_A, "novo_contato")
    expect(mocks.POST).not.toHaveBeenCalled()
    expect(mocks.toast.erro).not.toHaveBeenCalled()
  })

  it("arrasto proibido (venda fechada): card volta, avisa e não chama a API", async () => {
    await abrir()
    act(() => {
      mocks.dnd.props?.onDragStart?.({ active: { id: LEAD_C } } as never)
      mocks.dnd.props?.onDragOver?.({ active: { id: LEAD_C }, over: { id: "novo_contato" } } as never)
    })
    const alvo = screen.getByRole("region", { name: /^Novo contato/ })
    expect(within(alvo).getByText("Venda fechada é uma etapa final.")).toBeInTheDocument()
    await soltar(LEAD_C, "novo_contato")
    expect(mocks.POST).not.toHaveBeenCalled()
    expect(mocks.toast.erro).toHaveBeenCalledWith("Venda fechada é uma etapa final.")
    const origem = screen.getByRole("region", { name: /^Venda fechada/ })
    expect(within(origem).getByText("Carla Dias")).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: /^Novo contato/ })).queryByText("Carla Dias")).toBeNull()
    expect(screen.queryByText("Venda fechada é uma etapa final.")).not.toBeInTheDocument()
  })

  it("409 da API reverte o card e mostra a mensagem do servidor", async () => {
    mocks.POST.mockResolvedValue({
      error: { erros: [{ caminho: "etapa", mensagem: "Somente o vendedor move etapas." }] },
    })
    await abrir()
    await soltar(LEAD_A, "interesse_qualificado")
    await waitFor(() =>
      expect(mocks.toast.erro).toHaveBeenCalledWith("Não foi possível mover o lead", {
        descricao: "Somente o vendedor move etapas.",
      }),
    )
    const origem = screen.getByRole("region", { name: /^Novo contato/ })
    expect(within(origem).getByText("Maria Souza")).toBeInTheDocument()
  })

  it("filtra por vendedor e por IA", async () => {
    await abrir()
    const filtro = screen.getByRole("group", { name: "Filtrar por vendedor" })
    await userEvent.click(within(filtro).getByRole("button", { name: "Ana Paula" }))
    expect(screen.queryByText("Maria Souza")).not.toBeInTheDocument()
    expect(screen.getByText("João Lima")).toBeInTheDocument()
    await userEvent.click(within(filtro).getByRole("button", { name: "IA" }))
    expect(screen.getByText("Maria Souza")).toBeInTheDocument()
    expect(screen.queryByText("João Lima")).not.toBeInTheDocument()
    await userEvent.click(within(filtro).getByRole("button", { name: "Todos" }))
    expect(screen.getByText("João Lima")).toBeInTheDocument()
  })

  it("fecha a assinatura SSE ao desmontar", async () => {
    const fechar = vi.fn()
    mocks.assinar.mockImplementation(() => fechar)
    const { unmount } = render(<KanbanBoard lojaId={LOJA} />)
    await screen.findByText("Maria Souza")
    unmount()
    expect(fechar).toHaveBeenCalled()
  })
})
