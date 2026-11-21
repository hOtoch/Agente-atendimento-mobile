"use client"

import { ArrowLeft, Send, UserRound } from "lucide-react"
import { useEffect, useRef, useState, type KeyboardEvent } from "react"

import { DonoBadge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { MessageBubble } from "@/components/ui/message-bubble"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import type { DetalheLead, MensagemLead } from "@/lib/api"
import { contatoDoLead } from "@/lib/lead"
import { cn } from "@/lib/utils"

import { interpretarDono, podeAssumir, podeResponder } from "./regras"
import type { StatusCarga } from "./use-inbox"

type Props = {
  detalhe: DetalheLead | null
  status: StatusCarga
  vendedorAtualId: string | null
  ocupado: boolean
  semCanal: ReadonlySet<string>
  onAssumir: () => void
  onDevolver: () => void
  onEnviar: (texto: string) => Promise<boolean>
  onVoltar: () => void
  onVerFicha: () => void
  onRecarregar: () => void
  className?: string
}

function autorDoBalao(m: MensagemLead): string | undefined {
  if (m.autor === "ia") return "IA"
  if (m.autor === "vendedor") return "Vendedor"
  return undefined
}

function situacao(detalhe: DetalheLead, vendedorAtualId: string | null): string {
  const dono = interpretarDono(detalhe.card.dono)
  if (dono.tipo === "ia") return "IA atendendo"
  if (dono.vendedorId === null) return "Aguardando vendedor"
  if (podeResponder(detalhe.card.dono, vendedorAtualId)) return "Você está atendendo"
  return `Atendida por ${detalhe.card.vendedor_nome ?? "outro vendedor"}`
}

export function Conversa({
  detalhe,
  status,
  vendedorAtualId,
  ocupado,
  semCanal,
  onAssumir,
  onDevolver,
  onEnviar,
  onVoltar,
  onVerFicha,
  onRecarregar,
  className,
}: Props) {
  const [texto, setTexto] = useState("")
  const [enviando, setEnviando] = useState(false)
  const lista = useRef<HTMLDivElement>(null)
  const mensagens = detalhe?.mensagens

  useEffect(() => {
    const el = lista.current
    if (el) el.scrollTop = el.scrollHeight
  }, [mensagens])

  const idDoLead = detalhe?.card.id
  useEffect(() => {
    // rascunho não vaza de uma conversa para outra
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTexto("")
  }, [idDoLead])

  const barraVoltar = (
    <Button variant="ghost" size="icon-sm" className="lg:hidden" aria-label="Voltar para a lista" onClick={onVoltar}>
      <ArrowLeft aria-hidden />
    </Button>
  )

  if (status === "erro") {
    return (
      <section aria-label="Conversa" className={cn("min-h-0 flex-col gap-2", className)}>
        <div>{barraVoltar}</div>
        <EmptyState
          title="Não foi possível abrir a conversa"
          description="O lead pode não existir mais ou o servidor está fora do ar."
          action={
            <Button variant="outline" size="sm" onClick={onRecarregar}>
              Tentar de novo
            </Button>
          }
        />
      </section>
    )
  }

  if (!detalhe) {
    return (
      <section aria-label="Conversa" className={cn("min-h-0 flex-col gap-2", className)}>
        <div>{barraVoltar}</div>
        <div role="status" aria-label="Carregando conversa" className="flex flex-col gap-2">
          <Skeleton className="h-10 w-1/2" />
          <Skeleton className="h-16 w-3/4" />
          <Skeleton className="ml-auto h-16 w-3/4" />
        </div>
      </section>
    )
  }

  const { card } = detalhe
  const contato = contatoDoLead(card)
  const dono = interpretarDono(card.dono)
  const habilitado = podeResponder(card.dono, vendedorAtualId)
  const assumivel = podeAssumir(card.dono)
  const vazio = texto.trim() === ""

  async function enviar() {
    const limpo = texto.trim()
    if (!limpo || enviando || !habilitado) return
    setEnviando(true)
    try {
      if (await onEnviar(limpo)) setTexto("")
    } finally {
      setEnviando(false)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void enviar()
    }
  }

  return (
    <section aria-label="Conversa" className={cn("min-h-0 flex-col rounded-lg border border-border bg-card", className)}>
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        {barraVoltar}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-foreground">{contato.titulo}</h2>
          <p className="truncate text-xs text-muted-foreground">{contato.detalhe}</p>
        </div>
        <DonoBadge dono={dono.tipo} />
        <Button variant="outline" size="sm" className="xl:hidden" onClick={onVerFicha}>
          Ver ficha
        </Button>
      </header>

      <div ref={lista} className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
        {detalhe.mensagens.length === 0 ? (
          <EmptyState title="Sem mensagens" description="Quando o cliente escrever, a conversa aparece aqui." />
        ) : (
          detalhe.mensagens.map((m) => (
            <MessageBubble
              key={m.id}
              lado={m.autor === "cliente" ? "cliente" : "atendente"}
              tipo={m.tipo}
              texto={m.texto}
              midiaUrl={m.midia_url}
              transcricao={m.transcricao}
              horario={m.criada_em}
              autor={autorDoBalao(m)}
              erro={semCanal.has(m.id) ? "Salva no painel; o canal ainda não envia." : undefined}
            />
          ))
        )}
      </div>

      <footer className="flex flex-col gap-2 border-t border-border p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
            <UserRound aria-hidden className="size-4 text-muted-foreground" />
            {situacao(detalhe, vendedorAtualId)}
          </p>
          {assumivel ? (
            <Button size="sm" disabled={ocupado || vendedorAtualId === null} onClick={onAssumir}>
              Assumir conversa
            </Button>
          ) : habilitado ? (
            <Button size="sm" variant="outline" disabled={ocupado} onClick={onDevolver}>
              Devolver para a IA
            </Button>
          ) : null}
        </div>
        {assumivel && vendedorAtualId === null ? (
          <p className="text-xs text-muted-foreground">Cadastre um vendedor ativo para poder assumir.</p>
        ) : null}
        <div className="flex items-end gap-2">
          <Textarea
            aria-label="Resposta ao cliente"
            placeholder={habilitado ? "Escreva a resposta ao cliente" : "Assuma a conversa para responder"}
            value={texto}
            disabled={!habilitado}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={aoTeclar}
            rows={2}
          />
          <Button disabled={!habilitado || vazio || enviando} onClick={() => void enviar()}>
            <Send aria-hidden data-icon="inline-start" />
            Enviar
          </Button>
        </div>
      </footer>
    </section>
  )
}
