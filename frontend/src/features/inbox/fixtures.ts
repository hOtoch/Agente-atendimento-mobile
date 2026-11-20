import type { CardLead, DetalheLead, MensagemLead } from "@/lib/api"

/** Dados de teste da inbox (compartilhados pelos testes da feature). */
export const LOJA = "00000000-0000-4000-8000-00000000de30"
export const LEAD_MARIA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
export const LEAD_JOAO = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
export const LEAD_SUMIDO = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
export const VENDEDOR_ANA = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
export const VENDEDOR_BRUNO = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

export function card(parcial: Partial<CardLead> & Pick<CardLead, "id">): CardLead {
  return {
    nome: null,
    telefone: "5511999990000",
    canal: "webchat",
    etapa: "novo_contato",
    etapa_desde: "2026-11-20T10:00:00Z",
    criado_em: "2026-11-20T10:00:00Z",
    dono: "ia",
    vendedor_id: null,
    vendedor_nome: null,
    aparelho_desejado: null,
    valor_estimado: null,
    ...parcial,
  }
}

export const CARD_MARIA = card({
  id: LEAD_MARIA,
  nome: "Maria Souza",
  telefone: "5511988887777",
  etapa: "interesse_qualificado",
  etapa_desde: "2026-11-20T12:00:00Z",
  aparelho_desejado: "iPhone 13 128 GB",
})

export const CARD_JOAO = card({
  id: LEAD_JOAO,
  nome: "João Lima",
  telefone: "5511977776666",
  etapa: "novo_contato",
  etapa_desde: "2026-11-20T09:00:00Z",
  criado_em: "2026-11-20T09:00:00Z",
})

export const VENDEDORES = [
  { id: VENDEDOR_ANA, nome: "Ana Paula", telefone: null, peso_percentual: "50", ativo: true },
  { id: VENDEDOR_BRUNO, nome: "Bruno Reis", telefone: null, peso_percentual: "50", ativo: true },
  { id: "ffffffff-ffff-4fff-8fff-ffffffffffff", nome: "Carlos Inativo", telefone: null, peso_percentual: "0", ativo: false },
]

export function mensagem(parcial: Partial<MensagemLead> & Pick<MensagemLead, "id" | "autor">): MensagemLead {
  return {
    conversa_id: "11111111-1111-4111-8111-111111111111",
    direcao: parcial.autor === "cliente" ? "entrada" : "saida",
    tipo: "texto",
    texto: null,
    midia_url: null,
    criada_em: "2026-11-20T12:00:00Z",
    ...parcial,
  }
}

export const MENSAGENS_MARIA: MensagemLead[] = [
  mensagem({ id: "m1", autor: "cliente", texto: "Oi, quero um iPhone 13", criada_em: "2026-11-20T12:00:00Z" }),
  mensagem({ id: "m2", autor: "ia", texto: "Olá! Qual capacidade você procura?", criada_em: "2026-11-20T12:00:30Z" }),
  mensagem({
    id: "m3",
    autor: "cliente",
    tipo: "audio",
    midia_url: "http://api.local/midias/a.ogg",
    criada_em: "2026-11-20T12:01:00Z",
  }),
]

export const FICHA_PARCIAL = {
  interesse: {
    modelo: { marca: "Apple", nome: "iPhone 13", conhecido: true },
    capacidade: 128,
    cor: "Azul",
    sku_estoque_confirmado: null,
  },
  tem_troca: true,
  usado: {
    modelo: { marca: "Apple", nome: "iPhone 11", conhecido: true },
    capacidade: 64,
    tela_danificada: true,
    traseira_danificada: false,
    carcaca_marcada: false,
    bateria_pct: 82,
    camera_ok: null,
    outros_defeitos: null,
    peca_trocada: null,
  },
  data_prevista_compra: "2026-12-05",
  pagamento: { tipo: "credito", parcelas: 10, bandeira: "visa", entrada: null },
}

export const PROPOSTA = {
  bloqueado: false,
  aparelho: { sku: "IP13-128", modelo: "iPhone 13", capacidade: "128", cor: "Azul", condicao: "novo" },
  preco_aparelho: "3499.90",
  troca: { status: "avaliada", valor: "800.00", descontos_aplicados: [] },
  desconto: { negociado: "100.00", oportunidade_unica: null, total: "100.00" },
  forma_escolhida: {
    rotulo: "Cartão de crédito em 10x Visa",
    parcelas: 10,
    valor_parcela: "270.00",
    total_pago: "2699.90",
    taxa: "8,50%",
  },
}

export function detalhe(parcial: Partial<DetalheLead> & { card: CardLead }): DetalheLead {
  return {
    ficha: {},
    pendencias: [],
    mensagens: [],
    eventos: [],
    proposta: null,
    handoff_solicitado: false,
    motivo_handoff: null,
    resumo_handoff: null,
    ...parcial,
  }
}

export const DETALHE_MARIA = detalhe({
  card: CARD_MARIA,
  ficha: FICHA_PARCIAL,
  pendencias: ["estoque_confirmado", "usado_camera", "pagamento_bandeira"],
  mensagens: MENSAGENS_MARIA,
  proposta: PROPOSTA,
})

export const RESUMO_API: NonNullable<DetalheLead["resumo_handoff"]> = {
  motivo: "Cliente quer fechar a compra",
  aparelho_desejado: "iPhone 16 128GB",
  troca: "iPhone 13 128GB",
  valor_troca: "1200.00",
  proposta: "Cartão de crédito em 12x Mastercard",
  valor_proposta: "3900.00",
  forma_pagamento: "crédito, 12x, bandeira mastercard",
  data_prevista: "2026-11-25",
  pendencias: ["bandeira do cartão"],
  observacoes: "Cliente decidido, quer parcelar e fechar ainda hoje.",
  gerado_em: "2026-11-20T15:00:00Z",
}
