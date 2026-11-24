"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Campo } from "@/components/ui/campo"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { SeletorCampo } from "@/components/ui/seletor-campo"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"

import { parseNumero } from "./conversores"
import { errosPorCampo } from "./formulario"
import { type Cliente } from "./grades"
import { ImportarPlanilha } from "./importar-planilha"

type Form = {
  max_parcelas: string
  repassa_taxa: "sim" | "nao"
  desconto_pix_tipo: "nenhum" | "percentual" | "valor"
  desconto_pix_valor: string
  aceita_entrada_mais_cartao: "sim" | "nao"
  desconto_teto: string
  desconto_degrau: string
  oportunidade_ativa: "sim" | "nao"
  oportunidade_dias_minimos: string
  oportunidade_valor: string
}

const PADRAO: Form = {
  max_parcelas: "12",
  repassa_taxa: "sim",
  desconto_pix_tipo: "nenhum",
  desconto_pix_valor: "",
  aceita_entrada_mais_cartao: "sim",
  desconto_teto: "0",
  desconto_degrau: "50",
  oportunidade_ativa: "nao",
  oportunidade_dias_minimos: "0",
  oportunidade_valor: "0",
}

const AJUDA_ESCADA =
  "A IA libera o degrau a cada pedido do cliente até o teto. Se ele pedir mais que o teto, ou brinde/benefício, o atendimento vai para o vendedor com um resumo."

const SIM_NAO = [
  { value: "sim", label: "Sim" },
  { value: "nao", label: "Não" },
]
const TIPOS_PIX = [
  { value: "nenhum", label: "Sem desconto" },
  { value: "percentual", label: "Percentual (%)" },
  { value: "valor", label: "Valor (R$)" },
]

function numeroTexto(valor: string | number | null | undefined): string {
  return valor === null || valor === undefined ? "" : String(Number(valor)).replace(".", ",")
}

function paraForm(d: {
  max_parcelas: number
  repassa_taxa: boolean
  desconto_pix_tipo: string
  desconto_pix_valor?: string | null
  aceita_entrada_mais_cartao: boolean
  desconto_teto: string
  desconto_degrau: string
  oportunidade_ativa: boolean
  oportunidade_dias_minimos: number
  oportunidade_valor: string
}): Form {
  return {
    max_parcelas: String(d.max_parcelas),
    repassa_taxa: d.repassa_taxa ? "sim" : "nao",
    desconto_pix_tipo: d.desconto_pix_tipo as Form["desconto_pix_tipo"],
    desconto_pix_valor: numeroTexto(d.desconto_pix_valor),
    aceita_entrada_mais_cartao: d.aceita_entrada_mais_cartao ? "sim" : "nao",
    desconto_teto: numeroTexto(d.desconto_teto),
    desconto_degrau: numeroTexto(d.desconto_degrau),
    oportunidade_ativa: d.oportunidade_ativa ? "sim" : "nao",
    oportunidade_dias_minimos: String(d.oportunidade_dias_minimos),
    oportunidade_valor: numeroTexto(d.oportunidade_valor),
  }
}

/** Número quando dá; texto cru caso contrário (a API aponta o erro no campo). */
function envio(texto: string): number | string {
  return parseNumero(texto) ?? texto.trim()
}

function paraCorpo(f: Form) {
  return {
    max_parcelas: envio(f.max_parcelas) as number,
    repassa_taxa: f.repassa_taxa === "sim",
    desconto_pix_tipo: f.desconto_pix_tipo,
    desconto_pix_valor: f.desconto_pix_tipo === "nenhum" ? null : envio(f.desconto_pix_valor),
    aceita_entrada_mais_cartao: f.aceita_entrada_mais_cartao === "sim",
    desconto_teto: envio(f.desconto_teto),
    desconto_degrau: envio(f.desconto_degrau),
    oportunidade_ativa: f.oportunidade_ativa === "sim",
    oportunidade_dias_minimos: envio(f.oportunidade_dias_minimos) as number,
    oportunidade_valor: envio(f.oportunidade_valor),
    oportunidade_conta_no_teto: false,
  }
}

