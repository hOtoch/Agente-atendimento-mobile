import createClient, { type ClientOptions } from "openapi-fetch"

import type { components, paths } from "./schema"

/** Base da API; definida em build por `NEXT_PUBLIC_API_URL` (ver `.env.example`). */
export const URL_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

type Fetch = ClientOptions["fetch"]

let aoNaoAutorizado: (() => void) | null = null

/** Registra quem reage a 401/403 de qualquer chamada autenticada; devolve a função que desfaz. */
export function registrarAoNaoAutorizado(fn: () => void): () => void {
  aoNaoAutorizado = fn
  return () => {
    if (aoNaoAutorizado === fn) aoNaoAutorizado = null
  }
}

/** Avisa o handler registrado (usado pelo middleware do cliente e por quem detecta sessão inválida). */
export function notificarNaoAutorizado(): void {
  aoNaoAutorizado?.()
}

/**
 * Cliente tipado a partir do OpenAPI do backend (`npm run gerar:api`). Envia o cookie de sessão
 * (`credentials: "include"`); 401/403 (menos no próprio login) avisam o handler registrado.
 */
export function criarCliente(baseUrl: string = URL_API, fetchImpl?: Fetch) {
  const cliente = createClient<paths>({ baseUrl, fetch: fetchImpl, credentials: "include" })
  cliente.use({
    onResponse({ request, response }) {
      const ehLogin = new URL(request.url).pathname.endsWith("/auth/login")
      if ((response.status === 401 || response.status === 403) && !ehLogin) notificarNaoAutorizado()
      return undefined
    },
  })
  return cliente
}

/** Cliente sem cookies nem tratamento de sessão: chat web público do cliente da loja. */
export function criarClientePublico(baseUrl: string = URL_API, fetchImpl?: Fetch) {
  return createClient<paths>({ baseUrl, fetch: fetchImpl })
}

export const api = criarCliente()
export const apiPublica = criarClientePublico()

type Schemas = components["schemas"]

export type Etapa = Schemas["Etapa"]
export type Kanban = Schemas["KanbanSchema"]
export type ColunaKanban = Schemas["ColunaKanbanSchema"]
export type CardLead = Schemas["CardLeadSchema"]
export type DetalheLead = Schemas["DetalheLeadSchema"]
export type MensagemLead = Schemas["MensagemSchema"]
export type EventoLead = Schemas["EventoLeadSchema"]
export type ErrosApi = Schemas["ErrosSchema"]
export type Metricas = Schemas["MetricasSchema"]
export type Identidade = Schemas["IdentidadeSchema"]
export type EstadoConexao = Schemas["EstadoConexao"]

/** Primeira mensagem do corpo de erro uniforme da API (`{ erros: [{ caminho, mensagem }] }`). */
export function mensagemDeErro(erro: unknown): string {
  if (typeof erro === "object" && erro !== null && "erros" in erro) {
    const { erros } = erro as { erros: unknown }
    if (Array.isArray(erros) && typeof erros[0]?.mensagem === "string") {
      return erros[0].mensagem
    }
  }
  return "Erro inesperado."
}
