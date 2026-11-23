import type { Metadata } from "next"
import { Suspense } from "react"

import { LoginForm } from "@/features/auth/login-form"

export const metadata: Metadata = { title: "Entrar · Atendimento Mobile" }

export default function Page() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </main>
  )
}
