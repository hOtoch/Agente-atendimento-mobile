"use client"

import { RotateCcw } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EtapaBadge } from "@/components/ui/badge"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import type { DetalheLead } from "@/lib/api"
import { contatoDoLead } from "@/lib/lead"

import { descreverFicha, descreverProposta } from "./ficha"
import { rotulosDasPendencias } from "./pendencias"
import { montarResumoHandoff } from "./resumo-handoff"
import { interpretarDono } from "./regras"

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{rotulo}</dt>
      <dd className="text-sm text-foreground">{valor}</dd>
    </div>
  )
}

function ResumoHandoff({ detalhe }: { detalhe: DetalheLead }) {
  const r = montarResumoHandoff(detalhe)
  return (
    <section aria-label="Resumo do handoff">
      <Card size="sm">
        <CardHeader>
          <CardTitle>Resumo do handoff</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-foreground">{r.motivo}</p>
          <dl className="flex flex-col gap-2">
            <Linha rotulo="Aparelho" valor={r.aparelho} />
            <Linha rotulo="Troca" valor={r.troca} />
            <Linha rotulo="Pagamento" valor={r.pagamento} />
            {r.proposta ? <Linha rotulo="Proposta" valor={r.proposta} /> : null}
            {r.valores ? <Linha rotulo="Valores" valor={r.valores} /> : null}
            {r.dataPrevista ? <Linha rotulo="Data prevista" valor={r.dataPrevista} /> : null}
            <Linha rotulo="Próximo passo" valor={r.proximoPasso} />
          </dl>
          {r.acordo?.length ? (
            <dl role="group" aria-label="Acordo fechado" className="flex flex-col gap-2">
              <h4 className="text-xs font-medium text-foreground">Acordo fechado</h4>
              {r.acordo.map((l) => (
                <Linha key={l.rotulo} rotulo={l.rotulo} valor={l.valor} />
              ))}
            </dl>
          ) : null}
          {r.observacoes ? (
            <div className="flex flex-col gap-1">
              <h4 className="text-xs text-muted-foreground">Observações da IA</h4>
              <p className="text-sm text-foreground">{r.observacoes}</p>
            </div>
          ) : null}
          {r.ultimasMensagens.length ? (
            <div className="flex flex-col gap-1">
              <h4 className="text-xs text-muted-foreground">Últimas mensagens</h4>
              <ul className="flex flex-col gap-1">
                {r.ultimasMensagens.map((m, i) => (
                  <li key={i} className="text-xs text-foreground">
                    <span className="font-medium">{m.autor}:</span> {m.texto}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  )
}

function ResetarConversa({ ocupado, onResetar }: { ocupado: boolean; onResetar: () => void }) {
  const [aberto, setAberto] = useState(false)
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Recomeçar do zero</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">
          Apaga o histórico e a memória da IA. Útil para testar o atendimento de novo.
        </p>
        <Dialog open={aberto} onOpenChange={setAberto}>
          <DialogTrigger
            render={
              <Button variant="destructive" size="sm" disabled={ocupado}>
                <RotateCcw aria-hidden data-icon="inline-start" />
                Resetar conversa
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Resetar esta conversa?</DialogTitle>
              <DialogDescription>
                Isso apaga todas as mensagens, a ficha e o lead, e não tem volta. Se o cliente escrever
                de novo, a IA começa um atendimento do zero.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="outline">Cancelar</Button>} />
              <Button
                variant="destructive"
                disabled={ocupado}
                onClick={() => {
                  setAberto(false)
                  onResetar()
                }}
              >
                Apagar conversa
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  )
}

type PropsPainel = {
  detalhe: DetalheLead
  /** Sem `onResetar`, a opção de resetar não aparece. */
  onResetar?: () => void
  ocupado?: boolean
}

/** Conteúdo do painel lateral: etapa, ficha, pendências, proposta, resumo do handoff e reset. */
export function PainelFicha({ detalhe, onResetar, ocupado = false }: PropsPainel) {
  const ficha = descreverFicha(detalhe.ficha)
  const proposta = descreverProposta(detalhe.proposta)
  const pendencias = rotulosDasPendencias(detalhe.pendencias)
  const contato = contatoDoLead(detalhe.card)
  const mostrarResumo = detalhe.handoff_solicitado || interpretarDono(detalhe.card.dono).tipo === "vendedor"

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{contato.titulo}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">{contato.detalhe}</p>
        </div>
        <EtapaBadge etapa={detalhe.card.etapa} />
      </div>

      {mostrarResumo ? <ResumoHandoff detalhe={detalhe} /> : null}

      <Card size="sm">
        <CardHeader>
          <CardTitle>Ficha</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="flex flex-col gap-2">
            <Linha rotulo="Aparelho desejado" valor={ficha.aparelho} />
            <Linha rotulo="Usado / troca" valor={ficha.troca} />
            <Linha rotulo="Data prevista" valor={ficha.dataPrevista} />
            <Linha rotulo="Forma de pagamento" valor={ficha.pagamento} />
          </dl>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Pendências</CardTitle>
        </CardHeader>
        <CardContent>
          {pendencias.length ? (
            <ul className="flex list-disc flex-col gap-1 pl-4 text-sm text-foreground">
              {pendencias.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Ficha completa: nada pendente.</p>
          )}
        </CardContent>
      </Card>

      {proposta ? (
        <Card size="sm">
          <CardHeader>
            <CardTitle>Proposta</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="flex flex-col gap-2">
              <Linha rotulo="Aparelho" valor={proposta.precoAparelho} />
              {proposta.troca ? <Linha rotulo="Troca" valor={proposta.troca} /> : null}
              {proposta.desconto ? <Linha rotulo="Desconto" valor={proposta.desconto} /> : null}
              <Linha rotulo="Forma" valor={proposta.forma} />
              {proposta.parcela ? <Linha rotulo="Parcelas" valor={proposta.parcela} /> : null}
              <Linha rotulo="Total" valor={proposta.total} />
            </dl>
          </CardContent>
        </Card>
      ) : null}

      {onResetar ? <ResetarConversa ocupado={ocupado} onResetar={onResetar} /> : null}
    </div>
  )
}
