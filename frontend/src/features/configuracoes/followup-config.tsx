"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Campo, type CampoControle } from "@/components/ui/campo"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"
import { errosPorCampo } from "@/features/onboarding/formulario"
import type { Cliente } from "@/features/onboarding/grades"

import {
  corpoParaForm,
  ETAPAS_FOLLOWUP,
  formParaCorpo,
  validarForm,
  type ChaveEtapa,
  type ErrosFollowup,
  type FormFollowup,
} from "./followup"

const LIGADO = [
  { value: "nao", label: "Desligado" },
  { value: "sim", label: "Ligado" },
]

type CampoSimples = "max_tentativas" | "intervalo_horas" | "hora_inicio" | "hora_fim" | "max_dias_parado"

function SeletorLigado({
  controle,
  valor,
  aoMudar,
}: {
  controle: CampoControle
  valor: string
  aoMudar: (valor: "sim" | "nao") => void
}) {
  return (
    <Select value={valor} items={LIGADO} onValueChange={(v) => aoMudar(v === "sim" ? "sim" : "nao")}>
      <SelectTrigger
        id={controle.id}
        aria-labelledby={controle["aria-labelledby"]}
        aria-describedby={controle["aria-describedby"]}
        className="w-full"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {LIGADO.map((i) => (
          <SelectItem key={i.value} value={i.value}>
            {i.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function FollowupConfig({ cliente, lojaId }: { cliente: Cliente; lojaId: string }) {
  const toast = useToast()
  const [form, setForm] = useState<FormFollowup | null>(null)
  const [erros, setErros] = useState<ErrosFollowup>({})
  const [gerais, setGerais] = useState<string[]>([])
  const [falha, setFalha] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    let ativo = true
    const erroCarga = "Não foi possível carregar a configuração de follow-up."
    cliente
      .GET("/lojas/{loja_id}/config/followup", { params: { path: { loja_id: lojaId } } })
      .then(({ data, response }) => {
        if (!ativo) return
        if (!response.ok || !data) setFalha(erroCarga)
        else setForm(corpoParaForm(data))
      })
      .catch(() => ativo && setFalha(erroCarga))
    return () => {
      ativo = false
    }
  }, [cliente, lojaId])

  function limpar(campo: keyof ErrosFollowup) {
    setErros((atual) => {
      const resto = { ...atual }
      delete resto[campo]
      return resto
    })
  }

  function alterar(campo: CampoSimples, valor: string) {
    setForm((atual) => (atual ? { ...atual, [campo]: valor } : atual))
    limpar(campo)
  }

  function alterarHoras(chave: ChaveEtapa, valor: string) {
    setForm((atual) => (atual ? { ...atual, horas: { ...atual.horas, [chave]: valor } } : atual))
    limpar("horas_por_etapa")
  }

  async function salvar() {
    if (!form) return
    const locais = validarForm(form)
    setErros(locais)
    setGerais([])
    if (Object.keys(locais).length > 0) {
      toast.erro("Corrija os campos destacados e salve de novo.")
      return
    }
    setSalvando(true)
    try {
      const { response, error } = await cliente.PUT("/lojas/{loja_id}/config/followup", {
        params: { path: { loja_id: lojaId } },
        body: formParaCorpo(form),
      })
      if (response.ok) {
        toast.sucesso("Follow-up automático: salvo.")
      } else {
        const r = errosPorCampo(error)
        setErros(r.campos as ErrosFollowup)
        setGerais(r.gerais)
        toast.erro("Corrija os campos destacados e salve de novo.")
      }
    } catch {
      toast.erro("Não foi possível salvar. Verifique a conexão e tente de novo.")
    } finally {
      setSalvando(false)
    }
  }

  const numero = (campo: CampoSimples, rotulo: string, dica?: string, tipo: "number" | "time" = "number") =>
    form ? (
      <Campo label={rotulo} dica={dica} erro={erros[campo]}>
        {(p) => (
          <Input
            {...p}
            type={tipo}
            inputMode={tipo === "number" ? "numeric" : undefined}
            min={tipo === "number" ? 1 : undefined}
            value={form[campo]}
            onChange={(e) => alterar(campo, e.target.value)}
          />
        )}
      </Campo>
    ) : null

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Follow-up automático</h2>
        </CardTitle>
        <CardDescription>
          A IA retoma a conversa com o lead que parou de responder, uma mensagem por vez, só no
          horário comercial. Leads com o vendedor não recebem follow-up da IA.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
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
            <Campo label="Follow-up automático" className="sm:max-w-xs">
              {(p) => (
                <SeletorLigado
                  controle={p}
                  valor={form.ligado}
                  aoMudar={(v) => setForm((atual) => (atual ? { ...atual, ligado: v } : atual))}
                />
              )}
            </Campo>
            <fieldset className="flex flex-col gap-2">
              <legend className="text-sm font-medium">Horas parado até o primeiro follow-up</legend>
              <p className="text-xs text-muted-foreground">
                Deixe vazio para não fazer follow-up naquela etapa.
              </p>
              <div className="grid gap-4 sm:grid-cols-3">
                {ETAPAS_FOLLOWUP.map(({ chave, rotulo }) => (
                  <Campo key={chave} label={`${rotulo} (horas)`}>
                    {(p) => (
                      <Input
                        {...p}
                        type="number"
                        inputMode="numeric"
                        min={1}
                        aria-invalid={erros.horas_por_etapa ? true : undefined}
                        value={form.horas[chave]}
                        onChange={(e) => alterarHoras(chave, e.target.value)}
                      />
                    )}
                  </Campo>
                ))}
              </div>
              {erros.horas_por_etapa ? (
                <p className="text-xs text-danger">{erros.horas_por_etapa}</p>
              ) : null}
            </fieldset>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {numero("max_tentativas", "Máximo de tentativas", "De 1 a 5 por lead.")}
              {numero("intervalo_horas", "Intervalo entre tentativas (horas)")}
              {numero("max_dias_parado", "Parar após (dias parado)", "Lead mais antigo que isso não recebe.")}
              {numero("hora_inicio", "Início do horário comercial", "Horário de Brasília.", "time")}
              {numero("hora_fim", "Fim do horário comercial", undefined, "time")}
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
