"use client"

import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { CampoSenha } from "@/components/ui/campo-senha"
import { api, mensagemDeErro } from "@/lib/api"
import { useSessao } from "@/lib/sessao"

type Cliente = Pick<typeof api, "PUT">

const MINIMO = 10
const MSG_CURTA = `A nova senha precisa ter pelo menos ${MINIMO} caracteres.`

/** Erros tipados do backend (`motivo`) e o campo onde cada um aparece. */
const MOTIVOS: Record<string, { campo: "atual" | "nova"; mensagem: string }> = {
  senha_atual_incorreta: { campo: "atual", mensagem: "A senha atual está incorreta." },
  senha_nova_curta: { campo: "nova", mensagem: MSG_CURTA },
  senha_nova_igual: { campo: "nova", mensagem: "A nova senha precisa ser diferente da atual." },
}

type Erros = { atual?: string; nova?: string; confirmacao?: string; geral?: string }

export function TrocarSenhaForm({ cliente = api }: { cliente?: Cliente }) {
  const router = useRouter()
  const sessao = useSessao()
  const [atual, setAtual] = useState("")
  const [nova, setNova] = useState("")
  const [confirmacao, setConfirmacao] = useState("")
  const [erros, setErros] = useState<Erros>({})
  const [enviando, setEnviando] = useState(false)

  async function enviar(e: FormEvent) {
    e.preventDefault()
    const locais: Erros = {}
    if (!atual) locais.atual = "Informe a senha atual."
    if (nova.length < MINIMO) locais.nova = MSG_CURTA
    else if (confirmacao !== nova) locais.confirmacao = "A confirmação não é igual à nova senha."
    setErros(locais)
    if (Object.keys(locais).length) return

    setEnviando(true)
    try {
      const { error, response } = await cliente.PUT("/auth/senha", {
        body: { senha_atual: atual, senha_nova: nova },
      })
      if (!error && response.ok) {
        sessao.definirIdentidade({
          loja_id: sessao.lojaId,
          loja_nome: sessao.lojaNome,
          email: sessao.email,
          senha_provisoria: false,
        })
        router.replace("/kanban")
        return
      }
      const motivo = (error as { motivo?: string } | undefined)?.motivo
      const conhecido = motivo ? MOTIVOS[motivo] : undefined
      setErros(conhecido ? { [conhecido.campo]: conhecido.mensagem } : { geral: mensagemDeErro(error) })
    } catch {
      setErros({ geral: "Não foi possível trocar a senha. Tente novamente." })
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={enviar} noValidate className="flex w-full max-w-sm flex-col gap-4">
      {sessao.senhaProvisoria ? (
        <p className="text-sm text-muted-foreground">
          Sua senha é provisória. Escolha uma nova para acessar o painel.
        </p>
      ) : null}
      <CampoSenha label="Senha atual" value={atual} onChange={setAtual} erro={erros.atual} />
      <CampoSenha
        label="Nova senha"
        value={nova}
        onChange={setNova}
        erro={erros.nova}
        dica={`Mínimo de ${MINIMO} caracteres.`}
        autoComplete="new-password"
      />
      <CampoSenha
        label="Confirmar nova senha"
        value={confirmacao}
        onChange={setConfirmacao}
        erro={erros.confirmacao}
        autoComplete="new-password"
      />
      {erros.geral ? (
        <p role="alert" className="text-sm text-danger">
          {erros.geral}
        </p>
      ) : null}
      <Button type="submit" disabled={enviando}>
        Trocar senha
      </Button>
    </form>
  )
}
