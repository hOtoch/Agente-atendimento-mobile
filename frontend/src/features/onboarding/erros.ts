import { ROTULOS } from "./colunas"

/** Erro no formato uniforme da API: `{ caminho, mensagem }`. */
export type ErroApi = { caminho: string; mensagem: string }

export type PosicaoNaLista = { lista: string; indice: number; campo: string | null }

const CAMINHO_API = /^(\w+)\[(\d+)\](?:\.(\w+))?$/

/** `tabela_troca[3].desconto_tela` -> linha 3 (0-based) e coluna `desconto_tela` da grade. */
export function lerCaminhoApi(caminho: string): PosicaoNaLista | null {
  const m = CAMINHO_API.exec(caminho)
  if (!m) return null
  return { lista: m[1], indice: Number(m[2]), campo: m[3] ?? null }
}

const CAMPOS_TROCA = [
  "modelo",
  "capacidade_gb",
  "valor_sem_detalhes",
  "desconto_tela",
  "desconto_traseira",
  "desconto_carcaca",
  "desconto_bateria",
  "limite_bateria_pct",
]

/** Layout das abas dos modelos de planilha (a ordem das colunas é a do modelo xlsx do backend). */
const ABAS: Record<string, { rotulo: string; colunas: (string | null)[] }> = {
  troca: { rotulo: "Tabela de troca", colunas: CAMPOS_TROCA },
  outras_marcas: { rotulo: "Outras marcas", colunas: ["marca", ...CAMPOS_TROCA] },
  estoque: {
    rotulo: "Estoque",
    colunas: ["sku", "modelo", "capacidade_gb", "cor", "condicao", "preco_pix", "quantidade", "bateria_pct"],
  },
  taxas: {
    rotulo: "Taxas",
    colunas: ["chave", "mastercard", "visa", "elo", "hipercard", "amex"],
  },
  regras: { rotulo: "Regras de preço", colunas: [null, null] },
}

export type CelulaPlanilha = {
  aba: string
  abaRotulo: string
  /** Referência como no Excel, ex.: `D7`. */
  celula: string
  letra: string
  /** Linha da planilha (1-based; a linha 1 é o cabeçalho). */
  linha: number
  /** Índice da linha de dados (0-based): linha 2 da planilha = 0. */
  indice: number
  colunaKey: string | null
  colunaRotulo: string | null
}

const CELULA = /^(\w+)!([A-Z]+)(\d+)$/

function indiceDaLetra(letra: string): number {
  let n = 0
  for (const c of letra) n = n * 26 + (c.charCodeAt(0) - 64)
  return n - 1
}

/** `troca!D7` -> aba, linha 7 (índice 5) e a coluna da grade que a letra D representa. */
export function lerCelulaPlanilha(caminho: string): CelulaPlanilha | null {
  const m = CELULA.exec(caminho)
  if (!m) return null
  const [, aba, letra, linhaTexto] = m
  const layout = ABAS[aba]
  if (!layout) return null
  const linha = Number(linhaTexto)
  const colunaKey = layout.colunas[indiceDaLetra(letra)] ?? null
  return {
    aba,
    abaRotulo: layout.rotulo,
    celula: `${letra}${linhaTexto}`,
    letra,
    linha,
    indice: linha - 2,
    colunaKey,
    colunaRotulo: colunaKey ? (ROTULOS[colunaKey] ?? null) : null,
  }
}

export function descreverErroImportacao(erro: ErroApi): string {
  const c = lerCelulaPlanilha(erro.caminho)
  if (!c) return erro.mensagem
  const coluna = c.colunaRotulo ? ` · ${c.colunaRotulo}` : ""
  return `Aba ${c.abaRotulo} · linha ${c.linha}${coluna} (${c.celula}): ${erro.mensagem}`
}
