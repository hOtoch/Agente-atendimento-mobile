import { describe, expect, it } from "vitest"

import { horariosDePico, montarMapaHorario, nomeDoDia } from "./mapa-horario"

describe("mapa de horários", () => {
  it("preenche 7 dias x 24 horas com zeros onde a API não manda nada", () => {
    const mapa = montarMapaHorario([{ dia_semana: 0, hora: 14, mensagens: 32 }])
    expect(mapa).toHaveLength(7)
    expect(mapa.every((linha) => linha.length === 24)).toBe(true)
    expect(mapa[0][14]).toBe(32)
    expect(mapa.flat().filter((v) => v === 0)).toHaveLength(7 * 24 - 1)
  })

  it("ignora células fora do intervalo e soma repetições", () => {
    const mapa = montarMapaHorario([
      { dia_semana: 2, hora: 9, mensagens: 3 },
      { dia_semana: 2, hora: 9, mensagens: 4 },
      { dia_semana: 9, hora: 1, mensagens: 99 },
      { dia_semana: 1, hora: 30, mensagens: 99 },
    ])
    expect(mapa[2][9]).toBe(7)
    expect(mapa.flat().reduce((a, b) => a + b, 0)).toBe(7)
  })

  it("sem dados, o mapa é todo zero", () => {
    expect(montarMapaHorario([]).flat().every((v) => v === 0)).toBe(true)
  })

  it("lista os horários de pico do maior para o menor, só com mensagens", () => {
    const pico = horariosDePico(
      [
        { dia_semana: 4, hora: 18, mensagens: 10 },
        { dia_semana: 0, hora: 14, mensagens: 32 },
        { dia_semana: 5, hora: 11, mensagens: 0 },
        { dia_semana: 2, hora: 9, mensagens: 21 },
      ],
      2,
    )
    expect(pico).toEqual([
      { dia: 0, hora: 14, mensagens: 32 },
      { dia: 2, hora: 9, mensagens: 21 },
    ])
  })

  it("nomeia os dias a partir da segunda-feira", () => {
    expect(nomeDoDia(0)).toBe("Segunda-feira")
    expect(nomeDoDia(6)).toBe("Domingo")
  })
})
