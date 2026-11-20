import type { DataGridRow } from "@/components/ui/data-grid"
import type { criarCliente } from "@/lib/api"

import {
  COLUNAS_ESTOQUE,
  COLUNAS_MAPEAMENTO,
  COLUNAS_TAXAS,
  COLUNAS_TROCA,
  COLUNAS_VENDEDORES,
} from "./colunas"
import {
  estoqueParaLinhas,
  linhasParaEstoque,
  linhasParaMapeamento,
  linhasParaTaxas,
  linhasParaTroca,
  linhasParaVendedores,
  mapeamentoParaLinhas,
  somaPercentuais,
  taxasParaLinhas,
  trocaParaLinhas,
  vendedoresParaLinhas,
} from "./conversores"
import { lerCaminhoApi, type ErroApi } from "./erros"

export type Cliente = ReturnType<typeof criarCliente>
export type TipoImportacao = "troca" | "taxas" | "estoque"

export type CelulaComErro = { linha: number; coluna: string; mensagem: string }
export type ResultadoGrade =
  | { ok: true }
  | { ok: false; celulas: CelulaComErro[]; gerais: string[] }

export type DefinicaoGrade = {
  id: string
  titulo: string
  descricao?: string
  rotuloGrade: string
  colunas: typeof COLUNAS_TROCA
  rotuloAdicionar: string
  /** Planilha que alimenta esta grade (modo validar e depois aplicar). */
  importar?: TipoImportacao
  linhaVazia: () => DataGridRow
  carregar: (cliente: Cliente, lojaId: string) => Promise<DataGridRow[]>
  salvar: (cliente: Cliente, lojaId: string, linhas: DataGridRow[]) => Promise<ResultadoGrade>
  /** Regra checada no cliente antes de chamar a API; devolve a mensagem de erro. */
  validarLocal?: (linhas: DataGridRow[]) => string | null
}

/** Corpo de erro uniforme da API (`{ erros: [{ caminho, mensagem }] }`), quando existir. */
export function errosDoCorpo(corpo: unknown): ErroApi[] | null {
  if (typeof corpo !== "object" || corpo === null || !("erros" in corpo)) return null
  const { erros } = corpo as { erros: unknown }
  if (!Array.isArray(erros)) return null
  const validos = erros.filter(
    (e): e is ErroApi => typeof e?.caminho === "string" && typeof e?.mensagem === "string",
  )
  return validos.length > 0 ? validos : null
}

type Posicao = { linha: number; coluna: string }

/**
 * Distribui os erros da API: os que apontam `<lista>[i].<campo>` vão para a célula da grade
 * (via `mapear`, que por padrão usa índice e campo); os demais viram mensagem geral.
 */
export function distribuirErros(
  erros: ErroApi[],
  lista: string,
  mapear?: (indice: number, campo: string | null) => Posicao | null,
): ResultadoGrade {
  const celulas: CelulaComErro[] = []
  const gerais: string[] = []
  for (const erro of erros) {
    const pos = lerCaminhoApi(erro.caminho)
    if (pos && pos.lista === lista) {
      const destino = mapear
        ? mapear(pos.indice, pos.campo)
        : pos.campo
          ? { linha: pos.indice, coluna: pos.campo }
          : null
      if (destino) {
        celulas.push({ ...destino, mensagem: erro.mensagem })
        continue
      }
      gerais.push(`Linha ${pos.indice + 1}: ${erro.mensagem}`)
      continue
    }
    gerais.push(erro.mensagem)
  }
  return { ok: false, celulas, gerais }
}

type RespostaPut = { error?: unknown; response: { ok: boolean } }

function resultado(
  r: RespostaPut,
  lista: string,
  mapear?: (indice: number, campo: string | null) => Posicao | null,
): ResultadoGrade {
  if (r.response.ok) return { ok: true }
  const erros = errosDoCorpo(r.error)
  if (!erros) return { ok: false, celulas: [], gerais: ["Não foi possível salvar. Tente de novo."] }
  return distribuirErros(erros, lista, mapear)
}

async function carregarOuFalhar<T>(
  chamada: Promise<{ data?: T; response: { ok: boolean } }>,
): Promise<T> {
  const r = await chamada
  if (!r.response.ok || r.data === undefined) throw new Error("Não foi possível carregar os dados.")
  return r.data
}

export const GRADE_VENDEDORES: DefinicaoGrade = {
  id: "vendedores",
  titulo: "Vendedores e distribuição",
  descricao:
    "Quem atende os leads e a porcentagem de leads de cada um. A soma dos percentuais precisa dar 100.",
  rotuloGrade: "Vendedores",
  colunas: COLUNAS_VENDEDORES,
  rotuloAdicionar: "Adicionar vendedor",
  linhaVazia: () => ({ id: null, nome: "", telefone: "", peso_percentual: null }),
  carregar: async (c, lojaId) =>
    vendedoresParaLinhas(
      (
        await carregarOuFalhar(
          c.GET("/lojas/{loja_id}/config/vendedores", { params: { path: { loja_id: lojaId } } }),
        )
      ).vendedores,
    ),
  salvar: async (c, lojaId, linhas) =>
    resultado(
      await c.PUT("/lojas/{loja_id}/config/vendedores", {
        params: { path: { loja_id: lojaId } },
        body: linhasParaVendedores(linhas),
      }),
      "vendedores",
    ),
  validarLocal: (linhas) => {
    const soma = somaPercentuais(linhas)
    return soma === 100
      ? null
      : `Os percentuais dos vendedores precisam somar 100% (hoje somam ${String(soma).replace(".", ",")}%).`
  },
}

