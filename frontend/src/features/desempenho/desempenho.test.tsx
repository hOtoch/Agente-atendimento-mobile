import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { cloneElement, type ReactElement } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Metricas } from "@/lib/api"

import { Desempenho } from "./desempenho"
import { metricasCompletas, metricasVazias } from "./fixtures"

const mocks = vi.hoisted(() => ({ GET: vi.fn() }))

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>()
  return { ...real, api: { GET: mocks.GET } }
})

// O jsdom não mede layout: damos tamanho fixo ao gráfico para exercitar o desenho de verdade.
vi.mock("recharts", async (importOriginal) => {
  const real = await importOriginal<typeof import("recharts")>()
  return {
    ...real,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div style={{ width: 600, height: 300 }}>{cloneElement(children, { width: 600, height: 300 })}</div>
    ),
  }
})

const LOJA = "00000000-0000-4000-8000-00000000de30"
const HOJE = new Date("2026-11-22T15:00:00Z")

function responder(metricas: Metricas) {
  mocks.GET.mockResolvedValue({ data: metricas })
}

async function abrir() {
  render(<Desempenho lojaId={LOJA} hoje={HOJE} />)
  await screen.findByRole("group", { name: "Conversas atendidas" })
}

const tile = (nome: string) => screen.getByRole("group", { name: nome })

beforeEach(() => {
  mocks.GET.mockReset()
  responder(metricasCompletas())
})

describe("Desempenho: visão geral", () => {
  it("mostra os KPIs com valores formatados em pt-BR e variação contra o período anterior", async () => {
    await abrir()

    expect(within(tile("Conversas atendidas")).getByText("120")).toBeInTheDocument()
    expect(within(tile("Conversas atendidas")).getByText(/\+20%/)).toBeInTheDocument()
    expect(within(tile("Acordos fechados")).getByText("15")).toBeInTheDocument()
    expect(within(tile("Taxa de conversão")).getByText("12,5%")).toBeInTheDocument()
    expect(within(tile("Gasto com a IA")).getByText("US$ 15,30")).toBeInTheDocument()
    expect(within(tile("Custo por conversa")).getByText("US$ 0,1275")).toBeInTheDocument()
    expect(within(tile("Tempo médio de resposta")).getByText("2,4 s")).toBeInTheDocument()
    expect(within(tile("Passadas ao vendedor")).getByText("10%")).toBeInTheDocument()
    expect(within(tile("Erros")).getByText("5")).toBeInTheDocument()
  })

  it("a cor da variação depende de o indicador subir ser bom ou ruim", async () => {
    await abrir()

    // acordos +50%: subir é bom
    expect(within(tile("Acordos fechados")).getByText(/\+50%/).closest("[data-tom]")).toHaveAttribute(
      "data-tom",
      "bom",
    )
    // gasto +50%: subir NÃO é bom
    expect(within(tile("Gasto com a IA")).getByText(/\+50%/).closest("[data-tom]")).toHaveAttribute(
      "data-tom",
      "ruim",
    )
    // tempo de resposta -20%: cair é bom
    expect(within(tile("Tempo médio de resposta")).getByText(/-20%/).closest("[data-tom]")).toHaveAttribute(
      "data-tom",
      "bom",
    )
  })

  it("a variação tem texto para leitor de tela, não só seta e cor", async () => {
    await abrir()
    expect(
      within(tile("Gasto com a IA")).getByText(/aumento de 50% em relação ao período anterior/i),
    ).toBeInTheDocument()
  })

  it("latência sem medição aparece como traço com a dica", async () => {
    const m = metricasCompletas()
    m.kpis.tempo_resposta_media_ms = { valor: null, anterior: null, variacao_pct: null }
    responder(m)
    await abrir()

    const t = tile("Tempo médio de resposta")
    expect(within(t).getByText("—")).toBeInTheDocument()
    expect(within(t).getByTitle("sem medição no período")).toBeInTheDocument()
  })

  it("mostra o intervalo de datas do período", async () => {
    await abrir()
    expect(screen.getByText("24/10/2026 a 22/11/2026")).toBeInTheDocument()
  })
})

