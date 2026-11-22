"use client"

import { useCallback, useEffect, useState, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DataGrid,
  errosDeCelulas,
  type DataGridErrors,
  type DataGridRow,
} from "@/components/ui/data-grid"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"

import { somaPercentuais } from "./conversores"
import { type Cliente, type DefinicaoGrade } from "./grades"
import { ImportarPlanilha } from "./importar-planilha"

function formatarPercentual(n: number): string {
  return String(n).replace(".", ",")
}

function SomaPercentuais({ linhas }: { linhas: DataGridRow[] }) {
  const soma = somaPercentuais(linhas)
  const resta = Math.round((100 - soma) * 100) / 100
  return (
    <p className="text-sm">
      <span className={soma === 100 ? "font-medium text-success" : "font-medium"}>
        Soma: {formatarPercentual(soma)}%
      </span>{" "}
      {resta > 0 ? (
        <span className="text-muted-foreground">faltam {formatarPercentual(resta)}%</span>
      ) : null}
      {resta < 0 ? (
        <span className="text-danger">passou {formatarPercentual(-resta)}%</span>
      ) : null}
    </p>
  )
}

/** Um passo do onboarding em forma de grade editável: carrega, edita, valida e salva. */
export function PassoGrade({
  definicao,
  cliente,
  lojaId,
  aoSalvar,
  mostrarSoma = false,
  acoes,
}: {
  definicao: DefinicaoGrade
  cliente: Cliente
  lojaId: string
  /** Chamado depois de salvar/importar (ex.: atualizar o checklist). */
  aoSalvar: () => void
  mostrarSoma?: boolean
  /** Ações extras do passo (ex.: importar do ERP); recebem `recarregar` para atualizar a grade. */
  acoes?: (recarregar: () => void) => ReactNode
}) {
  const toast = useToast()
  const [linhas, setLinhas] = useState<DataGridRow[] | null>(null)
  const [falhaAoCarregar, setFalhaAoCarregar] = useState<string | null>(null)
  const [erros, setErros] = useState<DataGridErrors>({})
  const [gerais, setGerais] = useState<string[]>([])
  const [salvando, setSalvando] = useState(false)
  const [versao, setVersao] = useState(0)

  useEffect(() => {
    let ativo = true
    definicao
      .carregar(cliente, lojaId)
      .then((dados) => {
        if (!ativo) return
        setLinhas(dados)
        setFalhaAoCarregar(null)
        setErros({})
        setGerais([])
      })
      .catch((e: unknown) => {
        if (ativo) setFalhaAoCarregar(e instanceof Error ? e.message : "Erro ao carregar.")
      })
    return () => {
      ativo = false
    }
  }, [definicao, cliente, lojaId, versao])

  const recarregar = useCallback(() => {
    setVersao((v) => v + 1)
    aoSalvar()
  }, [aoSalvar])

  async function salvar() {
    if (!linhas) return
    const local = definicao.validarLocal?.(linhas) ?? null
    if (local) {
      setErros({})
      setGerais([local])
      return
    }
    setSalvando(true)
    try {
      const r = await definicao.salvar(cliente, lojaId, linhas)
      if (r.ok) {
        setErros({})
        setGerais([])
        toast.sucesso(`${definicao.titulo}: salvo.`)
        aoSalvar()
      } else {
        setErros(errosDeCelulas(r.celulas))
        setGerais(r.gerais)
        toast.erro("Corrija os campos destacados e salve de novo.")
      }
    } catch {
      toast.erro("Não foi possível salvar. Verifique a conexão e tente de novo.")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{definicao.titulo}</CardTitle>
        {definicao.descricao ? <CardDescription>{definicao.descricao}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {definicao.importar ? (
          <ImportarPlanilha
            tipo={definicao.importar}
            lojaId={lojaId}
            cliente={cliente}
            aoAplicar={recarregar}
          />
        ) : null}

        {acoes ? acoes(recarregar) : null}

        {falhaAoCarregar ? (
          <p role="alert" className="text-sm text-danger">
            {falhaAoCarregar}
          </p>
        ) : linhas === null ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : (
          <>
            <DataGrid
              aria-label={definicao.rotuloGrade}
              columns={definicao.colunas}
              rows={linhas}
              pageSize={definicao.porPagina}
              filterable={definicao.porPagina !== undefined}
              errors={erros}
              onChange={({ rowIndex, columnKey, row }) => {
                setLinhas((atual) => atual?.map((l, i) => (i === rowIndex ? row : l)) ?? atual)
                setErros((atual) => {
                  if (!atual[rowIndex]?.[columnKey]) return atual
                  const resto = { ...atual[rowIndex] }
                  delete resto[columnKey]
                  return { ...atual, [rowIndex]: resto }
                })
              }}
              onAddRow={() => setLinhas((atual) => [...(atual ?? []), definicao.linhaVazia()])}
              onRemoveRow={(i) => {
                setLinhas((atual) => atual?.filter((_, j) => j !== i) ?? atual)
                setErros({})
              }}
              addRowLabel={definicao.rotuloAdicionar}
              emptyMessage="Nenhuma linha ainda. Adicione ou importe uma planilha."
            />
            {mostrarSoma ? <SomaPercentuais linhas={linhas} /> : null}
            {gerais.length > 0 ? (
              <div role="alert" className="flex flex-col gap-1 text-sm text-danger">
                {gerais.map((g, i) => (
                  <p key={i}>{g}</p>
                ))}
              </div>
            ) : null}
            <div>
              <Button onClick={() => void salvar()} disabled={salvando}>
                {salvando ? "Salvando…" : "Salvar"}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
