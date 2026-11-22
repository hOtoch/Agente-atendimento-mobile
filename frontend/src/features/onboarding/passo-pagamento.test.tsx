import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { PassoPagamento } from "./passo-pagamento"

const LOJA = "00000000-0000-4000-8000-00000000de30"
const ROTA = `/lojas/${LOJA}/config/pagamento`

function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
}

const PAGAMENTO = {
  aceita_pix: true,
  aceita_debito: true,
  aceita_credito: true,
  aceita_entrada_mais_credito: true,
  chave_pix_tipo: "email",
  chave_pix: "pix@lojademo.exemplo",
  chave_pix_favorecido: "Loja Demo Celulares",
}

function preparar(pagamento: Record<string, unknown>, aoPut?: () => { status: number; corpo: unknown }) {
  const enviados: Record<string, unknown>[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    if (new URL(req.url).pathname !== ROTA) return json({}, 404)
    if (req.method === "PUT") {
      enviados.push(await req.json())
      const r = aoPut?.()
      return r ? json(r.corpo, r.status) : json(pagamento)
    }
    return json(pagamento)
  })
  const aoSalvar = vi.fn()
  render(
    <PassoPagamento cliente={criarCliente("http://api.local", fetchFalso)} lojaId={LOJA} aoSalvar={aoSalvar} />,
  )
  return { enviados, aoSalvar }
}

describe("PassoPagamento", () => {
  it("mostra as formas e a chave Pix como vieram da API", async () => {
    preparar({ ...PAGAMENTO, aceita_debito: false })
    expect(await screen.findByRole("checkbox", { name: /^pix/i })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: /débito/i })).not.toBeChecked()
    expect(screen.getByRole("checkbox", { name: /^cartão de crédito/i })).toBeChecked()
    expect(screen.getByLabelText("Chave Pix")).toHaveValue("pix@lojademo.exemplo")
    expect(screen.getByLabelText("Favorecido")).toHaveValue("Loja Demo Celulares")
    expect(screen.getByRole("combobox", { name: "Tipo da chave" })).toHaveTextContent("E-mail")
  })

  it("informa que entrada + cartão vem das regras de preço", async () => {
    preparar(PAGAMENTO)
    expect(await screen.findByText(/entrada \+ cartão: aceita/i)).toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: /entrada/i })).not.toBeInTheDocument()
  })

  it("desligar uma forma e salvar envia a flag e a chave", async () => {
    const { enviados, aoSalvar } = preparar(PAGAMENTO)
    await userEvent.click(await screen.findByRole("checkbox", { name: /débito/i }))
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(enviados).toHaveLength(1))
    expect(enviados[0]).toEqual({
      aceita_pix: true,
      aceita_debito: false,
      aceita_credito: true,
      chave_pix_tipo: "email",
      chave_pix: "pix@lojademo.exemplo",
      chave_pix_favorecido: "Loja Demo Celulares",
    })
    await waitFor(() => expect(aoSalvar).toHaveBeenCalled())
  })

  it("chave em branco é enviada como null nos três campos", async () => {
    const { enviados } = preparar({
      ...PAGAMENTO,
      chave_pix_tipo: null,
      chave_pix: null,
      chave_pix_favorecido: null,
    })
    await screen.findByLabelText("Chave Pix")
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }))
    await waitFor(() => expect(enviados).toHaveLength(1))
    expect(enviados[0]).toMatchObject({
      chave_pix_tipo: null,
      chave_pix: null,
      chave_pix_favorecido: null,
    })
  })

  it("avisa quando o Pix está aceito sem chave", async () => {
    preparar({ ...PAGAMENTO, chave_pix_tipo: null, chave_pix: null, chave_pix_favorecido: null })
    expect(await screen.findByText(/cadastre a chave pix/i)).toBeInTheDocument()
  })

  it("mostra o erro da API no campo da chave", async () => {
    preparar(PAGAMENTO, () => ({
      status: 422,
      corpo: { erros: [{ caminho: "chave_pix", mensagem: "CPF inválido: informe 11 dígitos." }] },
    }))
    await userEvent.click(await screen.findByRole("button", { name: "Salvar" }))
    expect(await screen.findByText("CPF inválido: informe 11 dígitos.")).toBeInTheDocument()
    expect(screen.getByLabelText("Chave Pix")).toHaveAttribute("aria-invalid", "true")
  })
})