export const GRADE_TAXAS: DefinicaoGrade = {
  id: "taxas",
  titulo: "Taxas da maquininha",
  descricao:
    "Percentual cobrado por parcela e bandeira. Escreva “igual” para usar a taxa da Mastercard; deixe em branco o que não se aplica.",
  rotuloGrade: "Taxas",
  colunas: COLUNAS_TAXAS,
  rotuloAdicionar: "Adicionar parcela",
  importar: "taxas",
  linhaVazia: () => ({ chave: "", mastercard: "", visa: "", elo: "", hipercard: "", amex: "" }),
  carregar: async (c, lojaId) =>
    taxasParaLinhas(
      (
        await carregarOuFalhar(
          c.GET("/lojas/{loja_id}/config/taxas", { params: { path: { loja_id: lojaId } } }),
        )
      ).taxas,
    ),
  salvar: async (c, lojaId, linhas) => {
    const { taxas, origens } = linhasParaTaxas(linhas)
    return resultado(
      await c.PUT("/lojas/{loja_id}/config/taxas", {
        params: { path: { loja_id: lojaId } },
        body: taxas,
      }),
      "taxas",
      (indice, campo) => {
        const origem = origens[indice]
        if (!origem) return null
        return { linha: origem.linha, coluna: campo === "chave" ? "chave" : origem.coluna }
      },
    )
  },
}

export const GRADE_TROCA: DefinicaoGrade = {
  id: "troca",
  titulo: "Tabela de troca",
  descricao:
    "Valor do aparelho usado perfeito e quanto descontar de cada problema. Em cada desconto use um valor, 0 ou SEM (avaliação na loja).",
  rotuloGrade: "Tabela de troca",
  colunas: COLUNAS_TROCA,
  rotuloAdicionar: "Adicionar modelo",
  importar: "troca",
  linhaVazia: () => ({
    marca: "Apple",
    modelo: "",
    capacidade_gb: null,
    valor_sem_detalhes: null,
    desconto_tela: "",
    desconto_traseira: "",
    desconto_carcaca: "",
    desconto_bateria: "",
    limite_bateria_pct: 80,
  }),
  carregar: async (c, lojaId) =>
    trocaParaLinhas(
      (
        await carregarOuFalhar(
          c.GET("/lojas/{loja_id}/config/troca", { params: { path: { loja_id: lojaId } } }),
        )
      ).tabela_troca,
    ),
  salvar: async (c, lojaId, linhas) =>
    resultado(
      await c.PUT("/lojas/{loja_id}/config/troca", {
        params: { path: { loja_id: lojaId } },
        body: linhasParaTroca(linhas),
      }),
      "tabela_troca",
    ),
}

export const GRADE_ESTOQUE: DefinicaoGrade = {
  id: "estoque",
  titulo: "Estoque local",
  descricao:
    "Itens à venda. Se a loja tiver ERP, o estoque virá de lá e esta grade serve de apoio.",
  rotuloGrade: "Estoque",
  colunas: COLUNAS_ESTOQUE,
  rotuloAdicionar: "Adicionar item",
  importar: "estoque",
  linhaVazia: () => ({
    sku: "",
    marca: "Apple",
    modelo: "",
    capacidade_gb: null,
    cor: "",
    condicao: "novo",
    preco_pix: null,
    quantidade: 1,
    bateria_pct: null,
  }),
  carregar: async (c, lojaId) =>
    estoqueParaLinhas(
      (
        await carregarOuFalhar(
          c.GET("/lojas/{loja_id}/config/estoque", { params: { path: { loja_id: lojaId } } }),
        )
      ).estoque,
    ),
  salvar: async (c, lojaId, linhas) =>
    resultado(
      await c.PUT("/lojas/{loja_id}/config/estoque", {
        params: { path: { loja_id: lojaId } },
        body: linhasParaEstoque(linhas),
      }),
      "estoque",
    ),
}

export const GRADE_MAPEAMENTO: DefinicaoGrade = {
  id: "mapeamento-sku",
  titulo: "Mapeamento de SKU",
  descricao: "Relaciona o código do SKU do ERP com o modelo, a capacidade, a cor e a condição.",
  rotuloGrade: "Mapeamento de SKU",
  colunas: COLUNAS_MAPEAMENTO,
  rotuloAdicionar: "Adicionar SKU",
  linhaVazia: () => ({
    sku_externo: "",
    marca: "Apple",
    modelo: "",
    capacidade_gb: null,
    cor: "",
    condicao: "novo",
  }),
  carregar: async (c, lojaId) =>
    mapeamentoParaLinhas(
      (
        await carregarOuFalhar(
          c.GET("/lojas/{loja_id}/config/mapeamento-sku", {
            params: { path: { loja_id: lojaId } },
          }),
        )
      ).mapeamento_sku,
    ),
  salvar: async (c, lojaId, linhas) =>
    resultado(
      await c.PUT("/lojas/{loja_id}/config/mapeamento-sku", {
        params: { path: { loja_id: lojaId } },
        body: linhasParaMapeamento(linhas),
      }),
      "mapeamento_sku",
    ),
}
