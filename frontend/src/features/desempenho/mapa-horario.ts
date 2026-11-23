import type { Metricas } from "@/lib/api"

type Celula = Metricas["mapa_horario"][number]

export const DIAS = [
  "Segunda-feira",
  "Terça-feira",
  "Quarta-feira",
  "Quinta-feira",
  "Sexta-feira",
  "Sábado",
  "Domingo",
] as const

export const DIAS_CURTOS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"] as const

export const HORAS = Array.from({ length: 24 }, (_, h) => `${h}h`)

export function nomeDoDia(dia: number): string {
  return DIAS[dia] ?? ""
}

/** A API manda só as células com mensagens; aqui vira a grade 7 (segunda = 0) x 24 com zeros. */
export function montarMapaHorario(celulas: readonly Celula[]): number[][] {
  const mapa = DIAS.map(() => Array.from({ length: 24 }, () => 0))
  for (const { dia_semana, hora, mensagens } of celulas) {
    if (dia_semana < 0 || dia_semana > 6 || hora < 0 || hora > 23) continue
    mapa[dia_semana][hora] += mensagens
  }
  return mapa
}

/** Os `quantos` horários com mais mensagens, do maior para o menor (células zeradas não entram). */
export function horariosDePico(celulas: readonly Celula[], quantos = 3): { dia: number; hora: number; mensagens: number }[] {
  const mapa = montarMapaHorario(celulas)
  return mapa
    .flatMap((horas, dia) => horas.map((mensagens, hora) => ({ dia, hora, mensagens })))
    .filter((c) => c.mensagens > 0)
    .sort((a, b) => b.mensagens - a.mensagens || a.dia - b.dia || a.hora - b.hora)
    .slice(0, quantos)
}
