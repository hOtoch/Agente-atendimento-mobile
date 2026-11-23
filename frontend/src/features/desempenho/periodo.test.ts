import { describe, expect, it } from "vitest"

import { PERIODOS, intervaloDoPeriodo } from "./periodo"

describe("intervaloDoPeriodo", () => {
  it("oferece 7, 30 e 90 dias", () => {
    expect(PERIODOS.map((p) => p.dias)).toEqual([7, 30, 90])
  })

  it("termina hoje (inclusive) e começa dias-1 antes", () => {
    const agora = new Date("2026-11-22T15:00:00Z")
    expect(intervaloDoPeriodo(7, agora)).toEqual({ de: "2026-11-16", ate: "2026-11-22" })
    expect(intervaloDoPeriodo(30, agora)).toEqual({ de: "2026-10-24", ate: "2026-11-22" })
    expect(intervaloDoPeriodo(90, agora)).toEqual({ de: "2026-08-25", ate: "2026-11-22" })
  })

  it("usa o dia de São Paulo, não o de UTC", () => {
    // 01:00 UTC de 22/11 ainda é 22:00 de 21/11 em São Paulo
    const agora = new Date("2026-11-22T01:00:00Z")
    expect(intervaloDoPeriodo(7, agora)).toEqual({ de: "2026-11-15", ate: "2026-11-21" })
  })
})
