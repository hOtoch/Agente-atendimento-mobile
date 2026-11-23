"use client"

import { useRouter, useSearchParams } from "next/navigation"
import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Campo } from "@/components/ui/campo"
import { CampoSenha } from "@/components/ui/campo-senha"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { sanitizarVolta, useSessao } from "@/lib/sessao"

type Cliente = Pick<typeof api, "POST">

/** "Muitas tentativas, tente em X min": `Retry-After` em segundos, arredondado para cima (mín. 1). */
function mensagemLimite(retryAfter: string | null): string {
  const segundos = Number(retryAfter)
  if (!retryAfter || !Number.isFinite(segundos) || segundos <= 0) {
    return "Muitas tentativas, tente novamente em instantes"
  }
  return `Muitas tentativas, tente em ${Math.max(1, Math.ceil(segundos / 60))} min`
}

export function LoginForm({ cliente = api }: { cliente?: Cliente }) {
  const router = useRouter()
  const params = useSearchParams()
  const { definirIdentidade } = useSessao()
  const [email, setEmail] = useState("")
  const [senha, setSenha] = useState("")
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function enviar(e: FormEvent) {
    e.preventDefault()
    if (!email.trim() || !senha) {
      setErro("Informe e-mail e senha")
      return
    }
    setEnviando(true)
    setErro(null)
    try {
      const { data, response } = await cliente.POST("/auth/login", {
        body: { email: email.trim(), senha },
      })
      if (data) {
        definirIdentidade(data)
        router.replace(sanitizarVolta(params.get("volta")))
        return
      }
      setErro(
        response.status === 429
          ? mensagemLimite(response.headers.get("Retry-After"))
          : response.status === 401
            ? "E-mail ou senha incorretos"
            : "Não foi possível entrar. Tente novamente.",
      )
    } catch {
      setErro("Não foi possível entrar. Tente novamente.")
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={enviar} noValidate className="flex w-full max-w-sm flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Entrar</h1>
        <p className="mt-1 text-sm text-muted-foreground">Acesse o painel de atendimento da loja.</p>
      </div>
      <Campo label="E-mail">
        {(c) => (
          <Input
            {...c}
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        )}
      </Campo>
      <CampoSenha label="Senha" value={senha} onChange={setSenha} />
      {erro ? (
        <p role="alert" className="text-sm text-danger">
          {erro}
        </p>
      ) : null}
      <Button type="submit" disabled={enviando}>
        Entrar
      </Button>
    </form>
  )
}
