import { describe, expect, it } from "vitest"

import { ehRotaPublica, sanitizarVolta, urlLogin } from "./volta"

describe("sanitizarVolta", () => {
  it("aceita caminhos internos, com query", () => {
    expect(sanitizarVolta("/kanban")).toBe("/kanban")
    expect(sanitizarVolta("/conversas?lead=1")).toBe("/conversas?lead=1")
  })

  it("ignora destinos externos ou ambíguos e cai no kanban", () => {
    for (const ruim of [
      "https://evil.com",
      "http://evil.com/x",
      "//evil.com",
      "/\\evil.com",
      "\\\\evil.com",
      "javascript:alert(1)",
      "kanban",
      "",
      null,
      undefined,
    ]) {
      expect(sanitizarVolta(ruim)).toBe("/kanban")
    }
  })

  it("não volta para o próprio login", () => {
    expect(sanitizarVolta("/login")).toBe("/kanban")
    expect(sanitizarVolta("/login?volta=/x")).toBe("/kanban")
  })
})

describe("urlLogin", () => {
  it("monta /login?volta=<rota> mantendo as barras legíveis", () => {
    expect(urlLogin("/kanban")).toBe("/login?volta=/kanban")
    expect(urlLogin("/conversas?lead=1&x=2")).toBe("/login?volta=/conversas%3Flead%3D1%26x%3D2")
  })

  it("sem rota válida não leva volta", () => {
    expect(urlLogin("/login")).toBe("/login")
    expect(urlLogin("https://evil.com")).toBe("/login")
  })
})

describe("ehRotaPublica", () => {
  it("login e chat público são públicos", () => {
    expect(ehRotaPublica("/login")).toBe(true)
    expect(ehRotaPublica("/chat")).toBe(true)
    expect(ehRotaPublica("/chat/abc")).toBe(true)
  })

  it("o resto do painel não é", () => {
    expect(ehRotaPublica("/kanban")).toBe(false)
    expect(ehRotaPublica("/chatx")).toBe(false)
    expect(ehRotaPublica("/loginx")).toBe(false)
    expect(ehRotaPublica("/conta/senha")).toBe(false)
  })
})
