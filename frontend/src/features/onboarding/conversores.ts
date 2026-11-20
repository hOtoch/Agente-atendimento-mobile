/**
 * Conversão entre o formato da API e as linhas das grades (`DataGridRow`).
 * Decimais da API chegam como string (`"3100.00"`); na grade viram número ou texto pt-BR.
 */
import type { DataGridRow } from "@/components/ui/data-grid"

import { BANDEIRAS } from "./colunas"

type Enviavel = number | string | null

/** Interpreta "2.500,50", "R$ 600", "600,5" ou "600.5". `null` se vazio ou não numérico. */
export function parseNumero(texto: string): number | null {
  let limpo = texto.trim().replace(/^R\$\s*/i, "").replace(/\s/g, "")
  if (limpo === "") return null
  if (limpo.includes(",")) limpo = limpo.replace(/\./g, "").replace(",", ".")
  const n = Number(limpo)
  return Number.isNaN(n) ? null : n
}

/** Número quando dá; senão o texto cru, para a API apontar o erro na célula certa. */
function paraEnvio(texto: string): number | string {
  return parseNumero(texto) ?? texto.trim()
}

function decimalDaApi(valor: string | null | undefined): number | null {
  return valor === null || valor === undefined ? null : Number(valor)
}

function textoPtBr(valor: string): string {
  return String(Number(valor)).replace(".", ",")
}

function texto(valor: unknown): string {
  return valor === null || valor === undefined ? "" : String(valor)
}

function numeroOuNulo(valor: unknown): Enviavel {
  if (valor === null || valor === undefined || valor === "") return null
  return typeof valor === "number" ? valor : paraEnvio(String(valor))
}

// --- vendedores -------------------------------------------------------------------------------

export type VendedorApi = {
  id: string
  nome: string
  telefone: string | null
  peso_percentual: string
  ativo: boolean
}

/** Só os ativos aparecem na grade; remover uma linha desativa o vendedor no servidor. */
export function vendedoresParaLinhas(lista: VendedorApi[]): DataGridRow[] {
  return lista
    .filter((v) => v.ativo)
    .map((v) => ({
      id: v.id,
      nome: v.nome,
      telefone: v.telefone ?? "",
      peso_percentual: Number(v.peso_percentual),
    }))
}

export function linhasParaVendedores(linhas: DataGridRow[]) {
  return {
    vendedores: linhas.map((l) => ({
      id: typeof l.id === "string" ? l.id : null,
      nome: texto(l.nome).trim(),
      telefone: texto(l.telefone).trim() || null,
      peso_percentual: numeroOuNulo(l.peso_percentual) ?? 0,
      ativo: true,
    })),
  }
}

/** Soma em centésimos para não acumular erro de ponto flutuante (0,1 + 0,2). */
export function somaPercentuais(linhas: { peso_percentual?: unknown }[]): number {
  const centesimos = linhas.reduce((total, l) => {
    const v = typeof l.peso_percentual === "number" ? l.peso_percentual : 0
    return total + Math.round(v * 100)
  }, 0)
  return centesimos / 100
}

// --- taxas ------------------------------------------------------------------------------------

export type TaxaApi = { chave: number | string; bandeira: string; taxa_pct?: string | null }

const PARCELAS_MAX = 21
const DEBITO = "debito"

function linhaDeTaxa(chave: string): DataGridRow {
  const linha: DataGridRow = { chave }
  for (const b of BANDEIRAS) linha[b] = ""
  return linha
}

function ordemDaChave(chave: string): number {
  return chave === DEBITO ? 1000 : Number(chave)
}

export function taxasParaLinhas(lista: TaxaApi[]): DataGridRow[] {
  if (lista.length === 0) {
    return [
      ...Array.from({ length: PARCELAS_MAX }, (_, i) => linhaDeTaxa(String(i + 1))),
      linhaDeTaxa(DEBITO),
    ]
  }
  const porChave = new Map<string, DataGridRow>()
  for (const t of lista) {
    const chave = String(t.chave)
    const linha = porChave.get(chave) ?? linhaDeTaxa(chave)
    linha[t.bandeira] =
      t.taxa_pct === null || t.taxa_pct === undefined ? "igual" : textoPtBr(t.taxa_pct)
    porChave.set(chave, linha)
  }
  return [...porChave.values()].sort((a, b) => ordemDaChave(texto(a.chave)) - ordemDaChave(texto(b.chave)))
}

export type OrigemTaxa = { linha: number; coluna: string }

/** Uma entrada por célula preenchida; `origens[i]` diz de qual célula veio `taxas[i]`. */
export function linhasParaTaxas(linhas: DataGridRow[]) {
  const taxas: { chave: number | string; bandeira: string; taxa_pct: Enviavel }[] = []
  const origens: OrigemTaxa[] = []
  linhas.forEach((l, linha) => {
    const bruta = texto(l.chave).trim().toLowerCase()
    const chave: number | string = /^\d+$/.test(bruta) ? Number(bruta) : bruta
    for (const bandeira of BANDEIRAS) {
      const celula = texto(l[bandeira]).trim()
      if (celula === "") continue
      const taxa_pct = celula.toLowerCase() === "igual" ? null : paraEnvio(celula)
      taxas.push({ chave, bandeira, taxa_pct })
      origens.push({ linha, coluna: bandeira })
    }
  })
  return { taxas: { taxas }, origens }
}

