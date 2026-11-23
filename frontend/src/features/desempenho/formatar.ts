/** Formatação pt-BR dos números do painel de desempenho (funções puras). */

export const TRACO = "—"

const LOCALE = "pt-BR"

const inteiro = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 })
const compacto = new Intl.NumberFormat(LOCALE, { notation: "compact", compactDisplay: "short", maximumFractionDigits: 1 })

export function formatarInteiro(valor: number | null): string {
  return valor === null ? TRACO : inteiro.format(valor)
}

export function formatarDecimal(valor: number | null, casas = 1): string {
  if (valor === null) return TRACO
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: casas }).format(valor)
}

/** `fracao` em 0..1 (0,2 = 20%). */
export function formatarPercentual(fracao: number | null, casas = 1): string {
  if (fracao === null) return TRACO
  return new Intl.NumberFormat(LOCALE, { style: "percent", maximumFractionDigits: casas }).format(fracao)
}

/** Dólar a partir da string decimal da API; abaixo de US$ 1 mostra 4 casas (custo por conversa é centavos). */
export function formatarUsd(valor: string | number | null): string {
  if (valor === null) return TRACO
  const numero = Number(valor)
  const casas = Math.abs(numero) < 1 && numero !== 0 ? 4 : 2
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency: "USD",
    currencyDisplay: "symbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: casas,
  }).format(numero)
}

/** ms → "850 ms", "2,4 s" ou "1 min 5 s". */
export function formatarDuracao(ms: number | null): string {
  if (ms === null) return TRACO
  if (ms < 1000) return `${Math.round(ms)} ms`
  const segundos = ms / 1000
  if (segundos < 60) return `${formatarDecimal(segundos, 1)} s`
  const minutos = Math.floor(segundos / 60)
  return `${minutos} min ${Math.round(segundos - minutos * 60)} s`
}

/** "+12,5%", "-3%", "0%"; `null` quando não há comparação. */
export function formatarVariacao(pct: number | null): string | null {
  if (pct === null) return null
  const numero = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 }).format(Math.abs(pct))
  if (pct > 0) return `+${numero}%`
  if (pct < 0) return `-${numero}%`
  return "0%"
}

/** Números dos eixos: 950, "1,2 mil", "2,5 mi". */
export function formatarCompacto(valor: number): string {
  return compacto.format(valor).replace(/ /g, " ")
}

/** "2026-11-05" → "05/11". */
export function formatarDataCurta(dia: string): string {
  const [, mes, d] = dia.split("-")
  return `${d}/${mes}`
}

function formatarDataCompleta(dia: string): string {
  const [ano, mes, d] = dia.split("-")
  return `${d}/${mes}/${ano}`
}

export function formatarIntervalo(de: string, ate: string): string {
  return `${formatarDataCompleta(de)} a ${formatarDataCompleta(ate)}`
}
