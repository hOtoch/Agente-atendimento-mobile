"use client"

import { useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Campo } from "@/components/ui/campo"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"
import { errosPorCampo } from "@/features/onboarding/formulario"
import { errosDoCorpo, type Cliente } from "@/features/onboarding/grades"

import {
  corpoParaForm,
  formatarData,
  formatarRelatorio,
  formParaCorpo,
  INTERVALO_MAXIMO,
  INTERVALO_MINIMO,
  rotuloStatus,
  validarForm,
  variantStatus,
  type ConexaoErp,
  type ErrosErp,
  type FormErp,
  type TesteConexaoErp,
} from "./erp"

function mensagemDaApi(error: unknown, padrao: string): string {
  const mensagens = errosDoCorpo(error)?.map((e) => e.mensagem)
  return mensagens && mensagens.length > 0 ? mensagens.join(" ") : padrao
}

type CampoTexto = "system_unit_id" | "filtro_loja" | "intervalo_min"

function StatusSincronizacao({ conexao }: { conexao: ConexaoErp }) {
  const { linhas, erro } = formatarRelatorio(conexao.ultimo_relatorio)
  return (
    <section aria-label="Última sincronização" className="flex flex-col gap-2 rounded-lg border p-3">
      <h3 className="text-sm font-medium">Última sincronização</h3>
      {conexao.ultima_sincronizacao_em ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {conexao.ultimo_status ? (
            <Badge variant={variantStatus(conexao.ultimo_status)}>{rotuloStatus(conexao.ultimo_status)}</Badge>
          ) : null}
          <span className="text-muted-foreground">em {formatarData(conexao.ultima_sincronizacao_em)}</span>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Ainda não sincronizou.</p>
      )}
      {erro ? (
        <p className="text-sm text-danger">
          {erro}
          {conexao.ultimo_status === "erro" ? " O estoque anterior foi mantido." : null}
        </p>
      ) : null}
      {linhas.length > 0 ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {linhas.map((l) => (
            <div key={`${l.nivel}-${l.rotulo}`} className="contents">
              <dt className={l.nivel === 1 ? "pl-4 text-muted-foreground" : "text-muted-foreground"}>{l.rotulo}</dt>
              <dd className="font-mono">{l.valor}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  )
}

export function ErpConfig({ cliente, lojaId }: { cliente: Cliente; lojaId: string }) {
  const toast = useToast()
  const [conexao, setConexao] = useState<ConexaoErp | null>(null)
  const [form, setForm] = useState<FormErp | null>(null)
  const [erros, setErros] = useState<ErrosErp>({})
  const [gerais, setGerais] = useState<string[]>([])
  const [falha, setFalha] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [testando, setTestando] = useState(false)
  const [sincronizando, setSincronizando] = useState(false)
  const [teste, setTeste] = useState<TesteConexaoErp | null>(null)
  const [erroAcao, setErroAcao] = useState<string | null>(null)

  useEffect(() => {
    let ativo = true
    const erroCarga = "Não foi possível carregar a conexão com o ERP."
    cliente
      .GET("/lojas/{loja_id}/config/erp", { params: { path: { loja_id: lojaId } } })
      .then(({ data, response }) => {
        if (!ativo) return
        if (!response.ok || !data) {
          setFalha(erroCarga)
        } else {
          setConexao(data)
          setForm(corpoParaForm(data))
        }
      })
      .catch(() => ativo && setFalha(erroCarga))
    return () => {
      ativo = false
    }
  }, [cliente, lojaId])

  function alterar(campo: CampoTexto, valor: string) {
    setForm((atual) => (atual ? { ...atual, [campo]: valor } : atual))
    setErros((atual) => {
      const resto = { ...atual }
      delete resto[campo]
      return resto
    })
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
      const { data, response, error } = await cliente.PUT("/lojas/{loja_id}/config/erp", {
        params: { path: { loja_id: lojaId } },
        body: formParaCorpo(form),
      })
      if (response.ok && data) {
        setConexao(data)
        toast.sucesso("Conexão com o ERP: salva.")
      } else {
        const r = errosPorCampo(error)
        setErros(r.campos as ErrosErp)
        setGerais(r.gerais)
        toast.erro("Corrija os campos destacados e salve de novo.")
      }
    } catch {
      toast.erro("Não foi possível salvar. Verifique a conexão e tente de novo.")
    } finally {
      setSalvando(false)
    }
  }

  async function testar() {
    setTestando(true)
    setTeste(null)
    setErroAcao(null)
    try {
      const { data, response, error } = await cliente.POST("/lojas/{loja_id}/config/erp/testar", {
        params: { path: { loja_id: lojaId } },
      })
      if (response.ok && data) setTeste(data)
      else setErroAcao(mensagemDaApi(error, "Não foi possível testar a conexão."))
    } catch {
      setErroAcao("Não foi possível testar a conexão. Verifique a rede e tente de novo.")
    } finally {
      setTestando(false)
    }
  }

  async function sincronizar() {
    setSincronizando(true)
    setTeste(null)
    setErroAcao(null)
    try {
      const { data, response, error } = await cliente.POST("/lojas/{loja_id}/config/erp/sincronizar", {
        params: { path: { loja_id: lojaId } },
      })
      if (response.ok && data) {
        setConexao(data)
        if (data.ultimo_status === "ok") toast.sucesso("Estoque sincronizado com o ERP.")
        else toast.erro("A sincronização falhou. O estoque anterior foi mantido.")
      } else {
        setErroAcao(mensagemDaApi(error, "Não foi possível sincronizar agora."))
      }
    } catch {
      setErroAcao("Não foi possível sincronizar. Verifique a rede e tente de novo.")
    } finally {
      setSincronizando(false)
    }
  }

  const acaoEmCurso = testando || sincronizando
  const semConexaoSalva = conexao !== null && !conexao.configurada

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Conexão com o ERP</h2>
        </CardTitle>
        <CardDescription>
          Aponta a loja para a unidade do Mercado Phone, de onde vêm estoque e preços. A chave de
          acesso fica no servidor: não é informada nem exibida aqui.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {falha ? (
          <p role="alert" className="text-sm text-danger">
            {falha}
          </p>
        ) : form === null || conexao === null ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Campo
                label="Unidade do ERP"
                dica="Número da unidade (system_unit_id) no Mercado Phone."
                erro={erros.system_unit_id}
              >
                {(p) => (
                  <Input
                    {...p}
                    type="number"
                    inputMode="numeric"
                    min={1}
                    value={form.system_unit_id}
                    onChange={(e) => alterar("system_unit_id", e.target.value)}
                  />
                )}
              </Campo>
              <Campo
                label="Filtro da loja"
                dica="Só se outra loja dividir a mesma unidade. Deixe vazio caso contrário."
                erro={erros.filtro_loja}
              >
                {(p) => (
                  <Input
                    {...p}
                    value={form.filtro_loja}
                    onChange={(e) => alterar("filtro_loja", e.target.value)}
                  />
                )}
              </Campo>
              <Campo
                label="Intervalo de sincronização (minutos)"
                dica={`De ${INTERVALO_MINIMO} a ${INTERVALO_MAXIMO} minutos.`}
                erro={erros.intervalo_min}
              >
                {(p) => (
                  <Input
                    {...p}
                    type="number"
                    inputMode="numeric"
                    min={INTERVALO_MINIMO}
                    max={INTERVALO_MAXIMO}
                    value={form.intervalo_min}
                    onChange={(e) => alterar("intervalo_min", e.target.value)}
                  />
                )}
              </Campo>
            </div>
            <div className="flex flex-col gap-3">
              <Checkbox
                rotulo="Sincronização ativa"
                descricao="Busca estoque e preços do ERP no intervalo acima."
                checked={form.ativo}
                onCheckedChange={(ativo) => setForm((atual) => (atual ? { ...atual, ativo } : atual))}
              />
              <Checkbox
                rotulo="Exportar handoff para o ERP"
                descricao="Ao passar o lead para o vendedor, registra o cliente e o orçamento no ERP."
                checked={form.exportar_handoff}
                onCheckedChange={(exportar_handoff) =>
                  setForm((atual) => (atual ? { ...atual, exportar_handoff } : atual))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => void testar()}
                  disabled={semConexaoSalva || acaoEmCurso}
                >
                  {testando ? "Testando…" : "Testar conexão"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void sincronizar()}
                  disabled={semConexaoSalva || acaoEmCurso}
                >
                  {sincronizando ? "Sincronizando…" : "Sincronizar agora"}
                </Button>
              </div>
              {semConexaoSalva ? (
                <p className="text-xs text-muted-foreground">
                  Salve a conexão para poder testar e sincronizar.
                </p>
              ) : null}
              {teste ? (
                <p
                  role={teste.ok ? "status" : "alert"}
                  className={teste.ok ? "text-sm text-success" : "text-sm text-danger"}
                >
                  {teste.mensagem}
                </p>
              ) : null}
              {erroAcao ? (
                <p role="alert" className="text-sm text-danger">
                  {erroAcao}
                </p>
              ) : null}
            </div>
            <StatusSincronizacao conexao={conexao} />
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
