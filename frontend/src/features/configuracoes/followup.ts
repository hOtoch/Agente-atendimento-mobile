import type { components } from "@/lib/api/schema"

export type CorpoFollowup = components["schemas"]["FollowupSchema-Input"]

/** Etapas em que a IA faz follow-up (as demais são do vendedor). Ordem = ordem do funil. */
export const ETAPAS_FOLLOWUP = [
  { chave: "novo_contato", rotulo: "Novo contato" },
  { chave: "interesse_identificado", rotulo: "Interesse identificado" },
  { chave: "interesse_qualificado", rotulo: "Interesse qualificado" },
] as const

export type ChaveEtapa = (typeof ETAPAS_FOLLOWUP)[number]["chave"]

export const MAX_TENTATIVAS = 5

export type FormFollowup = {
  ligado: "sim" | "nao"
  horas: Record<ChaveEtapa, string>
  max_tentativas: string
  intervalo_horas: string
  hora_inicio: string
  hora_fim: string
  max_dias_parado: string
}

export type ErrosFollowup = Partial<
  Record<
    "horas_por_etapa" | "max_tentativas" | "intervalo_horas" | "hora_inicio" | "hora_fim" | "max_dias_parado",
    string
  >
>

const hhmm = (hora: string) => hora.slice(0, 5)

export function corpoParaForm(c: CorpoFollowup): FormFollowup {
  const horas = (chave: ChaveEtapa) => {
    const h = c.horas_por_etapa?.[chave]
    return h === undefined ? "" : String(h)
  }
  return {
    ligado: c.ligado ? "sim" : "nao",
    horas: {
      novo_contato: horas("novo_contato"),
      interesse_identificado: horas("interesse_identificado"),
      interesse_qualificado: horas("interesse_qualificado"),
    },
    max_tentativas: String(c.max_tentativas),
    intervalo_horas: String(c.intervalo_horas),
    hora_inicio: hhmm(c.hora_inicio),
    hora_fim: hhmm(c.hora_fim),
    max_dias_parado: String(c.max_dias_parado),
  }
}

/** Inteiro positivo ou `null` (vazio, fracionado, negativo, zero ou lixo). */
function inteiro(texto: string): number | null {
  if (!/^\d+$/.test(texto.trim())) return null
  const n = Number(texto)
  return n >= 1 ? n : null
}

export function formParaCorpo(f: FormFollowup): CorpoFollowup {
  const horas: Record<string, number> = {}
  for (const { chave } of ETAPAS_FOLLOWUP) {
    const h = inteiro(f.horas[chave])
    if (h !== null) horas[chave] = h
  }
  return {
    ligado: f.ligado === "sim",
    horas_por_etapa: horas,
    max_tentativas: Number(f.max_tentativas),
    intervalo_horas: Number(f.intervalo_horas),
    hora_inicio: f.hora_inicio,
    hora_fim: f.hora_fim,
    max_dias_parado: Number(f.max_dias_parado),
  }
}

export function validarForm(f: FormFollowup): ErrosFollowup {
  const erros: ErrosFollowup = {}
  const tentativas = inteiro(f.max_tentativas)
  if (tentativas === null || tentativas > MAX_TENTATIVAS) {
    erros.max_tentativas = `Informe um número entre 1 e ${MAX_TENTATIVAS}.`
  }
  if (inteiro(f.intervalo_horas) === null) erros.intervalo_horas = "Informe as horas (número inteiro, 1 ou mais)."
  if (inteiro(f.max_dias_parado) === null) erros.max_dias_parado = "Informe os dias (número inteiro, 1 ou mais)."
  if (!f.hora_inicio) erros.hora_inicio = "Informe o horário de início."
  if (!f.hora_fim) erros.hora_fim = "Informe o horário de fim."
  if (f.hora_inicio && f.hora_fim && f.hora_inicio >= f.hora_fim) {
    erros.hora_inicio = "O início precisa ser antes do fim."
  }
  const preenchidas = ETAPAS_FOLLOWUP.map(({ chave }) => f.horas[chave])
  if (preenchidas.some((h) => h.trim() !== "" && inteiro(h) === null)) {
    erros.horas_por_etapa = "As horas devem ser um número inteiro de 1 ou mais (ou vazio para não fazer follow-up)."
  } else if (f.ligado === "sim" && preenchidas.every((h) => h.trim() === "")) {
    erros.horas_por_etapa = "Informe as horas de ao menos uma etapa."
  }
  return erros
}
