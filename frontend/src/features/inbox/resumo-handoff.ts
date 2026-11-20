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
  falha_llm: "A IA ficou indisponível e passou a conversa para o vendedor",
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

function doResumoDaApi(
  r: NonNullable<DetalheLead["resumo_handoff"]>,
  mensagens: MensagemLead[],
): ResumoHandoff {
  return {
    motivo: MOTIVOS_DO_SISTEMA[r.motivo] ?? r.motivo,
    aparelho: r.aparelho_desejado ?? NAO_INFORMADO,
    troca: comValor(r.troca, r.valor_troca, "avaliada em") ?? NAO_INFORMADO,
    pagamento: r.forma_pagamento ?? NAO_INFORMADO,
    proposta: comValor(r.proposta, r.valor_proposta, "total"),
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
    observacoes: null,
    pendencias,
    proximoPasso: pendencias[0] ?? "Fechar a venda com o cliente",
    ultimasMensagens: ultimasMensagens(d.mensagens),
  }
}
