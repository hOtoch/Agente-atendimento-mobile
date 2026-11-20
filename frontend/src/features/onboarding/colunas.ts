import type { DataGridColumn } from "@/components/ui/data-grid"

/** Rótulos pt-BR dos campos das grades (também usados nas mensagens de erro da importação). */
export const ROTULOS: Record<string, string> = {
  chave: "Parcelas",
  mastercard: "Mastercard",
  visa: "Visa",
  elo: "Elo",
  hipercard: "Hipercard",
  amex: "Amex",
  marca: "Marca",
  modelo: "Modelo",
  capacidade_gb: "Capacidade (GB)",
  valor_sem_detalhes: "Valor sem detalhes (R$)",
  desconto_tela: "Desconto tela",
  desconto_traseira: "Desconto traseira",
  desconto_carcaca: "Desconto carcaça",
  desconto_bateria: "Desconto bateria",
  limite_bateria_pct: "Bateria abaixo de (%)",
  sku: "SKU",
  sku_externo: "SKU externo",
  cor: "Cor",
  condicao: "Condição",
  preco_pix: "Preço Pix (R$)",
  quantidade: "Quantidade",
  bateria_pct: "Bateria (%)",
  nome: "Nome",
  telefone: "Telefone",
  peso_percentual: "Percentual (%)",
  dia: "Dia",
  horario: "Horário",
}

function col(key: string, extra: Partial<DataGridColumn> = {}): DataGridColumn {
  return { key, header: ROTULOS[key], ...extra }
}

const CONDICOES = [
  { value: "novo", label: "Novo" },
  { value: "seminovo", label: "Seminovo" },
]

export const BANDEIRAS = ["mastercard", "visa", "elo", "hipercard", "amex"] as const

export const COLUNAS_VENDEDORES: DataGridColumn[] = [
  col("nome"),
  col("telefone"),
  col("peso_percentual", { type: "number", widthClass: "w-32" }),
]

export const COLUNAS_TAXAS: DataGridColumn[] = [
  col("chave", { widthClass: "w-28" }),
  ...BANDEIRAS.map((b) => col(b, { align: "right", widthClass: "w-28" })),
]

export const COLUNAS_TROCA: DataGridColumn[] = [
  col("marca", { widthClass: "w-28" }),
  col("modelo"),
  col("capacidade_gb", { type: "number", widthClass: "w-24" }),
  col("valor_sem_detalhes", { type: "number", widthClass: "w-32" }),
  col("desconto_tela", { align: "right", widthClass: "w-24" }),
  col("desconto_traseira", { align: "right", widthClass: "w-24" }),
  col("desconto_carcaca", { align: "right", widthClass: "w-24" }),
  col("desconto_bateria", { align: "right", widthClass: "w-24" }),
  col("limite_bateria_pct", { type: "number", widthClass: "w-24" }),
]

export const COLUNAS_ESTOQUE: DataGridColumn[] = [
  col("sku", { widthClass: "w-28" }),
  col("marca", { widthClass: "w-24" }),
  col("modelo"),
  col("capacidade_gb", { type: "number", widthClass: "w-24" }),
  col("cor", { widthClass: "w-28" }),
  col("condicao", { type: "select", options: CONDICOES, widthClass: "w-28" }),
  col("preco_pix", { type: "number", widthClass: "w-28" }),
  col("quantidade", { type: "number", widthClass: "w-24" }),
  col("bateria_pct", { type: "number", widthClass: "w-24" }),
]

export const COLUNAS_MAPEAMENTO: DataGridColumn[] = [
  col("sku_externo"),
  col("marca", { widthClass: "w-24" }),
  col("modelo"),
  col("capacidade_gb", { type: "number", widthClass: "w-24" }),
  col("cor", { widthClass: "w-28" }),
  col("condicao", { type: "select", options: CONDICOES, widthClass: "w-28" }),
]

export const COLUNAS_HORARIOS: DataGridColumn[] = [
  col("dia", { widthClass: "w-40" }),
  col("horario"),
]
