"use client"

import { Check } from "lucide-react"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

import {
  GRADE_ESTOQUE,
  GRADE_MAPEAMENTO,
  GRADE_TAXAS,
  GRADE_TROCA,
  GRADE_VENDEDORES,
  type Cliente,
} from "./grades"
import { ImportarVendedoresErp } from "./importar-vendedores-erp"
import { PassoGrade } from "./passo-grade"
import { PassoPagamento } from "./passo-pagamento"
import { PassoPerfil } from "./passo-perfil"
import { PassoPreco } from "./passo-preco"
import { PassoWhatsapp } from "./passo-whatsapp"
import {
  PASSOS,
  passoCompleto,
  passoPorId,
  primeiroPendente,
  type ItemChecklist,
  type Passo,
} from "./passos"

async function buscarChecklist(cliente: Cliente, lojaId: string): Promise<ItemChecklist[] | null> {
  try {
    const { data, response } = await cliente.GET("/lojas/{loja_id}/onboarding/checklist", {
      params: { path: { loja_id: lojaId } },
    })
    return response.ok && data ? data.itens : null
  } catch {
    return null
  }
}

function useChecklist(cliente: Cliente, lojaId: string) {
  const [itens, setItens] = useState<ItemChecklist[] | null>(null)
  const [falha, setFalha] = useState(false)
  const [versao, setVersao] = useState(0)

  useEffect(() => {
    let ativo = true
    void buscarChecklist(cliente, lojaId).then((resultado) => {
      if (!ativo) return
      if (resultado) setItens(resultado)
      setFalha(resultado === null)
    })
    return () => {
      ativo = false
    }
  }, [cliente, lojaId, versao])

  const atualizar = useCallback(() => setVersao((v) => v + 1), [])
  return { itens, falha, atualizar }
}

function ConteudoDoPasso({
  passo,
  cliente,
  lojaId,
  aoSalvar,
}: {
  passo: Passo
  cliente: Cliente
  lojaId: string
  aoSalvar: () => void
}) {
  switch (passo.id) {
    case "perfil":
      return <PassoPerfil cliente={cliente} lojaId={lojaId} aoSalvar={aoSalvar} />
    case "vendedores":
      return (
        <PassoGrade
          definicao={GRADE_VENDEDORES}
          cliente={cliente}
          lojaId={lojaId}
          aoSalvar={aoSalvar}
          mostrarSoma
          acoes={(recarregar) => (
            <ImportarVendedoresErp cliente={cliente} lojaId={lojaId} aoImportar={recarregar} />
          )}
        />
      )
    case "preco":
      return <PassoPreco cliente={cliente} lojaId={lojaId} aoSalvar={aoSalvar} />
    case "pagamento":
      return <PassoPagamento cliente={cliente} lojaId={lojaId} aoSalvar={aoSalvar} />
    case "taxas":
      return <PassoGrade definicao={GRADE_TAXAS} cliente={cliente} lojaId={lojaId} aoSalvar={aoSalvar} />
    case "troca":
      return <PassoGrade definicao={GRADE_TROCA} cliente={cliente} lojaId={lojaId} aoSalvar={aoSalvar} />
    case "estoque":
      return (
        <div className="flex flex-col gap-6">
          <PassoGrade definicao={GRADE_ESTOQUE} cliente={cliente} lojaId={lojaId} aoSalvar={aoSalvar} />
          <PassoGrade
            definicao={GRADE_MAPEAMENTO}
            cliente={cliente}
            lojaId={lojaId}
            aoSalvar={aoSalvar}
          />
        </div>
      )
    case "whatsapp":
      return <PassoWhatsapp cliente={cliente} lojaId={lojaId} />
    case "teste":
      return (
        <Card>
          <CardHeader>
            <CardTitle>Conversa de teste</CardTitle>
            <CardDescription>
              Converse como cliente e confira preço, troca e tom antes de ligar o WhatsApp.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/simulador" className={cn(buttonVariants())}>
              Abrir o simulador
            </Link>
          </CardContent>
        </Card>
      )
  }
}

/** Assistente de onboarding: passos com grades editáveis, importar planilha e checklist da API. */
export function Onboarding({ lojaId, cliente = api }: { lojaId: string; cliente?: Cliente }) {
  const pathname = usePathname()
  const passoDaUrl = passoPorId(useSearchParams().get("passo"))
  const { itens, falha, atualizar } = useChecklist(cliente, lojaId)

  const passo = passoDaUrl ?? (itens ? primeiroPendente(itens) : falha ? PASSOS[0] : null)
  const concluidos = itens?.filter((i) => i.completo).length ?? 0
  const total = itens?.length ?? 0
  const itensDoPasso = passo && itens ? itens.filter((i) => passo.chaves.includes(i.chave)) : []

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
      <aside className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          {itens ? (
            <>
              <p className="text-sm font-medium">
                {concluidos} de {total} itens concluídos
              </p>
              <div
                role="progressbar"
                aria-label="Progresso do onboarding"
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={concluidos}
                className="h-2 overflow-hidden rounded-full bg-muted"
              >
                <div
                  className="h-full bg-primary"
                  style={{ width: `${total ? (concluidos / total) * 100 : 0}%` }}
                />
              </div>
            </>
          ) : falha ? (
            <p role="alert" className="text-sm text-danger">
              Não foi possível carregar o progresso.
            </p>
          ) : (
            <Skeleton className="h-8 w-full" />
          )}
        </div>
        <nav aria-label="Passos do onboarding">
          <ol className="flex flex-col gap-1">
            {PASSOS.map((p, i) => {
              const completo = itens ? passoCompleto(p, itens) : null
              const atual = passo?.id === p.id
              return (
                <li key={p.id}>
                  <Link
                    href={`${pathname}?passo=${p.id}`}
                    aria-current={atual ? "step" : undefined}
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      atual ? "bg-accent font-medium text-accent-foreground" : "hover:bg-muted",
                    )}
                  >
                    <span>
                      <span className="mr-2 text-muted-foreground">{i + 1}.</span>
                      {p.titulo}
                    </span>
                    {completo === true ? (
                      <Badge variant="success">
                        <Check aria-hidden="true" />
                        Concluído
                      </Badge>
                    ) : completo === false ? (
                      <Badge variant="warning">Pendente</Badge>
                    ) : null}
                  </Link>
                </li>
              )
            })}
          </ol>
        </nav>
      </aside>

      <section aria-label="Passo atual" className="flex min-w-0 flex-col gap-4">
        {passo ? (
          <>
            <div>
              <h2 className="text-lg font-semibold">{passo.titulo}</h2>
              <p className="text-sm text-muted-foreground">{passo.descricao}</p>
              {itensDoPasso.map((i) => (
                <p
                  key={i.chave}
                  className={cn("mt-1 text-xs", i.completo ? "text-success" : "text-warning-foreground")}
                >
                  {i.rotulo_ptbr}: {i.detalhe}
                </p>
              ))}
            </div>
            <ConteudoDoPasso
              key={passo.id}
              passo={passo}
              cliente={cliente}
              lojaId={lojaId}
              aoSalvar={atualizar}
            />
          </>
        ) : (
          <Skeleton className="h-40 w-full" />
        )}
      </section>
    </div>
  )
}
