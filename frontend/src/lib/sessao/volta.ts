const PADRAO = "/kanban"

/** Rotas que não exigem sessão: a tela de login e o chat web público do cliente da loja. */
export function ehRotaPublica(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname === "/chat" ||
    pathname.startsWith("/chat/")
  )
}

/**
 * Valida o destino pós-login (`?volta=`): só caminhos internos, para evitar open redirect.
 * Qualquer outra coisa (URL absoluta, `//host`, barra invertida, o próprio login) vira o kanban.
 */
export function sanitizarVolta(valor: string | null | undefined): string {
  if (typeof valor !== "string" || !valor.startsWith("/")) return PADRAO
  if (valor.startsWith("//") || valor.includes("\\")) return PADRAO
  if (/[\u0000-\u001f]/.test(valor)) return PADRAO
  const caminho = valor.split(/[?#]/)[0]
  if (caminho === "/login") return PADRAO
  return valor
}

/** `/login?volta=<rota>`; sem rota interna válida (ou se já for o login) vai só para `/login`. */
export function urlLogin(rota: string): string {
  const volta = sanitizarVolta(rota)
  if (volta === PADRAO && rota !== PADRAO) return "/login"
  return `/login?volta=${encodeURIComponent(volta).replace(/%2F/g, "/")}`
}
