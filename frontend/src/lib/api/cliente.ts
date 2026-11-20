import createClient, { type ClientOptions } from "openapi-fetch"

import type { components, paths } from "./schema"

/** Base da API; definida em build por `NEXT_PUBLIC_API_URL` (ver `.env.example`). */
export const URL_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

/** Cliente tipado a partir do OpenAPI do backend (`npm run gerar:api`). */
export function criarCliente(baseUrl: string = URL_API, fetchImpl?: ClientOptions["fetch"]) {
  return createClient<paths>({ baseUrl, fetch: fetchImpl })
}

export const api = criarCliente()

type Schemas = components["schemas"]

export type Etapa = Schemas["Etapa"]
export type Kanban = Schemas["KanbanSchema"]
export type ColunaKanban = Schemas["ColunaKanbanSchema"]
export type CardLead = Schemas["CardLeadSchema"]
export type DetalheLead = Schemas["DetalheLeadSchema"]
export type MensagemLead = Schemas["MensagemSchema"]
export type EventoLead = Schemas["EventoLeadSchema"]
export type ErrosApi = Schemas["ErrosSchema"]

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
