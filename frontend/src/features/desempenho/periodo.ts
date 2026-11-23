/** Períodos oferecidos no painel e o cálculo do intervalo (dias de São Paulo, como a API). */

export const PERIODOS = [
  { dias: 7, rotulo: "7 dias" },
  { dias: 30, rotulo: "30 dias" },
  { dias: 90, rotulo: "90 dias" },
] as const

export const PERIODO_PADRAO = 30

const FUSO_DA_LOJA = "America/Sao_Paulo"

/** Dia de hoje (AAAA-MM-DD) no fuso da loja. */
function hojeNaLoja(agora: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: FUSO_DA_LOJA }).format(agora)
}

/** Últimos `dias` dias, terminando hoje (inclusive): `de` = hoje - (dias - 1). */
export function intervaloDoPeriodo(dias: number, agora: Date = new Date()): { de: string; ate: string } {
  const ate = hojeNaLoja(agora)
  const inicio = new Date(`${ate}T00:00:00Z`)
  inicio.setUTCDate(inicio.getUTCDate() - (dias - 1))
  return { de: inicio.toISOString().slice(0, 10), ate }
}
