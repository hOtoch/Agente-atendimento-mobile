import { describe, expect, it } from "vitest"

import { contatoDoLead } from "./lead"

const base = { nome: null, telefone: "5511988887777", canal: "whatsapp" as const }

describe("contatoDoLead", () => {
  it("whatsapp: mostra o telefone e 'Sem nome' quando não há nome", () => {
    expect(contatoDoLead(base)).toEqual({ titulo: "Sem nome", detalhe: "5511988887777" })
    expect(contatoDoLead({ ...base, nome: "Maria" })).toEqual({ titulo: "Maria", detalhe: "5511988887777" })
  })

  it("webchat: o telefone é o id da sessão, então mostra 'Chat web'", () => {
    const sessao = "a".repeat(32)
    expect(contatoDoLead({ nome: null, telefone: sessao, canal: "webchat" })).toEqual({
      titulo: "Visitante do chat web",
      detalhe: "Chat web",
    })
    expect(contatoDoLead({ nome: "João", telefone: sessao, canal: "webchat" })).toEqual({
      titulo: "João",
      detalhe: "Chat web",
    })
  })

  it("instagram segue a regra do whatsapp", () => {
    expect(contatoDoLead({ ...base, canal: "instagram" }).detalhe).toBe("5511988887777")
  })
})
