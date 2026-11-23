"use client"

import { BarChart3 } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { PageHeader } from "@/components/ui/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

import { formatarIntervalo } from "./formatar"
import { semDados } from "./indicadores"
import { PERIODOS, PERIODO_PADRAO, intervaloDoPeriodo } from "./periodo"
import { Custo, Demanda, Qualidade, Resultado, VisaoGeral, Volume } from "./secoes"
import { useDesempenho } from "./use-desempenho"

function Carregando() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Carregando desempenho">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  )
}

/**
 * Tela de desempenho da IA para o dono da loja: visão geral, volume, resultado, custo, qualidade
 * e demanda, comparados com o período anterior. `hoje` existe para testes (padrão: agora).
 */
export function Desempenho({ lojaId, hoje }: { lojaId: string; hoje?: Date }) {
  const [agora] = useState(() => hoje ?? new Date())
  const [dias, setDias] = useState<number>(PERIODO_PADRAO)
  const { de, ate } = useMemo(() => intervaloDoPeriodo(dias, agora), [dias, agora])
  const { status, dados, atualizando, recarregar } = useDesempenho(lojaId, de, ate)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Desempenho da IA"
        description="Como a IA está atendendo seus clientes, em comparação com o período anterior."
      />
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div role="group" aria-label="Período" className="flex flex-wrap gap-1.5">
          {PERIODOS.map((p) => (
            <Button
              key={p.dias}
              size="xs"
              variant={p.dias === dias ? "default" : "outline"}
              aria-pressed={p.dias === dias}
              onClick={() => setDias(p.dias)}
            >
              {p.rotulo}
            </Button>
          ))}
        </div>
        <p className="text-sm text-muted-foreground">{formatarIntervalo(de, ate)}</p>
      </div>

      {status === "carregando" ? (
        <Carregando />
      ) : status === "erro" ? (
        <EmptyState
          icon={BarChart3}
          title="Não foi possível carregar o desempenho"
          description="Verifique a conexão e tente de novo."
          action={<Button onClick={recarregar}>Tentar de novo</Button>}
        />
      ) : dados === null ? null : semDados(dados) ? (
        <EmptyState
          icon={BarChart3}
          title="Ainda não há dados neste período"
          description="Os números aparecem conforme a IA atender conversas. Escolha um período maior ou volte depois das primeiras conversas."
        />
      ) : (
        <div
          aria-busy={atualizando}
          className={cn("flex flex-col gap-8 transition-opacity", atualizando && "opacity-60")}
        >
          <VisaoGeral m={dados} />
          <Volume m={dados} />
          <Resultado m={dados} />
          <Custo m={dados} />
          <Qualidade m={dados} />
          <Demanda m={dados} />
        </div>
      )}
    </div>
  )
}