describe("Desempenho: período", () => {
  it("padrão de 30 dias: busca com de/ate de hoje para trás", async () => {
    await abrir()
    expect(mocks.GET).toHaveBeenCalledTimes(1)
    expect(mocks.GET).toHaveBeenCalledWith("/lojas/{loja_id}/metricas", {
      params: { path: { loja_id: LOJA }, query: { de: "2026-10-24", ate: "2026-11-22" } },
    })
    expect(screen.getByRole("button", { name: "30 dias" })).toHaveAttribute("aria-pressed", "true")
  })

  it("trocar o período refaz a busca com de/ate corretos", async () => {
    const user = userEvent.setup()
    await abrir()

    await user.click(screen.getByRole("button", { name: "7 dias" }))
    await waitFor(() => expect(mocks.GET).toHaveBeenCalledTimes(2))
    expect(mocks.GET).toHaveBeenLastCalledWith("/lojas/{loja_id}/metricas", {
      params: { path: { loja_id: LOJA }, query: { de: "2026-11-16", ate: "2026-11-22" } },
    })
    expect(screen.getByRole("button", { name: "7 dias" })).toHaveAttribute("aria-pressed", "true")

    await user.click(screen.getByRole("button", { name: "90 dias" }))
    await waitFor(() => expect(mocks.GET).toHaveBeenCalledTimes(3))
    expect(mocks.GET).toHaveBeenLastCalledWith("/lojas/{loja_id}/metricas", {
      params: { path: { loja_id: LOJA }, query: { de: "2026-08-25", ate: "2026-11-22" } },
    })
    // Renderiza a tela inteira (com gráficos) três vezes no jsdom: passa de 5 s em máquina lenta.
  }, 15_000)

  it("enquanto recarrega mantém o conteúdo anterior na tela (sem voltar ao esqueleto)", async () => {
    const user = userEvent.setup()
    await abrir()
    mocks.GET.mockReturnValue(new Promise(() => {}))

    await user.click(screen.getByRole("button", { name: "7 dias" }))

    expect(within(tile("Conversas atendidas")).getByText("120")).toBeInTheDocument()
    expect(document.querySelector("[aria-busy='true']")).not.toBeNull()
  })
})

describe("Desempenho: estados", () => {
  it("mostra o esqueleto enquanto carrega", () => {
    mocks.GET.mockReturnValue(new Promise(() => {}))
    render(<Desempenho lojaId={LOJA} hoje={HOJE} />)
    expect(screen.getByLabelText("Carregando desempenho")).toBeInTheDocument()
  })

  it("sem dados explica que o painel enche conforme a IA atende", async () => {
    responder(metricasVazias())
    render(<Desempenho lojaId={LOJA} hoje={HOJE} />)

    expect(await screen.findByText("Ainda não há dados neste período")).toBeInTheDocument()
    expect(screen.getByText(/conforme a IA atender/i)).toBeInTheDocument()
    expect(screen.queryByRole("group", { name: "Conversas atendidas" })).toBeNull()
    // o seletor de período continua disponível
    expect(screen.getByRole("button", { name: "90 dias" })).toBeInTheDocument()
  })

  it("erro da API mostra mensagem e tentar de novo refaz a busca", async () => {
    const user = userEvent.setup()
    mocks.GET.mockResolvedValueOnce({ error: { erros: [{ caminho: "", mensagem: "falhou" }] } })
    render(<Desempenho lojaId={LOJA} hoje={HOJE} />)

    expect(await screen.findByText("Não foi possível carregar o desempenho")).toBeInTheDocument()

    responder(metricasCompletas())
    await user.click(screen.getByRole("button", { name: "Tentar de novo" }))
    expect(await screen.findByRole("group", { name: "Conversas atendidas" })).toBeInTheDocument()
    expect(mocks.GET).toHaveBeenCalledTimes(2)
  })

  it("falha de rede também cai no estado de erro", async () => {
    mocks.GET.mockRejectedValueOnce(new Error("rede"))
    render(<Desempenho lojaId={LOJA} hoje={HOJE} />)
    expect(await screen.findByText("Não foi possível carregar o desempenho")).toBeInTheDocument()
  })
})

describe("Desempenho: custo", () => {
  it("avisa quando o total exclui modelos sem preço", async () => {
    responder(
      metricasCompletas({
        custo: { total_usd: "15.3", completo: false, modelos_sem_preco: ["modelo-novo"], por_modelo: [] },
      }),
    )
    await abrir()
    const aviso = screen.getByRole("status")
    expect(aviso).toHaveTextContent(/não inclui/i)
    expect(aviso).toHaveTextContent("modelo-novo")
  })

  it("sem modelos sem preço não mostra aviso", async () => {
    await abrir()
    expect(screen.queryByText(/não inclui/i)).toBeNull()
  })

  it("mostra aproveitamento do cache e custo por acordo", async () => {
    await abrir()
    const cache = tile("Aproveitamento do cache")
    expect(within(cache).getByText("90%")).toBeInTheDocument()
    expect(within(cache).getByRole("meter")).toHaveAttribute("aria-valuenow", "90")
    expect(within(tile("Custo por acordo")).getByText("US$ 1,02")).toBeInTheDocument()
  })
})

