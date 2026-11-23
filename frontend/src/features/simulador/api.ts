import { apiPublica, mensagemDeErro, URL_API, type criarCliente } from "@/lib/api"

/** Resposta publicada no stream da sessão (IA ou vendedor); ver `WebChatAdapter` no backend. */
export type MensagemWebchat = {
  tipo: "texto" | "audio" | "imagem"
  texto: string | null
  midia_url: string | null
  enviada_em: string
}

export type TipoMidia = "imagem" | "audio"

export type OpcoesStream = {
  baseUrl?: string
  /** Erro de conexão; o EventSource reconecta sozinho, então não fecha a assinatura. */
  onErro?: (erro: Event) => void
}

export type ServicoChat = {
  criarSessao(lojaId: string): Promise<string>
  enviarTexto(lojaId: string, sessao: string, idCliente: string, texto: string): Promise<void>
  /** Sobe o arquivo e envia a mensagem; devolve a `midia_url` guardada pela API. */
  enviarMidia(
    lojaId: string,
    sessao: string,
    idCliente: string,
    arquivo: Blob,
    tipo: TipoMidia,
  ): Promise<string>
  assinar(
    lojaId: string,
    sessao: string,
    onMensagem: (mensagem: MensagemWebchat) => void,
    opcoes?: OpcoesStream,
  ): () => void
}

const TIPOS: ReadonlySet<string> = new Set<MensagemWebchat["tipo"]>(["texto", "audio", "imagem"])

function interpretar(dados: string): MensagemWebchat | null {
  try {
    const m: unknown = JSON.parse(dados)
    if (typeof m === "object" && m !== null && "tipo" in m && typeof m.tipo === "string" && TIPOS.has(m.tipo)) {
      return m as MensagemWebchat
    }
  } catch {
    // heartbeat/lixo: ignora
  }
  return null
}

/** Assina o SSE de respostas da sessão; devolve a função que fecha a conexão. */
export function assinarSessao(
  lojaId: string,
  sessao: string,
  onMensagem: (mensagem: MensagemWebchat) => void,
  { baseUrl = URL_API, onErro }: OpcoesStream = {},
): () => void {
  const fonte = new EventSource(`${baseUrl}/webchat/${lojaId}/sessoes/${sessao}/stream`)
  fonte.onmessage = (evento: MessageEvent<string>) => {
    const mensagem = interpretar(evento.data)
    if (mensagem) onMensagem(mensagem)
  }
  if (onErro) fonte.onerror = onErro
  return () => fonte.close()
}

export function criarServicoWebchat(cliente: ReturnType<typeof criarCliente> = apiPublica): ServicoChat {
  return {
    async criarSessao(lojaId) {
      const { data, error } = await cliente.POST("/webchat/{loja_id}/sessoes", {
        params: { path: { loja_id: lojaId } },
      })
      if (!data) throw new Error(mensagemDeErro(error))
      return data.sessao
    },

    async enviarTexto(lojaId, sessao, idCliente, texto) {
      const { error } = await cliente.POST("/webchat/{loja_id}/sessoes/{sessao}/mensagens", {
        params: { path: { loja_id: lojaId, sessao } },
        body: { id_cliente: idCliente, tipo: "texto", texto },
      })
      if (error) throw new Error(mensagemDeErro(error))
    },

    async enviarMidia(lojaId, sessao, idCliente, arquivo, tipo) {
      const upload = await cliente.POST("/webchat/{loja_id}/midias", {
        params: { path: { loja_id: lojaId } },
        // O tipo gerado para `UploadFile` é `string`; o serializador monta o multipart real.
        body: { arquivo: arquivo as unknown as string },
        bodySerializer: () => {
          const corpo = new FormData()
          corpo.append("arquivo", arquivo)
          return corpo
        },
      })
      if (!upload.data) throw new Error(mensagemDeErro(upload.error))
      const midiaUrl = upload.data.midia_url

      const { error } = await cliente.POST("/webchat/{loja_id}/sessoes/{sessao}/mensagens", {
        params: { path: { loja_id: lojaId, sessao } },
        body: { id_cliente: idCliente, tipo, midia_url: midiaUrl },
      })
      if (error) throw new Error(mensagemDeErro(error))
      return midiaUrl
    },

    assinar: assinarSessao,
  }
}

export const servicoWebchat: ServicoChat = criarServicoWebchat()
