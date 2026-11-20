import type { Metadata } from "next"
import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { ChatWeb } from "@/features/simulador/chat-web"

export const metadata: Metadata = {
  title: "Chat com a loja",
  description: "Converse com o atendimento da loja.",
}

async function ChatDaLoja({ params }: { params: Promise<{ loja: string }> }) {
  const { loja } = await params
  return <ChatWeb lojaId={loja} />
}

export default function Page({ params }: { params: Promise<{ loja: string }> }) {
  return (
    <Suspense fallback={<Skeleton className="mx-auto h-dvh w-full max-w-lg" />}>
      <ChatDaLoja params={params} />
    </Suspense>
  )
}
