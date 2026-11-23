"use client"

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { KanbanSquare, WifiOff } from "lucide-react"
import { useMemo, useState, useSyncExternalStore } from "react"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { ETAPAS, rotuloDaEtapa, type Etapa } from "@/lib/etapas"

import { ConteudoCard } from "./card-lead"
import { ColunaDoKanban, type EstadoAlvo } from "./coluna-kanban"
import {
  filtrarColunas,
  localizarCard,
  opcoesDeVendedor,
  validarMovimento,
  type FiltroVendedor,
} from "./regras"
import { useKanban } from "./use-kanban"

const ehEtapa = (id: unknown): id is Etapa => ETAPAS.some((e) => e.valor === id)

/** Relógio em passos de `intervaloMs`; no servidor vale 0 (nada de data durante o prerender). */
function useAgora(intervaloMs = 30_000) {
  const passo = useSyncExternalStore(
    (aviso) => {
      const t = setInterval(aviso, intervaloMs)
      return () => clearInterval(t)
    },
    () => Math.floor(Date.now() / intervaloMs),
    () => 0,
  )
  return useMemo(() => new Date(passo * intervaloMs), [passo, intervaloMs])
}

function Carregando() {
  return (
    <div className="flex gap-3 overflow-x-auto" aria-busy="true" aria-label="Carregando kanban">
      {ETAPAS.map((e) => (
        <div key={e.valor} className="flex w-72 shrink-0 flex-col gap-2 lg:w-auto lg:min-w-56 lg:flex-1">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ))}
    </div>
  )
}

export function KanbanBoard({ lojaId }: { lojaId: string }) {
  const { colunas, status, tempoRealOk, mover, recarregar } = useKanban(lojaId)
  const agora = useAgora()
  const [filtro, setFiltro] = useState<FiltroVendedor>("todos")
  const [arrastandoId, setArrastandoId] = useState<string | null>(null)
  const [sobre, setSobre] = useState<Etapa | null>(null)

  const sensores = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor),
  )

  const opcoes = useMemo(() => opcoesDeVendedor(colunas), [colunas])
  // Se o vendedor filtrado some dos cards, volta para "Todos".
  const filtroEfetivo = opcoes.some((o) => o.valor === filtro) ? filtro : "todos"
  const visiveis = useMemo(() => filtrarColunas(colunas, filtroEfetivo), [colunas, filtroEfetivo])

  const arrastando = arrastandoId ? localizarCard(colunas, arrastandoId)?.card ?? null : null

  function fimDoArrasto(e: DragEndEvent) {
    const leadId = String(e.active.id)
    const destino = e.over?.id
    setArrastandoId(null)
    setSobre(null)
    if (!ehEtapa(destino)) return
    void mover(leadId, destino)
  }

  function alvoDa(etapa: Etapa): EstadoAlvo {
    if (!arrastando) return "neutro"
    const regra = validarMovimento(arrastando.etapa, etapa)
    if (regra.permitido) return "permitido"
    return regra.noop ? "neutro" : "proibido"
  }

  function motivoDaRegra(etapa: Etapa): string | undefined {
    if (!arrastando) return undefined
    const regra = validarMovimento(arrastando.etapa, etapa)
    return regra.permitido ? undefined : regra.motivo
  }

  const anuncios: Announcements = {
    onDragStart: ({ active }) => `Pegou o card ${nomeDe(String(active.id))}.`,
    onDragOver: ({ active, over }) =>
      over && ehEtapa(over.id) ? `Card ${nomeDe(String(active.id))} sobre a coluna ${rotuloDaEtapa(over.id)}.` : undefined,
    onDragEnd: ({ active, over }) =>
      over && ehEtapa(over.id)
        ? `Card ${nomeDe(String(active.id))} solto na coluna ${rotuloDaEtapa(over.id)}.`
        : `Card ${nomeDe(String(active.id))} solto fora das colunas.`,
    onDragCancel: ({ active }) => `Arrasto do card ${nomeDe(String(active.id))} cancelado.`,
  }
  function nomeDe(id: string) {
    const c = localizarCard(colunas, id)?.card
    return c?.nome ?? c?.telefone ?? "do lead"
  }

  if (status === "carregando") return <Carregando />
  if (status === "erro") {
    return (
      <EmptyState
        icon={KanbanSquare}
        title="Não foi possível carregar o kanban"
        description="Verifique a conexão e tente de novo."
        action={<Button onClick={() => recarregar()}>Tentar de novo</Button>}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Filtrar por vendedor" className="flex flex-wrap gap-1.5">
          {opcoes.map((o) => (
            <Button
              key={o.valor}
              size="xs"
              variant={o.valor === filtroEfetivo ? "default" : "outline"}
              aria-pressed={o.valor === filtroEfetivo}
              onClick={() => setFiltro(o.valor)}
            >
              {o.rotulo}
            </Button>
          ))}
        </div>
        {!tempoRealOk ? (
          <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <WifiOff aria-hidden="true" className="size-3.5" />
            Tempo real indisponível, reconectando…
          </p>
        ) : null}
      </div>

      <DndContext
        sensors={sensores}
        accessibility={{
          announcements: anuncios,
          screenReaderInstructions: {
            draggable:
              "Para mover o card, pressione espaço ou Enter, use as setas para escolher a coluna e pressione espaço ou Enter para soltar. Esc cancela.",
          },
        }}
        onDragStart={(e: DragStartEvent) => setArrastandoId(String(e.active.id))}
        onDragOver={(e: DragOverEvent) => setSobre(ehEtapa(e.over?.id) ? (e.over!.id as Etapa) : null)}
        onDragEnd={fimDoArrasto}
        onDragCancel={() => {
          setArrastandoId(null)
          setSobre(null)
        }}
      >
        <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-2 md:mx-0 md:px-0">
          {visiveis.map((coluna) => (
            <ColunaDoKanban
              key={coluna.etapa}
              coluna={coluna}
              agora={agora}
              alvo={alvoDa(coluna.etapa)}
              motivoProibido={motivoDaRegra(coluna.etapa)}
              sobre={sobre === coluna.etapa}
            />
          ))}
        </div>
        <DragOverlay>
          {arrastando ? (
            <Card size="sm" className="w-72 cursor-grabbing gap-1 px-3 shadow-lg">
              <ConteudoCard lead={arrastando} agora={agora} link={false} />
            </Card>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
