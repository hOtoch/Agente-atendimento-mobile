import type { Metadata } from "next"

import { Vitrine } from "./vitrine"

export const metadata: Metadata = {
  title: "Design system — Atendimento Mobile",
}

export default function DesignPage() {
  return <Vitrine />
}
