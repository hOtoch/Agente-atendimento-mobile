"use client"

import { Image as IconeImagem, Mic, Send, Square, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { MessageBubble } from "@/components/ui/message-bubble"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"
import { cn } from "@/lib/utils"

import { servicoWebchat, type MensagemWebchat, type ServicoChat, type TipoMidia } from "./api"
import { useGravadorAudio } from "./gravador-audio"
import {
  esquecerSessao,
  guardarMensagens,
  guardarSessao,
  lerMensagens,
  lerSessao,
  type ItemGuardado,
} from "./sessao-storage"

type Item = ItemGuardado

const TIPOS_IMAGEM = "image/jpeg,image/png,image/webp"

function novoId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

type Props = {
  lojaId: string
  /** Troca o acesso à API/SSE (testes). */
  servico?: ServicoChat
  titulo?: string
  className?: string
}

/** Chat do cliente: simula o WhatsApp no navegador. Respostas da IA/vendedor chegam por SSE. */
export function ChatWeb({ lojaId, servico = servicoWebchat, titulo = "Atendimento da loja", className }: Props) {
  const toast = useToast()
  const gravador = useGravadorAudio()
  const [sessao, setSessao] = useState<string | null>(null)
  const [falhaInicio, setFalhaInicio] = useState<string | null>(null)
  const [geracao, setGeracao] = useState(0)
  const [itens, setItens] = useState<Item[]>([])
  const [texto, setTexto] = useState("")
  const [imagem, setImagem] = useState<{ arquivo: File; previa: string } | null>(null)
  const [enviandoMidia, setEnviandoMidia] = useState(false)
  const itensRef = useRef<Item[]>([])
  const sessaoRef = useRef<string | null>(null)
  const lista = useRef<HTMLDivElement>(null)
  const seletorImagem = useRef<HTMLInputElement>(null)

  const definirItens = useCallback(
    (proximo: (atual: Item[]) => Item[]) => {
      const novo = proximo(itensRef.current)
      itensRef.current = novo
      setItens(novo)
      if (sessaoRef.current) guardarMensagens(lojaId, sessaoRef.current, novo)
    },
    [lojaId],
  )

  // Abre (ou retoma) a sessão da loja.
  useEffect(() => {
    let ativo = true
    sessaoRef.current = null
    itensRef.current = []

    async function abrir() {
      try {
        const guardada = lerSessao(lojaId)
        const id = guardada ?? (await servico.criarSessao(lojaId))
        if (!ativo) return
        if (!guardada) guardarSessao(lojaId, id)
        sessaoRef.current = id
        itensRef.current = guardada ? lerMensagens(lojaId, id) : []
        setItens(itensRef.current)
        setSessao(id)
      } catch (e) {
        if (ativo) setFalhaInicio(e instanceof Error ? e.message : "Erro inesperado.")
      }
    }
    void abrir()
    return () => {
      ativo = false
    }
  }, [lojaId, servico, geracao])

  // Respostas em tempo real.
  useEffect(() => {
    if (!sessao) return
    return servico.assinar(
      lojaId,
      sessao,
      (m: MensagemWebchat) =>
        definirItens((atual) => [
          ...atual,
          {
            id: novoId(),
            lado: "atendente",
            tipo: m.tipo,
            texto: m.texto,
            midiaUrl: m.midia_url,
            horario: m.enviada_em,
          },
        ]),
      {},
    )
  }, [lojaId, sessao, servico, definirItens])

  useEffect(() => {
    const el = lista.current
    if (el) el.scrollTop = el.scrollHeight
  }, [itens])

  useEffect(() => {
    const previa = imagem?.previa
    return () => {
      if (previa) URL.revokeObjectURL(previa)
    }
  }, [imagem])

  const atualizarItem = useCallback(
    (id: string, mudanca: Partial<Item>) =>
      definirItens((atual) => atual.map((i) => (i.id === id ? { ...i, ...mudanca } : i))),
    [definirItens],
  )

  function falhou(id: string, e: unknown) {
    const mensagem = e instanceof Error ? e.message : "Erro inesperado."
    atualizarItem(id, { erro: "Não enviada" })
    toast.erro(mensagem)
  }

  async function enviarTexto(e: FormEvent) {
    e.preventDefault()
    const conteudo = texto.trim()
    if (!conteudo || !sessao) return
    const item: Item = {
      id: novoId(),
      lado: "cliente",
      tipo: "texto",
      texto: conteudo,
      midiaUrl: null,
      horario: new Date().toISOString(),
    }
    setTexto("")
    definirItens((atual) => [...atual, item])
    try {
      await servico.enviarTexto(lojaId, sessao, item.id, conteudo)
    } catch (erro) {
      falhou(item.id, erro)
    }
  }

  async function enviarMidia(arquivo: Blob, tipo: TipoMidia, previa: string) {
    if (!sessao) return
    const item: Item = {
      id: novoId(),
      lado: "cliente",
      tipo,
      texto: null,
      midiaUrl: previa,
      horario: new Date().toISOString(),
    }
    definirItens((atual) => [...atual, item])
    setEnviandoMidia(true)
    try {
      const url = await servico.enviarMidia(lojaId, sessao, item.id, arquivo, tipo)
      atualizarItem(item.id, { midiaUrl: url })
    } catch (erro) {
      falhou(item.id, erro)
    } finally {
      setEnviandoMidia(false)
    }
  }

  function escolherImagem(arquivo: File | undefined) {
    if (!arquivo) return
    setImagem({ arquivo, previa: URL.createObjectURL(arquivo) })
  }

  async function confirmarImagem() {
    if (!imagem) return
    const { arquivo, previa } = imagem
    setImagem(null)
    await enviarMidia(arquivo, "imagem", previa)
  }

  async function alternarGravacao() {
    if (!gravador.gravando) {
      try {
        await gravador.iniciar()
      } catch {
        toast.erro("Não foi possível acessar o microfone. Verifique a permissão do navegador.")
      }
      return
    }
    const arquivo = await gravador.parar()
    if (arquivo) await enviarMidia(arquivo, "audio", URL.createObjectURL(arquivo))
  }

  function novaConversa() {
    if (gravador.gravando) void gravador.parar()
    esquecerSessao(lojaId)
    setImagem(null)
    setTexto("")
    setSessao(null)
    setFalhaInicio(null)
    setItens([])
    setGeracao((g) => g + 1)
  }

  const pronto = sessao !== null

  return (
    <section
      data-testid="chat-web"
      aria-label="Chat com a loja"
      className={cn(
        "mx-auto flex h-dvh w-full max-w-lg flex-col bg-background text-foreground sm:border-x sm:border-border",
        className,
      )}
    >
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <Avatar>
          <AvatarFallback>IA</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold">{titulo}</h1>
          <p className="text-xs text-muted-foreground">Responde em instantes</p>
        </div>
        <Button variant="outline" size="sm" onClick={novaConversa}>
          Nova conversa
        </Button>
      </header>

      <div
        ref={lista}
        role="log"
        aria-label="Conversa"
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 py-3"
      >
        {falhaInicio ? (
          <EmptyState title="Não foi possível iniciar a conversa" description={falhaInicio} />
        ) : !pronto ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="ml-auto h-10 w-1/2" />
          </div>
        ) : itens.length === 0 ? (
          <EmptyState title="Envie uma mensagem para começar" description="A loja responde aqui, em tempo real." />
        ) : (
          itens.map((i) => (
            <MessageBubble
              key={i.id}
              lado={i.lado}
              tipo={i.tipo}
              texto={i.texto}
              midiaUrl={i.midiaUrl}
              horario={i.horario}
              erro={i.erro}
              perspectiva="cliente"
            />
          ))
        )}
      </div>

      {imagem ? (
        <div className="flex items-center gap-3 border-t border-border px-4 py-2">
          {/* eslint-disable-next-line @next/next/no-img-element -- preview local (blob:) */}
          <img
            src={imagem.previa}
            alt="Pré-visualização da imagem"
            className="size-16 shrink-0 rounded-md object-cover"
          />
          <div className="flex min-w-0 flex-1 flex-wrap gap-2">
            <Button size="sm" onClick={() => void confirmarImagem()} disabled={enviandoMidia}>
              Enviar imagem
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setImagem(null)}>
              <X aria-hidden /> Cancelar
            </Button>
          </div>
        </div>
      ) : null}

      <form onSubmit={(e) => void enviarTexto(e)} className="flex items-center gap-2 border-t border-border p-3">
        <input
          ref={seletorImagem}
          type="file"
          accept={TIPOS_IMAGEM}
          aria-label="Arquivo de imagem"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            escolherImagem(e.target.files?.[0])
            e.target.value = ""
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-lg"
          aria-label="Anexar imagem"
          disabled={!pronto || gravador.gravando}
          onClick={() => seletorImagem.current?.click()}
        >
          <IconeImagem aria-hidden />
        </Button>
        {gravador.gravando ? (
          <>
            <p className="min-w-0 flex-1 truncate text-sm text-danger" role="status">
              Gravando áudio…
            </p>
            <Button
              type="button"
              variant="destructive"
              size="icon-lg"
              aria-label="Parar e enviar áudio"
              onClick={() => void alternarGravacao()}
            >
              <Square aria-hidden />
            </Button>
          </>
        ) : (
          <>
            <label htmlFor="chat-mensagem" className="sr-only">
              Mensagem
            </label>
            <Input
              id="chat-mensagem"
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder="Digite sua mensagem"
              autoComplete="off"
              disabled={!pronto}
              className="h-9 min-w-0 flex-1"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon-lg"
              aria-label="Gravar áudio"
              disabled={!pronto || !gravador.suportado}
              onClick={() => void alternarGravacao()}
            >
              <Mic aria-hidden />
            </Button>
            <Button type="submit" size="icon-lg" aria-label="Enviar" disabled={!pronto || !texto.trim()}>
              <Send aria-hidden />
            </Button>
          </>
        )}
      </form>
    </section>
  )
}
