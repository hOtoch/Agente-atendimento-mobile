export type IdPasso = "perfil" | "vendedores" | "preco" | "taxas" | "troca" | "estoque" | "whatsapp" | "teste"

export type Passo = {
  id: IdPasso
  titulo: string
  descricao: string
  /** Itens do checklist da API que este passo cobre (vazio = passo sem checklist). */
  chaves: string[]
}

export const PASSOS: Passo[] = [
  {
    id: "perfil",
    titulo: "Dados da loja e tom",
    descricao: "Nome, endereço, horários e o jeito de falar do atendimento.",
    chaves: ["perfil"],
  },
  {
    id: "vendedores",
    titulo: "Vendedores e distribuição",
    descricao: "Quem recebe os leads e em que proporção.",
    chaves: ["vendedores"],
  },
  {
    id: "preco",
    titulo: "Regras de preço",
    descricao: "Parcelamento, desconto Pix e limites de desconto.",
    chaves: ["regras_preco"],
  },
  {
    id: "taxas",
    titulo: "Taxas da maquininha",
    descricao: "Taxa por parcela e bandeira.",
    chaves: ["taxas"],
  },
  {
    id: "troca",
    titulo: "Tabela de troca",
    descricao: "Quanto a loja paga por cada aparelho usado.",
    chaves: ["tabela_troca"],
  },
  {
    id: "estoque",
    titulo: "Estoque e SKU",
    descricao: "Itens à venda e o mapeamento dos códigos do ERP.",
    chaves: ["estoque", "mapeamento_sku"],
  },
  {
    id: "whatsapp",
    titulo: "Conectar WhatsApp",
    descricao: "Liga o número da loja ao atendimento.",
    chaves: [],
  },
  {
    id: "teste",
    titulo: "Conversa de teste",
    descricao: "Converse como se fosse um cliente antes de abrir para o público.",
    chaves: [],
  },
]

export type ItemChecklist = {
  chave: string
  rotulo_ptbr: string
  completo: boolean
  detalhe: string
}

export function passoCompleto(passo: Passo, itens: ItemChecklist[]): boolean | null {
  if (passo.chaves.length === 0) return null
  const doPasso = itens.filter((i) => passo.chaves.includes(i.chave))
  return doPasso.length > 0 && doPasso.every((i) => i.completo)
}

export function passoPorId(id: string | null | undefined): Passo | undefined {
  return PASSOS.find((p) => p.id === id)
}

/** Passo aberto sem `?passo=`: o primeiro pendente; tudo pronto, o último com checklist. */
export function primeiroPendente(itens: ItemChecklist[]): Passo {
  return PASSOS.find((p) => passoCompleto(p, itens) === false) ?? PASSOS[0]
}
