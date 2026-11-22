"use client"

import { CloudDownload } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/toast"
import { mensagemDeErro } from "@/lib/api"

import type { Cliente } from "./grades"

export type ResumoImportacaoVendedores = {
  criados: number
  atualizados: number
  desativados: number
  sem_alteracao: number
}

function contar(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`
}

export function resumirImportacaoVendedores(r: ResumoImportacaoVendedores): string {
  if (r.criados === 0 && r.atualizados === 0 && r.desativados === 0) {
    return "Nenhuma mudança: os vendedores já estão em dia com o ERP."
  }
  return `${contar(r.criados, "criado", "criados")}, ${contar(r.atualizados, "atualizado", "atualizados")}, ${contar(r.desativados, "desativado", "desativados")}.`
}

type Resultado = { tipo: "ok"; resumo: ResumoImportacaoVendedores } | { tipo: "erro"; mensagem: string }

/**
 * "Importar do ERP": traz os vendedores ativos do Mercado Phone. Telefone e percentual
 * continuam sendo editados aqui; quem entra novo começa com 0% (fora da distribuição).
 */
export function ImportarVendedoresErp({
  cliente,
  lojaId,
  aoImportar,
}: {
  cliente: Cliente
  lojaId: string
  /** Chamado depois de importar (recarrega a grade e o checklist). */
  aoImportar: () => void
}) {
  const toast = useToast()
  const [ocupado, setOcupado] = useState(false)
  const [resultado, setResultado] = useState<Resultado | null>(null)

  async function importar() {
    setOcupado(true)
    setResultado(null)
    try {
      const { data, error } = await cliente.POST("/lojas/{loja_id}/vendedores/importar-erp", {
        params: { path: { loja_id: lojaId } },
      })
      if (data) {
        setResultado({ tipo: "ok", resumo: data })
        toast.sucesso("Vendedores importados do ERP.")
        aoImportar()
        return
      }
      const mensagem = mensagemDeErro(error)
      setResultado({
        tipo: "erro",
        mensagem: mensagem === "Erro inesperado." ? "Não foi possível importar os vendedores do ERP." : mensagem,
      })
    } catch {
      setResultado({
        tipo: "erro",
        mensagem: "Não foi possível importar do ERP. Verifique a conexão e tente de novo.",
      })
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div data-slot="importar-vendedores-erp" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" disabled={ocupado} onClick={() => void importar()}>
          <CloudDownload aria-hidden="true" data-icon="inline-start" />
          {ocupado ? "Importando…" : "Importar do ERP"}
        </Button>
        <span className="text-xs text-muted-foreground">
          Recarrega a lista: salve antes as edições pendentes.
        </span>
      </div>
      {resultado?.tipo === "ok" ? (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p>{resumirImportacaoVendedores(resultado.resumo)}</p>
          {resultado.resumo.criados > 0 ? (
            <p className="text-muted-foreground">
              Vendedores novos entram com 0%: defina o percentual de cada um e salve.
            </p>
          ) : null}
        </div>
      ) : null}
      {resultado?.tipo === "erro" ? (
        <p role="alert" className="text-sm text-danger">
          {resultado.mensagem}
        </p>
      ) : null}
    </div>
  )
}
