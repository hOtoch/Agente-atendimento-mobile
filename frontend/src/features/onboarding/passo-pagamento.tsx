"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Campo } from "@/components/ui/campo"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { SeletorCampo } from "@/components/ui/seletor-campo"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"

import { errosPorCampo } from "./formulario"
import type { Cliente } from "./grades"

type Dados = {
  aceita_pix: boolean
  aceita_debito: boolean
  aceita_credito: boolean
  aceita_entrada_mais_credito: boolean
  chave_pix_tipo?: string | null
  chave_pix?: string | null
  chave_pix_favorecido?: string | null
}

type Form = {
  aceita_pix: boolean
  aceita_debito: boolean
  aceita_credito: boolean
  chave_pix_tipo: string
  chave_pix: string
  chave_pix_favorecido: string
}

const SEM_CHAVE = "nenhuma"

const TIPOS_CHAVE = [
  { value: SEM_CHAVE, label: "Não informada" },
  { value: "cpf", label: "CPF" },
  { value: "cnpj", label: "CNPJ" },
  { value: "email", label: "E-mail" },
  { value: "telefone", label: "Telefone" },
  { value: "aleatoria", label: "Chave aleatória" },
]

const DICAS_CHAVE: Record<string, string> = {
  cpf: "11 dígitos, com ou sem pontuação.",
  cnpj: "14 caracteres, com ou sem pontuação.",
  email: "Ex.: pix@loja.com.br.",
  telefone: "Com DDD, ex.: (11) 91234-5678.",
  aleatoria: "Código no formato 8-4-4-4-12 gerado pelo banco.",
}

function paraForm(d: Dados): Form {
  return {
    aceita_pix: d.aceita_pix,
    aceita_debito: d.aceita_debito,
    aceita_credito: d.aceita_credito,
    chave_pix_tipo: d.chave_pix_tipo ?? SEM_CHAVE,
    chave_pix: d.chave_pix ?? "",
    chave_pix_favorecido: d.chave_pix_favorecido ?? "",
  }
}

/** Texto em branco vira `null`: os três campos da chave vazios = sem chave cadastrada. */
function ouNulo(texto: string): string | null {
  return texto.trim() === "" ? null : texto.trim()
}

function paraCorpo(f: Form) {
  return {
    aceita_pix: f.aceita_pix,
    aceita_debito: f.aceita_debito,
    aceita_credito: f.aceita_credito,
    chave_pix_tipo: f.chave_pix_tipo === SEM_CHAVE ? null : f.chave_pix_tipo,
    chave_pix: ouNulo(f.chave_pix),
    chave_pix_favorecido: ouNulo(f.chave_pix_favorecido),
  }
}

export function PassoPagamento({
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
  const [entradaMaisCartao, setEntradaMaisCartao] = useState(false)
  const [erros, setErros] = useState<Record<string, string>>({})
  const [gerais, setGerais] = useState<string[]>([])
  const [falha, setFalha] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    let ativo = true
    cliente
      .GET("/lojas/{loja_id}/config/pagamento", { params: { path: { loja_id: lojaId } } })
      .then(({ data, response }) => {
        if (!ativo) return
        if (!response.ok || !data) {
          setFalha("Não foi possível carregar as formas de pagamento.")
          return
        }
        setForm(paraForm(data))
        setEntradaMaisCartao(data.aceita_entrada_mais_credito)
      })
      .catch(() => ativo && setFalha("Não foi possível carregar as formas de pagamento."))
    return () => {
      ativo = false
    }
  }, [cliente, lojaId])

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
      const { data, response, error } = await cliente.PUT("/lojas/{loja_id}/config/pagamento", {
        params: { path: { loja_id: lojaId } },
        body: paraCorpo(form),
      })
      if (response.ok && data) {
        setForm(paraForm(data))
        setEntradaMaisCartao(data.aceita_entrada_mais_credito)
        setErros({})
        setGerais([])
        toast.sucesso("Formas de pagamento: salvo.")
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

  const pixSemChave =
    form !== null && form.aceita_pix && form.chave_pix.trim() === "" && form.chave_pix_tipo === SEM_CHAVE

  return (
    <Card>
      <CardHeader>
        <CardTitle>Formas de pagamento</CardTitle>
        <CardDescription>
          A IA só oferece as formas ligadas aqui e recusa as demais. A chave Pix fica guardada no
          sistema e só é passada ao cliente quando ele escolhe pagar no Pix.
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
            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1 text-sm font-medium">Formas aceitas</legend>
              <Checkbox
                rotulo="Pix"
                checked={form.aceita_pix}
                onCheckedChange={(v) => alterar("aceita_pix", v)}
              />
              <Checkbox
                rotulo="Débito"
                checked={form.aceita_debito}
                onCheckedChange={(v) => alterar("aceita_debito", v)}
              />
              <Checkbox
                rotulo="Cartão de crédito"
                descricao="Parcelado, até o máximo definido nas regras de preço."
                checked={form.aceita_credito}
                onCheckedChange={(v) => alterar("aceita_credito", v)}
              />
              <p className="text-xs text-muted-foreground">
                Entrada + cartão: {entradaMaisCartao ? "aceita" : "não aceita"} (definido em Regras
                de preço; exige o crédito ligado).
              </p>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Campo label="Tipo da chave" erro={erros.chave_pix_tipo}>
                {(p) => (
                  <SeletorCampo
                    controle={p}
                    valor={form.chave_pix_tipo}
                    itens={TIPOS_CHAVE}
                    aoMudar={(v) => alterar("chave_pix_tipo", v)}
                  />
                )}
              </Campo>
              <Campo
                label="Chave Pix"
                dica={DICAS_CHAVE[form.chave_pix_tipo]}
                erro={erros.chave_pix}
              >
                {(p) => (
                  <Input
                    {...p}
                    className="font-mono"
                    value={form.chave_pix}
                    onChange={(e) => alterar("chave_pix", e.target.value)}
                  />
                )}
              </Campo>
              <Campo
                label="Favorecido"
                dica="Nome de quem recebe o Pix."
                erro={erros.chave_pix_favorecido}
              >
                {(p) => (
                  <Input
                    {...p}
                    value={form.chave_pix_favorecido}
                    onChange={(e) => alterar("chave_pix_favorecido", e.target.value)}
                  />
                )}
              </Campo>
            </div>

            {pixSemChave ? (
              <p className="text-xs text-warning-foreground">
                Cadastre a chave Pix: sem ela a IA não consegue passar os dados do Pix ao cliente.
              </p>
            ) : null}
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
