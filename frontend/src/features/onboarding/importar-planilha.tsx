"use client"

import { FileSpreadsheet } from "lucide-react"
import { useRef, useState } from "react"

import { Button, buttonVariants } from "@/components/ui/button"
import { useToast } from "@/components/ui/toast"
import { URL_API, mensagemDeErro } from "@/lib/api"
import { cn } from "@/lib/utils"

import { descreverErroImportacao, type ErroApi } from "./erros"
import { errosDoCorpo, type Cliente, type TipoImportacao } from "./grades"

type Relatorio = { ok: boolean; erros: ErroApi[]; resumo: Record<string, unknown> }

export function resumirImportacao(tipo: TipoImportacao, resumo: Record<string, unknown>): string {
  const n = (chave: string) => Number(resumo[chave] ?? 0)
  if (tipo === "troca") {
    return `${n("linhas")} linhas (${n("apple")} Apple, ${n("outras_marcas")} outras marcas)`
  }
  if (tipo === "estoque") return `${n("linhas")} linhas, ${n("unidades")} unidades`
  return `${n("taxas")} taxas e as regras de preço`
}

async function enviar(
  cliente: Cliente,
  lojaId: string,
  tipo: TipoImportacao,
  arquivo: File,
  modo: "validar" | "aplicar",
): Promise<Relatorio> {
  const corpo = new FormData()
  corpo.append("arquivo", arquivo)
  const { data, error } = await cliente.POST("/lojas/{loja_id}/importar/{tipo}", {
    params: { path: { loja_id: lojaId, tipo }, query: { modo } },
    body: { arquivo: "" },
    bodySerializer: () => corpo,
  })
  if (data) return data
  const erros = errosDoCorpo(error)
  if (erros) {
    const resumo = (error as { resumo?: Record<string, unknown> }).resumo ?? {}
    return { ok: false, erros, resumo }
  }
  return { ok: false, erros: [{ caminho: "", mensagem: mensagemDeErro(error) }], resumo: {} }
}

/**
 * "Importar planilha": valida o .xlsx (nada é gravado) e mostra os erros por célula;
 * só com a planilha válida o usuário pode aplicar.
 */
export function ImportarPlanilha({
  tipo,
  lojaId,
  cliente,
  aoAplicar,
}: {
  tipo: TipoImportacao
  lojaId: string
  cliente: Cliente
  aoAplicar: () => void
}) {
  const toast = useToast()
  const entrada = useRef<HTMLInputElement>(null)
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [relatorio, setRelatorio] = useState<Relatorio | null>(null)
  const [ocupado, setOcupado] = useState(false)

  function fechar() {
    setArquivo(null)
    setRelatorio(null)
  }

  async function executar(modo: "validar" | "aplicar", alvo: File) {
    setOcupado(true)
    try {
      const r = await enviar(cliente, lojaId, tipo, alvo, modo)
      if (modo === "aplicar" && r.ok) {
        toast.sucesso("Planilha importada.")
        fechar()
        aoAplicar()
        return
      }
      setRelatorio(r)
    } catch {
      toast.erro("Não foi possível enviar a planilha. Tente de novo.")
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div data-slot="importar-planilha" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={entrada}
          type="file"
          accept=".xlsx"
          aria-label="Arquivo da planilha"
          className="sr-only"
          onChange={(e) => {
            const escolhido = e.target.files?.[0]
            e.target.value = ""
            if (!escolhido) return
            setArquivo(escolhido)
            setRelatorio(null)
            void executar("validar", escolhido)
          }}
        />
        <Button
          variant="outline"
          size="sm"
          disabled={ocupado}
          onClick={() => entrada.current?.click()}
        >
          <FileSpreadsheet aria-hidden="true" data-icon="inline-start" />
          Importar planilha
        </Button>
        <a
          href={`${URL_API}/modelos/${tipo}`}
          download
          className={cn(buttonVariants({ variant: "link", size: "sm" }))}
        >
          Baixar modelo
        </a>
      </div>

      {arquivo && ocupado && !relatorio ? (
        <p role="status" className="text-sm text-muted-foreground">
          Validando {arquivo.name}…
        </p>
      ) : null}

      {arquivo && relatorio ? (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 text-sm">
          {relatorio.ok ? (
            <>
              <p className="font-medium">Planilha válida</p>
              <p className="text-muted-foreground">
                {resumirImportacao(tipo, relatorio.resumo)}. Ao aplicar, o conteúdo atual deste
                passo é substituído.
              </p>
              <div className="flex gap-2">
                <Button size="sm" disabled={ocupado} onClick={() => void executar("aplicar", arquivo)}>
                  Aplicar importação
                </Button>
                <Button size="sm" variant="ghost" disabled={ocupado} onClick={fechar}>
                  Cancelar
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="font-medium text-danger">
                {relatorio.erros.length === 1
                  ? "1 erro na planilha"
                  : `${relatorio.erros.length} erros na planilha`}
                . Corrija o arquivo e importe de novo; nada foi gravado.
              </p>
              <ul aria-label="Erros da planilha" className="flex list-disc flex-col gap-1 pl-5">
                {relatorio.erros.map((e, i) => (
                  <li key={i}>{descreverErroImportacao(e)}</li>
                ))}
              </ul>
              <div>
                <Button size="sm" variant="ghost" onClick={fechar}>
                  Fechar
                </Button>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
