import type { DetalheLead, MensagemLead } from "@/lib/api"

import { descreverFicha, formatarMoeda } from "./ficha"
import { rotulosDasPendencias } from "./pendencias"

/**
 * Resumo do handoff para o vendedor. Quando a API traz `resumo_handoff` (a IA chamou o vendedor),
 * ele é a fonte (campos estruturados + observações do LLM); sem ele, o resumo é montado aqui a
 * partir da ficha, da proposta e das últimas mensagens (sem observações).
 */
export type ResumoHandoff = {
  motivo: string
  aparelho: string
  troca: string
  pagamento: string
  /** Proposta já apresentada ao cliente (só vem no resumo da API). */
  proposta: string | null
  /** Valores da proposta (aparelho, troca, desconto), só no resumo da API. */
  valores: string | null
  /** Data prevista da compra (dd/mm/aaaa), só no resumo da API. */
  dataPrevista: string | null
  /** Acordo fechado pela IA (linhas rótulo/valor); null quando a IA não fechou, só no resumo da API. */
  acordo: { rotulo: string; valor: string }[] | null
  /** 2–3 frases da IA (objeções, clima, próximo passo); null se ela falhou ou não houve. */
  observacoes: string | null
  pendencias: string[]
  proximoPasso: string
  ultimasMensagens: { autor: string; texto: string }[]
}

const AUTORES: Record<MensagemLead["autor"], string> = { cliente: "Cliente", ia: "IA", vendedor: "Vendedor" }
const LIMITE_MENSAGENS = 3
/** Motivos gravados pelo sistema (não pela IA), que chegam como código. */
const MOTIVOS_DO_SISTEMA: Record<string, string> = {
  falha_llm: "A IA teve uma falha técnica e passou o atendimento para você",
  acordo_fechado: "Acordo fechado pela IA: cliente vai à loja para concluir",
  negociacao: "Cliente quer negociar além do desconto liberado",
}

function textoDaMensagem(m: MensagemLead): string {
  if (m.texto) return m.texto
  if (m.tipo === "audio") return "[Áudio]"
  if (m.tipo === "imagem") return "[Imagem]"
  return ""
}

const NAO_INFORMADO = "Não informado"

function ultimasMensagens(mensagens: MensagemLead[]): ResumoHandoff["ultimasMensagens"] {
  return mensagens.slice(-LIMITE_MENSAGENS).map((m) => ({ autor: AUTORES[m.autor], texto: textoDaMensagem(m) }))
}

function comValor(texto: string | null, valor: string | null, prefixo: string): string | null {
  const dinheiro = formatarMoeda(valor)
  if (texto === null) return null
  return dinheiro ? `${texto} (${prefixo} ${dinheiro})` : texto
}

type ResumoApi = NonNullable<DetalheLead["resumo_handoff"]>

function aparelhoDoResumo(r: ResumoApi): string {
  if (!r.aparelho_desejado) return NAO_INFORMADO
  const base = [r.aparelho_desejado, r.cor].filter(Boolean).join(", ")
  return r.sku ? `${base} (SKU ${r.sku})` : base
}

function trocaDoResumo(r: ResumoApi): string {
  if (!r.troca) return NAO_INFORMADO
  const base = r.troca_condicao ? `${r.troca} (${r.troca_condicao})` : r.troca
  const valor = formatarMoeda(r.valor_troca)
  if (valor) return `${base} · avaliada em ${valor}`
  return r.troca_status === "avaliacao_na_loja" ? `${base} · avaliação na loja` : base
}

function propostaDoResumo(r: ResumoApi): string | null {
  const base = comValor(r.proposta, r.valor_proposta, "total")
  if (base === null) return null
  const parcela = formatarMoeda(r.valor_parcela)
  return r.parcelas && parcela ? `${base} · ${r.parcelas}x de ${parcela}` : base
}

function valoresDoResumo(r: ResumoApi): string | null {
  if (!r.valor_aparelho) return null
  const itens = [
    ["aparelho", r.valor_aparelho],
    ["troca", r.valor_troca],
    ["desconto", r.desconto],
  ] as const
  const partes = itens.flatMap(([rotulo, valor]) => {
    const dinheiro = formatarMoeda(valor)
    return dinheiro ? [`${rotulo} ${dinheiro}`] : []
  })
  return partes.length ? partes.join(", ") : null
}

function dataDoResumo(r: ResumoApi): string | null {
  const [ano, mes, dia] = (r.data_prevista ?? "").split("-")
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : null
}

function dataIso(iso: string | null | undefined): string | null {
  const [ano, mes, dia] = (iso ?? "").split("-")
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : null
}

function acordoDoResumo(r: ResumoApi): ResumoHandoff["acordo"] {
  const a = r.acordo
  if (!a) return null
  const total = formatarMoeda(a.valor_total)
  const forma = a.forma ? (total ? `${a.forma} · total ${total}` : a.forma) : null
  const favorecido = a.pix_favorecido ? ` (favorecido: ${a.pix_favorecido})` : ""
  const linhas: [string, string | null][] = [
    ["Forma", forma],
    ["Cliente vai à loja em", dataIso(a.data_prevista)],
    ["Endereço informado", a.endereco ?? null],
    ["Horário informado", a.horarios ?? null],
    ["Chave Pix informada", a.pix_chave ? `${a.pix_chave}${favorecido}` : null],
  ]
  return linhas.flatMap(([rotulo, valor]) => (valor ? [{ rotulo, valor }] : []))
}

function doResumoDaApi(
  r: ResumoApi,
  mensagens: MensagemLead[],
): ResumoHandoff {
  return {
    motivo: MOTIVOS_DO_SISTEMA[r.motivo] ?? r.motivo,
    aparelho: aparelhoDoResumo(r),
    troca: trocaDoResumo(r),
    pagamento: r.forma_pagamento ?? NAO_INFORMADO,
    proposta: propostaDoResumo(r),
    valores: valoresDoResumo(r),
    dataPrevista: dataDoResumo(r),
    acordo: acordoDoResumo(r),
    observacoes: r.observacoes ?? null,
    pendencias: r.pendencias,
    proximoPasso: r.pendencias[0] ?? "Fechar a venda com o cliente",
    ultimasMensagens: ultimasMensagens(mensagens),
  }
}

export function montarResumoHandoff(
  d: Pick<DetalheLead, "ficha" | "pendencias" | "mensagens" | "motivo_handoff" | "resumo_handoff">,
): ResumoHandoff {
  if (d.resumo_handoff) return doResumoDaApi(d.resumo_handoff, d.mensagens)
  const ficha = descreverFicha(d.ficha)
  const pendencias = rotulosDasPendencias(d.pendencias)
  return {
    motivo: d.motivo_handoff
      ? (MOTIVOS_DO_SISTEMA[d.motivo_handoff] ?? d.motivo_handoff)
      : "Atendimento transferido para o vendedor",
    aparelho: ficha.aparelho,
    troca: ficha.troca,
    pagamento: ficha.pagamento,
    proposta: null,
    valores: null,
    dataPrevista: null,
    acordo: null,
    observacoes: null,
    pendencias,
    proximoPasso: pendencias[0] ?? "Fechar a venda com o cliente",
    ultimasMensagens: ultimasMensagens(d.mensagens),
  }
}
