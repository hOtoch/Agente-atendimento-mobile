import { errosDoCorpo } from "./grades"

/** Erros da API por campo simples (`{ caminho: "max_parcelas" }`) -> `{ campo: mensagem }`. */
export function errosPorCampo(corpo: unknown): { campos: Record<string, string>; gerais: string[] } {
  const campos: Record<string, string> = {}
  const gerais: string[] = []
  const erros = errosDoCorpo(corpo)
  if (!erros) return { campos, gerais: ["Não foi possível salvar. Tente de novo."] }
  for (const e of erros) {
    if (/^\w+$/.test(e.caminho) && !(e.caminho in campos)) campos[e.caminho] = e.mensagem
    else gerais.push(e.mensagem)
  }
  return { campos, gerais }
}
