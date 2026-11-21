"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Campo } from "@/components/ui/campo"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { DataGrid, type DataGridRow } from "@/components/ui/data-grid"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/toast"

import { COLUNAS_HORARIOS } from "./colunas"
import { errosPorCampo } from "./formulario"
import type { Cliente } from "./grades"

type Perfil = {
  nome_exibicao: string
  tom_de_voz: string
  endereco: string
  whatsapp_contato: string
  responder_em_audio: boolean
}

const VAZIO: Perfil = {
  nome_exibicao: "",
  tom_de_voz: "",
  endereco: "",
  whatsapp_contato: "",
  responder_em_audio: true,
}

const DIAS_PADRAO = ["Segunda a sexta", "Sábado", "Domingo e feriados"]

function horariosParaLinhas(horarios: Record<string, string>): DataGridRow[] {
  const existentes = Object.entries(horarios).map(([dia, horario]) => ({ dia, horario }))
  return existentes.length > 0
    ? existentes
    : DIAS_PADRAO.map((dia) => ({ dia, horario: "" }))
}

function linhasParaHorarios(linhas: DataGridRow[]): Record<string, string> {
  const horarios: Record<string, string> = {}
  for (const l of linhas) {
    const dia = String(l.dia ?? "").trim()
    const horario = String(l.horario ?? "").trim()
    if (dia && horario) horarios[dia] = horario
  }
  return horarios
}

export function PassoPerfil({
  cliente,
  lojaId,
  aoSalvar,
}: {
  cliente: Cliente
  lojaId: string
  aoSalvar: () => void
}) {
  const toast = useToast()
  const [perfil, setPerfil] = useState<Perfil | null>(null)
  const [horarios, setHorarios] = useState<DataGridRow[]>([])
  const [erros, setErros] = useState<Record<string, string>>({})
  const [gerais, setGerais] = useState<string[]>([])
  const [falha, setFalha] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    let ativo = true
    cliente
      .GET("/lojas/{loja_id}/config/perfil", { params: { path: { loja_id: lojaId } } })
      .then(({ data, response }) => {
        if (!ativo) return
        if (!response.ok) {
          setFalha("Não foi possível carregar os dados da loja.")
          return
        }
        setPerfil(data ? { ...VAZIO, ...data } : VAZIO)
        setHorarios(horariosParaLinhas(data?.horarios ?? {}))
      })
      .catch(() => ativo && setFalha("Não foi possível carregar os dados da loja."))
    return () => {
      ativo = false
    }
  }, [cliente, lojaId])

  function alterar<K extends keyof Perfil>(campo: K, valor: Perfil[K]) {
    setPerfil((atual) => (atual ? { ...atual, [campo]: valor } : atual))
    setErros((atual) => {
      const resto = { ...atual }
      delete resto[campo]
      return resto
    })
  }

  async function salvar() {
    if (!perfil) return
    setSalvando(true)
    try {
      const { response, error } = await cliente.PUT("/lojas/{loja_id}/config/perfil", {
        params: { path: { loja_id: lojaId } },
        body: { ...perfil, horarios: linhasParaHorarios(horarios) },
      })
      if (response.ok) {
        setErros({})
        setGerais([])
        toast.sucesso("Dados da loja: salvo.")
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>Dados da loja e tom de voz</CardTitle>
        <CardDescription>
          Como a loja aparece para o cliente e como o atendimento deve soar.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {falha ? (
          <p role="alert" className="text-sm text-danger">
            {falha}
          </p>
        ) : perfil === null ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Campo label="Nome da loja" erro={erros.nome_exibicao}>
                {(p) => (
                  <Input
                    {...p}
                    value={perfil.nome_exibicao}
                    onChange={(e) => alterar("nome_exibicao", e.target.value)}
                  />
                )}
              </Campo>
              <Campo
                label="WhatsApp de contato"
                dica="Com DDD, de 10 a 15 dígitos."
                erro={erros.whatsapp_contato}
              >
                {(p) => (
                  <Input
                    {...p}
                    inputMode="tel"
                    value={perfil.whatsapp_contato}
                    onChange={(e) => alterar("whatsapp_contato", e.target.value)}
                  />
                )}
              </Campo>
              <Campo label="Endereço" erro={erros.endereco} className="sm:col-span-2">
                {(p) => (
                  <Input
                    {...p}
                    value={perfil.endereco}
                    onChange={(e) => alterar("endereco", e.target.value)}
                  />
                )}
              </Campo>
              <Campo
                label="Tom de voz"
                dica="Ex.: simpático e direto, sem gírias."
                erro={erros.tom_de_voz}
                className="sm:col-span-2"
              >
                {(p) => (
                  <Textarea
                    {...p}
                    value={perfil.tom_de_voz}
                    onChange={(e) => alterar("tom_de_voz", e.target.value)}
                  />
                )}
              </Campo>
              <div className="sm:col-span-2">
                <Checkbox
                  rotulo="Responder em áudio quando o cliente mandar áudio"
                  descricao="A resposta em texto sempre vai junto, com preços e valores."
                  checked={perfil.responder_em_audio}
                  onCheckedChange={(marcado) => alterar("responder_em_audio", marcado)}
                />
              </div>
            </div>
            <DataGrid
              aria-label="Horários de funcionamento"
              columns={COLUNAS_HORARIOS}
              rows={horarios}
              onChange={({ rowIndex, row }) =>
                setHorarios((atual) => atual.map((l, i) => (i === rowIndex ? row : l)))
              }
              onAddRow={() => setHorarios((atual) => [...atual, { dia: "", horario: "" }])}
              onRemoveRow={(i) => setHorarios((atual) => atual.filter((_, j) => j !== i))}
              addRowLabel="Adicionar horário"
            />
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
