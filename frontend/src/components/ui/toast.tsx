"use client"

import { toast as sonner, Toaster as SonnerToaster, type ToasterProps } from "sonner"

/**
 * Provedor de avisos: monte `<Toaster />` uma vez (layout raiz) e use `useToast()`
 * nas features. Cores só por tokens (popover/border/success/warning/danger).
 */
export function Toaster({ ...props }: ToasterProps) {
  return (
    <SonnerToaster
      theme="light"
      position="bottom-right"
      containerAriaLabel="Notificações"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--success-bg": "var(--popover)",
          "--success-text": "var(--popover-foreground)",
          "--success-border": "var(--success)",
          "--warning-bg": "var(--popover)",
          "--warning-text": "var(--popover-foreground)",
          "--warning-border": "var(--warning)",
          "--error-bg": "var(--popover)",
          "--error-text": "var(--popover-foreground)",
          "--error-border": "var(--danger)",
          "--border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export type ToastOpcoes = { descricao?: string; duracaoMs?: number }

function opcoes({ descricao, duracaoMs }: ToastOpcoes = {}) {
  return { description: descricao, duration: duracaoMs }
}

/** API estável do painel (pt-BR); troca de biblioteca não afeta as features. */
export const toast = {
  info: (mensagem: string, o?: ToastOpcoes) => sonner(mensagem, opcoes(o)),
  sucesso: (mensagem: string, o?: ToastOpcoes) => sonner.success(mensagem, opcoes(o)),
  aviso: (mensagem: string, o?: ToastOpcoes) => sonner.warning(mensagem, opcoes(o)),
  erro: (mensagem: string, o?: ToastOpcoes) => sonner.error(mensagem, opcoes(o)),
  fechar: (id?: string | number) => sonner.dismiss(id),
}

export function useToast() {
  return toast
}
