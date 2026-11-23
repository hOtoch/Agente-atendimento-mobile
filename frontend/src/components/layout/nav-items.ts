import {
  ChartNoAxesCombined,
  Columns3,
  MessageSquare,
  MessagesSquare,
  Rocket,
  Settings,
  type LucideIcon,
} from "lucide-react"

export type NavItem = {
  label: string
  href: string
  icon: LucideIcon
}

export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Kanban", href: "/kanban", icon: Columns3 },
  { label: "Conversas", href: "/conversas", icon: MessageSquare },
  { label: "Onboarding", href: "/onboarding", icon: Rocket },
  { label: "Simulador", href: "/simulador", icon: MessagesSquare },
  { label: "Desempenho", href: "/desempenho", icon: ChartNoAxesCombined },
  { label: "Configurações", href: "/configuracoes", icon: Settings },
]
