"use client"

import { WifiOff } from "lucide-react"
import { useState } from "react"

import { Campo } from "@/components/ui/campo"
import { EmptyState } from "@/components/ui/empty-state"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

import { Conversa } from "./conversa"
import { ListaConversas } from "./lista-conversas"
import { PainelFicha } from "./painel-ficha"
import { useInbox, type Assinar, type Cliente } from "./use-inbox"
import { useVendedorAtual } from "./vendedor-atual"

type Props = {
  lojaId: string
  /** Conversa aberta (vem da URL `?lead=`); null = só a lista. */
  leadId: string | null
  onSelecionar: (leadId: string | null) => void
  /** Troca o acesso à API/SSE (testes). */
  cliente?: Cliente
  assinar?: Assinar
}

export function Inbox({ lojaId, leadId, onSelecionar, cliente = api, assinar }: Props) {
  const [fichaAberta, setFichaAberta] = useState(false)
  const inbox = useInbox(lojaId, leadId, cliente, assinar, (removido) => {
    // a conversa aberta deixou de existir (reset aqui ou em outra aba): volta para a lista
    if (removido === leadId) {
      setFichaAberta(false)
      onSelecionar(null)
    }
  })
  const ativos = inbox.vendedores.filter((v) => v.ativo)
  const { vendedorId, definir } = useVendedorAtual(lojaId, ativos)
  const itens = ativos.map((v) => ({ value: v.id, label: v.nome }))

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Campo label="Atendendo como" className="w-full sm:w-64">
          {(controle) => (
            <Select
              value={vendedorId ?? ""}
              items={itens}
              disabled={itens.length === 0}
              onValueChange={(v) => definir(String(v))}
            >
              <SelectTrigger
                id={controle.id}
                aria-labelledby={controle["aria-labelledby"]}
                className="w-full"
              >
                <SelectValue placeholder="Nenhum vendedor ativo" />
              </SelectTrigger>
              <SelectContent>
                {itens.map((i) => (
                  <SelectItem key={i.value} value={i.value}>
                    {i.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Campo>
        {inbox.tempoRealOk ? null : (
          <p role="status" className="flex items-center gap-1.5 text-xs text-warning">
            <WifiOff aria-hidden className="size-3.5" />
            Tempo real indisponível, reconectando...
          </p>
        )}
      </div>

      <div className="grid h-[calc(100dvh-14rem)] min-h-96 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)] xl:grid-cols-[18rem_minmax(0,1fr)_20rem]">
        <ListaConversas
          conversas={inbox.conversas}
          status={inbox.statusLista}
          leadId={leadId}
          onSelecionar={onSelecionar}
          onRecarregar={inbox.recarregar}
          className={cn(leadId ? "hidden lg:flex" : "flex")}
        />

        {leadId ? (
          <Conversa
            detalhe={inbox.detalhe}
            status={inbox.statusDetalhe}
            vendedorAtualId={vendedorId}
            ocupado={inbox.ocupado}
            semCanal={inbox.semCanal}
            onAssumir={() => vendedorId && void inbox.assumir(vendedorId)}
            onDevolver={() => void inbox.devolver()}
            onEnviar={inbox.enviar}
            onVoltar={() => onSelecionar(null)}
            onVerFicha={() => setFichaAberta(true)}
            onRecarregar={inbox.recarregar}
            className="flex"
          />
        ) : (
          <div className="hidden min-h-0 lg:block">
            <EmptyState
              title="Selecione uma conversa"
              description="Escolha um lead na lista para ver as mensagens, assumir o atendimento ou devolver para a IA."
            />
          </div>
        )}

        <aside
          aria-label="Ficha do lead"
          className="hidden min-h-0 overflow-y-auto xl:block"
        >
          {inbox.detalhe ? (
            <PainelFicha detalhe={inbox.detalhe} ocupado={inbox.ocupado} onResetar={() => void inbox.resetar()} />
          ) : null}
        </aside>
      </div>

      <Sheet open={fichaAberta} onOpenChange={setFichaAberta}>
        <SheetContent side="right" className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Ficha do lead</SheetTitle>
            <SheetDescription>Dados coletados, pendências e proposta.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-4">
            {inbox.detalhe ? (
              <PainelFicha detalhe={inbox.detalhe} ocupado={inbox.ocupado} onResetar={() => void inbox.resetar()} />
            ) : null}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
