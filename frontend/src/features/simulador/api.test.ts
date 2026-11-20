// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { assinarSessao, criarServicoWebchat, type MensagemWebchat } from "./api"

const LOJA = "11111111-1111-1111-1111-111111111111"
const BASE = "http://api.local"

type Chamada = { url: string; metodo: string; corpo: unknown }

function fetchFalso(respostas: Record<string, { status: number; corpo: unknown }>) {
  const chamadas: Chamada[] = []
  const impl = async (req: Request) => {
    const url = new URL(req.url)
    const chave = `${req.method} ${url.pathname}`
    let corpo: unknown = null
    if ((req.headers.get("content-type") ?? "").includes("json")) corpo = await req.clone().json()
    else if ((req.headers.get("content-type") ?? "").includes("multipart")) corpo = await req.clone().formData()
    chamadas.push({ url: req.url, metodo: req.method, corpo })
    const r = respostas[chave]
    if (!r) throw new Error(`sem resposta para ${chave}`)
    return new Response(JSON.stringify(r.corpo), {
      status: r.status,
      headers: { "content-type": "application/json" },
    })
  }
  return { impl, chamadas }
}

class EventSourceFalso {
  static instancias: EventSourceFalso[] = []
  onmessage: ((e: MessageEvent<string>) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  closed = false
  constructor(public url: string) {
    EventSourceFalso.instancias.push(this)
  }
  close() {
    this.closed = true
  }
  emitir(dados: unknown) {
    this.onmessage?.({ data: typeof dados === "string" ? dados : JSON.stringify(dados) } as MessageEvent<string>)
  }
}

beforeEach(() => {
  EventSourceFalso.instancias = []
  vi.stubGlobal("EventSource", EventSourceFalso)
})
afterEach(() => vi.unstubAllGlobals())

describe("servico do webchat", () => {
  it("cria a sessão", async () => {
    const f = fetchFalso({ [`POST /webchat/${LOJA}/sessoes`]: { status: 201, corpo: { sessao: "abc" } } })
    const servico = criarServicoWebchat(criarCliente(BASE, f.impl))
    expect(await servico.criarSessao(LOJA)).toBe("abc")
  })

  it("envia texto com id do cliente", async () => {
    const f = fetchFalso({
      [`POST /webchat/${LOJA}/sessoes/s1/mensagens`]: {
        status: 202,
        corpo: { conversa_id: "c", nova: true },
      },
    })
    const servico = criarServicoWebchat(criarCliente(BASE, f.impl))
    await servico.enviarTexto(LOJA, "s1", "id1", "oi")
    expect(f.chamadas[0].corpo).toEqual({ id_cliente: "id1", tipo: "texto", texto: "oi" })
  })

  it("envia mídia: upload multipart e depois a mensagem com a midia_url", async () => {
    const f = fetchFalso({
      [`POST /webchat/${LOJA}/midias`]: { status: 201, corpo: { midia_url: `${BASE}/midias/x.png` } },
      [`POST /webchat/${LOJA}/sessoes/s1/mensagens`]: {
        status: 202,
        corpo: { conversa_id: "c", nova: false },
      },
    })
    const servico = criarServicoWebchat(criarCliente(BASE, f.impl))
    const arquivo = new File(["x"], "foto.png", { type: "image/png" })

    const url = await servico.enviarMidia(LOJA, "s1", "id2", arquivo, "imagem")

    expect(url).toBe(`${BASE}/midias/x.png`)
    const upload = f.chamadas[0].corpo as FormData
    expect(upload.get("arquivo")).toBeInstanceOf(File)
    expect(f.chamadas[1].corpo).toEqual({
      id_cliente: "id2",
      tipo: "imagem",
      midia_url: `${BASE}/midias/x.png`,
    })
  })

  it("traduz erro da API (ex.: 413) na mensagem do corpo de erro", async () => {
    const f = fetchFalso({
      [`POST /webchat/${LOJA}/midias`]: {
        status: 413,
        corpo: { erros: [{ caminho: "arquivo", mensagem: "Arquivo acima do limite de 10 MB." }] },
      },
    })
    const servico = criarServicoWebchat(criarCliente(BASE, f.impl))
    const arquivo = new File(["x"], "foto.png", { type: "image/png" })
    await expect(servico.enviarMidia(LOJA, "s1", "id", arquivo, "imagem")).rejects.toThrow(
      "Arquivo acima do limite de 10 MB.",
    )
  })
})

describe("assinarSessao", () => {
  it("abre o EventSource do stream da sessão e entrega mensagens tipadas", () => {
    const recebidas: MensagemWebchat[] = []
    assinarSessao(LOJA, "s1", (m) => recebidas.push(m), { baseUrl: BASE })
    const es = EventSourceFalso.instancias[0]
    expect(es.url).toBe(`${BASE}/webchat/${LOJA}/sessoes/s1/stream`)

    es.emitir({ tipo: "texto", texto: "Olá!", midia_url: null, enviada_em: "2026-11-20T15:00:00Z" })
    es.emitir({ tipo: "audio", texto: null, midia_url: "http://x/a.webm", enviada_em: "2026-11-20T15:00:01Z" })

    expect(recebidas).toEqual([
      { tipo: "texto", texto: "Olá!", midia_url: null, enviada_em: "2026-11-20T15:00:00Z" },
      { tipo: "audio", texto: null, midia_url: "http://x/a.webm", enviada_em: "2026-11-20T15:00:01Z" },
    ])
  })

  it("ignora payload inválido e a função devolvida fecha a conexão", () => {
    const onMensagem = vi.fn()
    const cancelar = assinarSessao(LOJA, "s1", onMensagem, { baseUrl: BASE })
    const es = EventSourceFalso.instancias[0]
    es.emitir("nao e json")
    es.emitir({ tipo: "video", texto: "x" })
    es.emitir({ sem: "tipo" })
    expect(onMensagem).not.toHaveBeenCalled()
    cancelar()
    expect(es.closed).toBe(true)
  })
})