// --- tabela de troca --------------------------------------------------------------------------

export type LinhaTrocaApi = {
  marca: string
  modelo: string
  capacidade_gb: number
  valor_sem_detalhes: string
  desconto_tela?: string | null
  desconto_tela_sem: boolean
  desconto_traseira?: string | null
  desconto_traseira_sem: boolean
  desconto_carcaca?: string | null
  desconto_carcaca_sem: boolean
  desconto_bateria?: string | null
  desconto_bateria_sem: boolean
  limite_bateria_pct: number
}

const DESCONTOS = ["tela", "traseira", "carcaca", "bateria"] as const

function descontoParaTexto(valor: string | null | undefined, sem: boolean): string {
  if (sem) return "SEM"
  return valor === null || valor === undefined ? "" : String(Number(valor)).replace(".", ",")
}

export function trocaParaLinhas(lista: LinhaTrocaApi[]): DataGridRow[] {
  return lista.map((x) => {
    const linha: DataGridRow = {
      marca: x.marca,
      modelo: x.modelo,
      capacidade_gb: x.capacidade_gb,
      valor_sem_detalhes: decimalDaApi(x.valor_sem_detalhes),
      limite_bateria_pct: x.limite_bateria_pct,
    }
    for (const d of DESCONTOS) {
      linha[`desconto_${d}`] = descontoParaTexto(x[`desconto_${d}`], x[`desconto_${d}_sem`])
    }
    return linha
  })
}

export function linhasParaTroca(linhas: DataGridRow[]) {
  return {
    tabela_troca: linhas.map((l) => {
      const corpo: Record<string, unknown> = {
        marca: texto(l.marca).trim(),
        modelo: texto(l.modelo).trim(),
        capacidade_gb: numeroOuNulo(l.capacidade_gb),
        valor_sem_detalhes: numeroOuNulo(l.valor_sem_detalhes),
        limite_bateria_pct: numeroOuNulo(l.limite_bateria_pct),
      }
      for (const d of DESCONTOS) {
        const celula = texto(l[`desconto_${d}`]).trim()
        const sem = celula.toUpperCase() === "SEM"
        corpo[`desconto_${d}`] = sem || celula === "" ? null : paraEnvio(celula)
        corpo[`desconto_${d}_sem`] = sem
      }
      return corpo as TrocaEnvio
    }),
  }
}

export type TrocaEnvio = {
  marca: string
  modelo: string
  capacidade_gb: number
  valor_sem_detalhes: number | string
  desconto_tela: Enviavel
  desconto_tela_sem: boolean
  desconto_traseira: Enviavel
  desconto_traseira_sem: boolean
  desconto_carcaca: Enviavel
  desconto_carcaca_sem: boolean
  desconto_bateria: Enviavel
  desconto_bateria_sem: boolean
  limite_bateria_pct: number
}

// --- estoque e mapeamento de SKU --------------------------------------------------------------

export type LinhaEstoqueApi = {
  sku: string
  marca: string
  modelo: string
  capacidade_gb: number
  cor: string
  condicao: string
  preco_pix: string
  quantidade: number
  bateria_pct?: number | null
}

export function estoqueParaLinhas(lista: LinhaEstoqueApi[]): DataGridRow[] {
  return lista.map((x) => ({
    sku: x.sku,
    marca: x.marca,
    modelo: x.modelo,
    capacidade_gb: x.capacidade_gb,
    cor: x.cor,
    condicao: x.condicao,
    preco_pix: decimalDaApi(x.preco_pix),
    quantidade: x.quantidade,
    bateria_pct: x.bateria_pct ?? null,
  }))
}

export function linhasParaEstoque(linhas: DataGridRow[]) {
  return {
    estoque: linhas.map((l) => ({
      sku: texto(l.sku).trim(),
      marca: texto(l.marca).trim(),
      modelo: texto(l.modelo).trim(),
      capacidade_gb: numeroOuNulo(l.capacidade_gb) as number,
      cor: texto(l.cor).trim(),
      condicao: texto(l.condicao),
      preco_pix: numeroOuNulo(l.preco_pix) as number | string,
      quantidade: numeroOuNulo(l.quantidade) as number,
      bateria_pct: numeroOuNulo(l.bateria_pct) as number | null,
    })),
  }
}

export type LinhaMapeamentoApi = {
  sku_externo: string
  marca: string
  modelo: string
  capacidade_gb: number
  cor: string
  condicao: string
}

export function mapeamentoParaLinhas(lista: LinhaMapeamentoApi[]): DataGridRow[] {
  return lista.map((x) => ({
    sku_externo: x.sku_externo,
    marca: x.marca,
    modelo: x.modelo,
    capacidade_gb: x.capacidade_gb,
    cor: x.cor,
    condicao: x.condicao,
  }))
}

export function linhasParaMapeamento(linhas: DataGridRow[]) {
  return {
    mapeamento_sku: linhas.map((l) => ({
      sku_externo: texto(l.sku_externo).trim(),
      marca: texto(l.marca).trim(),
      modelo: texto(l.modelo).trim(),
      capacidade_gb: numeroOuNulo(l.capacidade_gb) as number,
      cor: texto(l.cor).trim(),
      condicao: texto(l.condicao),
    })),
  }
}