export function PassoPreco({
  cliente,
  lojaId,
  aoSalvar,
}: {
  cliente: Cliente
  lojaId: string
  aoSalvar: () => void
}) {
  const toast = useToast()
  const [form, setForm] = useState<Form | null>(null)
  const [erros, setErros] = useState<Record<string, string>>({})
  const [gerais, setGerais] = useState<string[]>([])
  const [falha, setFalha] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [versao, setVersao] = useState(0)

  useEffect(() => {
    let ativo = true
    cliente
      .GET("/lojas/{loja_id}/config/preco", { params: { path: { loja_id: lojaId } } })
      .then(({ data, response }) => {
        if (!ativo) return
        if (!response.ok) {
          setFalha("Não foi possível carregar as regras de preço.")
          return
        }
        setForm(data ? paraForm(data) : PADRAO)
        setErros({})
      })
      .catch(() => ativo && setFalha("Não foi possível carregar as regras de preço."))
    return () => {
      ativo = false
    }
  }, [cliente, lojaId, versao])

  function alterar<K extends keyof Form>(campo: K, valor: Form[K]) {
    setForm((atual) => (atual ? { ...atual, [campo]: valor } : atual))
    setErros((atual) => {
      if (!(campo in atual)) return atual
      const resto = { ...atual }
      delete resto[campo]
      return resto
    })
  }

  async function salvar() {
    if (!form) return
    setSalvando(true)
    try {
      const { response, error } = await cliente.PUT("/lojas/{loja_id}/config/preco", {
        params: { path: { loja_id: lojaId } },
        body: paraCorpo(form),
      })
      if (response.ok) {
        setErros({})
        setGerais([])
        toast.sucesso("Regras de preço: salvo.")
        aoSalvar()
      } else {
        const r = errosPorCampo(error)
        setErros(r.campos)
        setGerais(r.gerais)
        toast.erro("Corrija os campos destacados e salve de novo.")
      }
    } catch {
      toast.erro("Não foi possível salvar. Verifique a conexão e tente de novo.")
    } finally {
      setSalvando(false)
    }
  }

  const texto = (campo: keyof Form, rotulo: string, extra?: { dica?: string; inteiro?: boolean }) =>
    form ? (
      <Campo label={rotulo} dica={extra?.dica} erro={erros[campo]}>
        {(p) => (
          <Input
            {...p}
            inputMode={extra?.inteiro ? "numeric" : "decimal"}
            className="text-right font-mono"
            value={form[campo]}
            onChange={(e) => alterar(campo, e.target.value as never)}
          />
        )}
      </Campo>
    ) : null

  const seletor = (
    campo: "repassa_taxa" | "aceita_entrada_mais_cartao" | "oportunidade_ativa",
    rotulo: string,
    dica?: string,
  ) =>
    form ? (
      <Campo label={rotulo} dica={dica} erro={erros[campo]}>
        {(p) => (
          <SeletorCampo
            controle={p}
            valor={form[campo]}
            itens={SIM_NAO}
            aoMudar={(v) => alterar(campo, v as "sim" | "nao")}
          />
        )}
      </Campo>
    ) : null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Regras de preço</CardTitle>
        <CardDescription>
          Parcelamento, desconto à vista e limite de desconto que o atendimento pode oferecer.
          Quem decide é o sistema, não a IA.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ImportarPlanilha
          tipo="taxas"
          lojaId={lojaId}
          cliente={cliente}
          aoAplicar={() => {
            setVersao((v) => v + 1)
            aoSalvar()
          }}
        />
        {falha ? (
          <p role="alert" className="text-sm text-danger">
            {falha}
          </p>
        ) : form === null ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {texto("max_parcelas", "Máximo de parcelas no cartão", { inteiro: true })}
              {seletor("repassa_taxa", "Repassa a taxa da maquininha ao cliente?")}
              {seletor("aceita_entrada_mais_cartao", "Aceita entrada + cartão?")}
              <Campo label="Desconto Pix/dinheiro" erro={erros.desconto_pix_tipo}>
                {(p) => (
                  <SeletorCampo
                    controle={p}
                    valor={form.desconto_pix_tipo}
                    itens={TIPOS_PIX}
                    aoMudar={(v) => alterar("desconto_pix_tipo", v as Form["desconto_pix_tipo"])}
                  />
                )}
              </Campo>
              {form.desconto_pix_tipo !== "nenhum"
                ? texto(
                    "desconto_pix_valor",
                    form.desconto_pix_tipo === "percentual" ? "Desconto Pix (%)" : "Desconto Pix (R$)",
                  )
                : null}
              {texto("desconto_degrau", "Desconto por pedido (degrau)")}
              {texto("desconto_teto", "Desconto máximo (teto)")}
              <p className="text-xs text-muted-foreground sm:col-span-2 lg:col-span-3">{AJUDA_ESCADA}</p>
              {seletor("oportunidade_ativa", "Oportunidade única ativa?")}
              {form.oportunidade_ativa === "sim"
                ? texto("oportunidade_dias_minimos", "Oportunidade: dias mínimos até a compra", {
                    inteiro: true,
                  })
                : null}
              {form.oportunidade_ativa === "sim"
                ? texto("oportunidade_valor", "Oportunidade: valor (R$)")
                : null}
            </div>
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
