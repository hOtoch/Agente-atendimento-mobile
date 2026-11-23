import { describe, expect, it, vi } from "vitest"

import {
  criarCliente,
  criarClientePublico,
  mensagemDeErro,
  registrarAoNaoAutorizado,
  type DetalheLead,
  type Kanban,
} from "./cliente"

const LOJA = "11111111-1111-1111-1111-111111111111"
const LEAD = "22222222-2222-2222-2222-222222222222"

function respostaJson(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("cliente da API do painel", () => {
  it("lista os leads por etapa em GET /lojas/{id}/leads, tipado", async () => {
    const kanban: Kanban = {
      etapas: [{ etapa: "novo_contato", nome: "Novo contato", leads: [] }],
    }
    const fetchFalso = vi.fn<(req: Request) => Promise<Response>>(async () => respostaJson(kanban))
    const api = criarCliente("http://api.local", fetchFalso)

    const { data, error } = await api.GET("/lojas/{loja_id}/leads", {
      params: { path: { loja_id: LOJA } },
    })

    expect(error).toBeUndefined()
    expect(data?.etapas[0].etapa).toBe("novo_contato")
    const req = fetchFalso.mock.calls[0][0]
    expect(req.method).toBe("GET")
    expect(req.url).toBe(`http://api.local/lojas/${LOJA}/leads`)
  })

  it("move a etapa com POST e corpo tipado; 409 volta em `error` com a mensagem", async () => {
    const fetchFalso = vi.fn<(req: Request) => Promise<Response>>(async () =>
      respostaJson({ erros: [{ caminho: "etapa", mensagem: "Venda fechada e uma etapa final." }] }, 409),
    )
    const api = criarCliente("http://api.local", fetchFalso)

    const { data, error, response } = await api.POST("/lojas/{loja_id}/leads/{lead_id}/etapa", {
      params: { path: { loja_id: LOJA, lead_id: LEAD } },
      body: { etapa: "novo_contato" },
    })

    expect(data).toBeUndefined()
    expect(response.status).toBe(409)
    expect(mensagemDeErro(error)).toBe("Venda fechada e uma etapa final.")
    const req = fetchFalso.mock.calls[0][0]
    expect(req.url).toBe(`http://api.local/lojas/${LOJA}/leads/${LEAD}/etapa`)
    expect(await req.json()).toEqual({ etapa: "novo_contato" })
  })

  it("mensagemDeErro tem texto padrao quando o corpo nao e o formato da API", () => {
    expect(mensagemDeErro(undefined)).toBe("Erro inesperado.")
    expect(mensagemDeErro({ detail: "x" })).toBe("Erro inesperado.")
  })

  it("expoe os tipos do detalhe do lead", () => {
    const detalhe = {} as DetalheLead
    // checagem de compilacao: campos do contrato
    const _campos: [unknown, unknown, unknown, unknown] = [
      detalhe.card?.dono,
      detalhe.pendencias,
      detalhe.mensagens,
      detalhe.eventos,
    ]
    expect(_campos).toHaveLength(4)
  })
})

describe("cookies de sessão e 401", () => {
  const rota = { params: { path: { loja_id: LOJA } } }
  const resp = (status: number) => async () =>
    respostaJson({ erros: [{ caminho: "x", mensagem: "x" }] }, status)

  it("o cliente do painel envia credentials: include", async () => {
    const fetchFalso = vi.fn<(req: Request) => Promise<Response>>(async () => respostaJson({ etapas: [] }))
    await criarCliente("http://api.local", fetchFalso).GET("/lojas/{loja_id}/leads", rota)
    expect(fetchFalso.mock.calls[0][0].credentials).toBe("include")
  })

  it("o cliente público (chat web) usa o credentials padrão, sem cookies", async () => {
    const fetchFalso = vi.fn<(req: Request) => Promise<Response>>(async () => respostaJson({ etapas: [] }))
    await criarClientePublico("http://api.local", fetchFalso).GET("/lojas/{loja_id}/leads", rota)
    expect(fetchFalso.mock.calls[0][0].credentials).toBe("same-origin")
  })

  it("401 e 403 avisam o handler registrado; login com senha errada não", async () => {
    const aviso = vi.fn()
    const parar = registrarAoNaoAutorizado(aviso)

    await criarCliente("http://api.local", resp(401)).GET("/lojas/{loja_id}/leads", rota)
    expect(aviso).toHaveBeenCalledTimes(1)
    await criarCliente("http://api.local", resp(403)).GET("/lojas/{loja_id}/leads", rota)
    expect(aviso).toHaveBeenCalledTimes(2)
    await criarCliente("http://api.local", resp(401)).POST("/auth/login", {
      body: { email: "a@b.com", senha: "x" },
    })
    expect(aviso).toHaveBeenCalledTimes(2)

    parar()
    await criarCliente("http://api.local", resp(401)).GET("/lojas/{loja_id}/leads", rota)
    expect(aviso).toHaveBeenCalledTimes(2)
  })
})
