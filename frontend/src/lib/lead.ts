import type { CardLead } from "@/lib/api"

export type ContatoDoLead = { titulo: string; detalhe: string }

/**
 * Como exibir quem é o lead. No canal `webchat` o campo `telefone` guarda o id da sessão (não é
 * um telefone), então ele nunca é mostrado.
 */
export function contatoDoLead(lead: Pick<CardLead, "nome" | "telefone" | "canal">): ContatoDoLead {
  if (lead.canal === "webchat") {
    return { titulo: lead.nome ?? "Visitante do chat web", detalhe: "Chat web" }
  }
  return { titulo: lead.nome ?? "Sem nome", detalhe: lead.telefone }
}
