"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Suspense, type ReactNode } from "react"

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

  // Rotas públicas (chat do avaliador): sem sidebar nem padding do painel.
  if (pathname === "/chat" || pathname.startsWith("/chat/")) {
    return <div className="min-h-screen bg-background text-foreground">{children}</div>
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-sidebar shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
        <div className="px-4 py-4 text-base font-semibold">Atendimento Mobile</div>
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
      </aside>
      <main className="min-w-0 flex-1 p-6">{children}</main>
    </div>
  )
}
