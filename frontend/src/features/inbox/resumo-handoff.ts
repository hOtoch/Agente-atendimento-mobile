import type { DetalheLead, MensagemLead } from "@/lib/api"

import { descreverFicha } from "./ficha"
import { rotulosDasPendencias } from "./pendencias"

/**
 * Resumo do handoff montado no front a partir da ficha, da proposta e das últimas mensagens.
 * O resumo gerado pela IA chega no M5 (#32); este é o substituto estruturado e determinístico.
 */
export type ResumoHandoff = {
  motivo: string
  aparelho: string
  troca: string
  pagamento: string
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

export function montarResumoHandoff(
  d: Pick<DetalheLead, "ficha" | "pendencias" | "mensagens" | "motivo_handoff">,
): ResumoHandoff {
  const ficha = descreverFicha(d.ficha)
  const pendencias = rotulosDasPendencias(d.pendencias)
  return {
    motivo: d.motivo_handoff
      ? (MOTIVOS_DO_SISTEMA[d.motivo_handoff] ?? d.motivo_handoff)
      : "Atendimento transferido para o vendedor",
    aparelho: ficha.aparelho,
    troca: ficha.troca,
    pagamento: ficha.pagamento,
    pendencias,
    proximoPasso: pendencias[0] ?? "Fechar a venda com o cliente",
    ultimasMensagens: d.mensagens.slice(-LIMITE_MENSAGENS).map((m) => ({
      autor: AUTORES[m.autor],
      texto: textoDaMensagem(m),
    })),
  }
}
