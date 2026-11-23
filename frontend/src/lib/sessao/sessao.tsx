"use client"

import { usePathname, useRouter } from "next/navigation"
import {
  createContext,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, registrarAoNaoAutorizado, type Identidade } from "@/lib/api"

import { ehRotaPublica, urlLogin } from "./volta"

type Cliente = Pick<typeof api, "GET" | "POST">

export type Sessao = {
  lojaId: string
  lojaNome: string
  email: string
  senhaProvisoria: boolean
  /** Atualiza a identidade em memória (login, troca de senha). */
  definirIdentidade: (identidade: Identidade) => void
  /** Encerra a sessão no servidor e volta ao login. */
  sair: () => Promise<void>
}

const SessaoContext = createContext<Sessao | null>(null)

export function useSessao(): Sessao {
  const sessao = useContext(SessaoContext)
  if (!sessao) throw new Error("useSessao precisa estar dentro de <SessaoProvider>.")
  return sessao
}

/** `anonima`: sessão encerrada/expirada; só volta a buscar `/auth/eu` depois de passar por uma rota pública. */
type Estado = "carregando" | "ok" | "falha" | "anonima"

function Carregando() {
  return (
    <div role="status" aria-label="Carregando" className="flex min-h-screen gap-6 p-6">
      <Skeleton className="h-full min-h-96 w-sidebar" />
      <div className="flex flex-1 flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  )
}

/**
 * Guarda de sessão do painel: carrega `GET /auth/eu`, expõe a loja da sessão e redireciona
 * (401/403 → `/login?volta=`; senha provisória → `/conta/senha`). Rotas públicas passam direto.
 * O `Suspense` cobre o `usePathname()` das rotas dinâmicas (Cache Components).
 */
export function SessaoProvider({ children, cliente = api }: { children: ReactNode; cliente?: Cliente }) {
  return (
    <Suspense fallback={null}>
      <Guarda cliente={cliente}>{children}</Guarda>
    </Suspense>
  )
}

function Guarda({ children, cliente }: { children: ReactNode; cliente: Cliente }) {
  const pathname = usePathname()
  const router = useRouter()
  const publica = ehRotaPublica(pathname)
  const [identidade, setIdentidade] = useState<Identidade | null>(null)
  const [estado, setEstado] = useState<Estado>("carregando")

  // Depois de encerrar/expirar a sessão só se busca `/auth/eu` de novo após passar por rota pública.
  const passouPorPublica = useRef(false)
  useEffect(() => {
    if (publica) passouPorPublica.current = true
  }, [publica])

  const irParaLogin = useCallback(() => {
    passouPorPublica.current = false
    setIdentidade(null)
    setEstado("anonima")
    const busca = typeof window !== "undefined" && window.location.pathname === pathname ? window.location.search : ""
    router.replace(urlLogin(pathname + busca))
  }, [pathname, router])

  useEffect(() => {
    if (publica) return
    return registrarAoNaoAutorizado(irParaLogin)
  }, [publica, irParaLogin])

  useEffect(() => {
    if (publica) return
    if (estado === "anonima" ? !passouPorPublica.current : estado !== "carregando") return
    let ativo = true
    cliente
      .GET("/auth/eu")
      .then(({ data, response }) => {
        if (!ativo) return
        if (data) {
          setIdentidade(data)
          setEstado("ok")
        } else if (response.status === 401 || response.status === 403) {
          irParaLogin()
        } else {
          setEstado("falha")
        }
      })
      .catch(() => {
        if (ativo) setEstado("falha")
      })
    return () => {
      ativo = false
    }
  }, [publica, estado, cliente, irParaLogin])

  const provisoria = identidade?.senha_provisoria === true && pathname !== "/conta/senha"
  useEffect(() => {
    if (!publica && provisoria) router.replace("/conta/senha")
  }, [publica, provisoria, router])

  const definirIdentidade = useCallback((nova: Identidade) => {
    setIdentidade(nova)
    setEstado("ok")
  }, [])

  const sair = useCallback(async () => {
    try {
      await cliente.POST("/auth/logout")
    } finally {
      passouPorPublica.current = false
      setIdentidade(null)
      setEstado("anonima")
      router.replace("/login")
    }
  }, [cliente, router])

  const valor = useMemo<Sessao | null>(
    () =>
      identidade
        ? {
            lojaId: identidade.loja_id,
            lojaNome: identidade.loja_nome,
            email: identidade.email,
            senhaProvisoria: identidade.senha_provisoria,
            definirIdentidade,
            sair,
          }
        : null,
    [identidade, definirIdentidade, sair],
  )

  if (publica) {
    // Rotas públicas não leem a sessão, mas o login precisa gravar a identidade ao entrar.
    return (
      <SessaoContext.Provider value={valor ?? semIdentidade(definirIdentidade, sair)}>
        {children}
      </SessaoContext.Provider>
    )
  }

  if (estado === "falha") {
    return (
      <div role="alert" className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-sm text-muted-foreground">Não foi possível carregar a sessão.</p>
        <Button variant="outline" onClick={() => setEstado("carregando")}>
          Tentar de novo
        </Button>
      </div>
    )
  }

  if (!valor || provisoria) return <Carregando />

  return <SessaoContext.Provider value={valor}>{children}</SessaoContext.Provider>
}

function semIdentidade(definirIdentidade: Sessao["definirIdentidade"], sair: Sessao["sair"]): Sessao {
  return { lojaId: "", lojaNome: "", email: "", senhaProvisoria: false, definirIdentidade, sair }
}
