/** Sessão atual do chat (e as mensagens já trocadas) no sessionStorage: sobrevive ao reload. */

export type ItemGuardado = {
  id: string
  lado: "cliente" | "atendente"
  tipo: "texto" | "imagem" | "audio"
  texto: string | null
  midiaUrl: string | null
  horario: string
  erro?: string
}

const chaveSessao = (lojaId: string) => `simulador:sessao:${lojaId}`
const chaveMensagens = (lojaId: string, sessao: string) => `simulador:mensagens:${lojaId}:${sessao}`

function ler(chave: string): string | null {
  try {
    return window.sessionStorage.getItem(chave)
  } catch {
    return null
  }
}

function gravar(chave: string, valor: string) {
  try {
    window.sessionStorage.setItem(chave, valor)
  } catch {
    // storage bloqueado: o chat segue funcionando, só não sobrevive ao reload
  }
}

function apagar(chave: string) {
  try {
    window.sessionStorage.removeItem(chave)
  } catch {
    // idem
  }
}

export const lerSessao = (lojaId: string) => ler(chaveSessao(lojaId))
export const guardarSessao = (lojaId: string, sessao: string) => gravar(chaveSessao(lojaId), sessao)

export function esquecerSessao(lojaId: string) {
  const sessao = lerSessao(lojaId)
  if (sessao) apagar(chaveMensagens(lojaId, sessao))
  apagar(chaveSessao(lojaId))
}

export function lerMensagens(lojaId: string, sessao: string): ItemGuardado[] {
  const bruto = ler(chaveMensagens(lojaId, sessao))
  if (!bruto) return []
  try {
    const itens: unknown = JSON.parse(bruto)
    return Array.isArray(itens) ? (itens as ItemGuardado[]) : []
  } catch {
    return []
  }
}

export function guardarMensagens(lojaId: string, sessao: string, itens: ItemGuardado[]) {
  // `blob:` só vale nesta aba/carregamento: não guarda mídia ainda não enviada.
  const duraveis = itens.filter((i) => !i.midiaUrl?.startsWith("blob:") && !i.erro)
  gravar(chaveMensagens(lojaId, sessao), JSON.stringify(duraveis))
}
