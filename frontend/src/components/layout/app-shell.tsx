"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { KeyRound, LogOut } from "lucide-react"
import { Suspense, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { ehRotaPublica, useSessao } from "@/lib/sessao"
import { cn } from "@/lib/utils"

import { NAV_ITEMS } from "./nav-items"

/**
 * Em rotas dinâmicas (`/chat/[loja]`) `usePathname()` só resolve em runtime; o Suspense permite
 * pré-renderizar o restante sem bloquear o build (Cache Components).
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={null}>
      <Casca>{children}</Casca>
    </Suspense>
  )
}

function Casca({ children }: { children: ReactNode }) {
  const pathname = usePathname()

  // Rotas públicas (login e chat do cliente): sem sidebar nem padding do painel.
  if (ehRotaPublica(pathname)) {
    return <div className="min-h-screen bg-background text-foreground">{children}</div>
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-sidebar shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
        <div className="px-4 py-4">
          <div className="text-base font-semibold">Atendimento Mobile</div>
          <LojaDaSessao />
        </div>
        <nav aria-label="Principal" className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`)
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                  active && "bg-sidebar-accent text-sidebar-accent-foreground",
                )}
              >
                <Icon aria-hidden className="size-4" />
                {label}
              </Link>
            )
          })}
        </nav>
        <Conta />
      </aside>
      <main className="min-w-0 flex-1 p-6">{children}</main>
    </div>
  )
}

function LojaDaSessao() {
  const { lojaNome } = useSessao()
  return <div className="mt-1 truncate text-sm text-muted-foreground">{lojaNome}</div>
}

function Conta() {
  const { sair } = useSessao()
  return (
    <div className="mt-auto flex flex-col gap-1 border-t border-sidebar-border p-2">
      <Link
        href="/conta/senha"
        className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
      >
        <KeyRound aria-hidden className="size-4" />
        Trocar senha
      </Link>
      <Button variant="ghost" className="justify-start px-3" onClick={() => void sair()}>
        <LogOut aria-hidden />
        Sair
      </Button>
    </div>
  )
}