describe("Desempenho: gráficos acessíveis", () => {
  it("cada seção e cada gráfico têm título e descrição", async () => {
    await abrir()
    for (const secao of ["Visão geral", "Volume", "Resultado", "Custo e uso", "Qualidade", "Demanda"]) {
      expect(screen.getByRole("heading", { level: 2, name: secao })).toBeInTheDocument()
    }
    for (const grafico of [
      "Conversas por dia",
      "Mensagens recebidas por dia",
      "Funil de vendas",
      "Passadas ao vendedor, por motivo",
      "Gasto por dia",
      "Tokens por tipo",
      "Tempo de resposta por dia",
      "Tempo de processamento da IA por dia",
      "Erros por tipo",
      "Modelos mais procurados",
      "Horários de pico",
    ]) {
      const regiao = screen.getByRole("region", { name: grafico })
      expect(regiao).toBeInTheDocument()
      expect(within(regiao).getByText(/\S{3,}/, { selector: "[data-slot='card-description']" })).toBeInTheDocument()
    }
  })

  it("o funil tem alternativa em tabela com leads e variação", async () => {
    const user = userEvent.setup()
    await abrir()
    const regiao = screen.getByRole("region", { name: "Funil de vendas" })

    await user.click(within(regiao).getByText("Ver dados em tabela"))

    const tabela = within(regiao).getByRole("table")
    const linha = within(tabela).getByRole("row", { name: /Novo contato/ })
    expect(within(linha).getByText("40")).toBeInTheDocument()
    expect(within(linha).getByText("30")).toBeInTheDocument()
  })

  it("a tabela de volume lista um dia por linha, em dia/mês", async () => {
    const user = userEvent.setup()
    await abrir()
    const regiao = screen.getByRole("region", { name: "Conversas por dia" })
    await user.click(within(regiao).getByText("Ver dados em tabela"))
    expect(within(regiao).getByRole("row", { name: /24\/10/ })).toBeInTheDocument()
    expect(within(regiao).getAllByRole("row")).toHaveLength(31) // cabeçalho + 30 dias
  })

  it("latência nula no dia aparece como traço na tabela", async () => {
    const user = userEvent.setup()
    await abrir()
    const regiao = screen.getByRole("region", { name: "Tempo de resposta por dia" })
    await user.click(within(regiao).getByText("Ver dados em tabela"))
    const primeira = within(regiao).getByRole("row", { name: /24\/10/ })
    expect(within(primeira).getAllByText("—")).toHaveLength(2)
  })
})

describe("Desempenho: demanda", () => {
  it("o mapa de horários cobre 7 dias x 24 horas, com zeros onde não houve mensagens", async () => {
    await abrir()
    const tabela = screen.getByRole("table", { name: /mapa de horários/i })
    const linhas = within(tabela).getAllByRole("row")
    expect(linhas).toHaveLength(8) // cabeçalho das horas + 7 dias

    expect(within(tabela).getByTitle("Segunda-feira, 14h: 32 mensagens")).toBeInTheDocument()
    expect(within(tabela).getByTitle("Domingo, 3h: 0 mensagens")).toBeInTheDocument()
    expect(within(tabela).getAllByTitle(/: 0 mensagens/)).toHaveLength(7 * 24 - 3)
  })

  it("lista os horários de pico em texto", async () => {
    await abrir()
    const regiao = screen.getByRole("region", { name: "Horários de pico" })
    expect(within(regiao).getByText(/Segunda-feira, 14h/)).toBeInTheDocument()
  })

  it("modelos mais procurados aparecem na tabela alternativa", async () => {
    const user = userEvent.setup()
    await abrir()
    const regiao = screen.getByRole("region", { name: "Modelos mais procurados" })
    await user.click(within(regiao).getByText("Ver dados em tabela"))
    expect(within(regiao).getByRole("row", { name: /iPhone 13 128GB/ })).toHaveTextContent("18")
  })
})
