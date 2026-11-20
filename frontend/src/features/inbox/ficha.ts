/**
 * Apresentação da ficha e da proposta (JSON do domínio) para o painel. Só formata o que o
 * backend já calculou: nenhuma regra de negócio mora aqui.
 */

const NAO_INFORMADO = "Não informado"
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" })

type Dados = Record<string, unknown>

function obj(valor: unknown): Dados {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor) ? (valor as Dados) : {}
}

function texto(valor: unknown): string | null {
  return typeof valor === "string" && valor !== "" ? valor : null
}

function numero(valor: unknown): number | null {
  if (typeof valor === "number" && Number.isFinite(valor)) return valor
  if (typeof valor === "string" && valor !== "" && Number.isFinite(Number(valor))) return Number(valor)
  return null
}

export function formatarMoeda(valor: unknown): string | null {
  const n = numero(valor)
  return n === null ? null : BRL.format(n)
}

function capacidade(valor: unknown): string | null {
  const gb = numero(valor)
  if (gb === null) return null
  return gb >= 1024 && gb % 1024 === 0 ? `${gb / 1024} TB` : `${gb} GB`
}

function nomeDoModelo(valor: unknown): string | null {
  return texto(obj(valor).nome)
}

function titulo(valor: unknown): string | null {
  const t = texto(valor)
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : null
}

function descreverAparelho(modelo: unknown, cap: unknown, cor?: unknown): string | null {
  const partes = [nomeDoModelo(modelo), capacidade(cap), texto(cor)].filter((p): p is string => p !== null)
  return partes.length ? partes.join(" · ") : null
}

function problemasDoUsado(usado: Dados): string[] {
  const problemas: string[] = []
  if (usado.tela_danificada === true) problemas.push("tela danificada")
  if (usado.traseira_danificada === true) problemas.push("traseira danificada")
  if (usado.carcaca_marcada === true) problemas.push("carcaça marcada")
  const bateria = numero(usado.bateria_pct)
  if (bateria !== null) problemas.push(`bateria ${bateria}%`)
  if (usado.camera_ok === false) problemas.push("câmera com defeito")
  if (Array.isArray(usado.outros_defeitos)) {
    for (const d of usado.outros_defeitos) if (typeof d === "string") problemas.push(d)
  }
  if (usado.peca_trocada === true) problemas.push("peça trocada")
  return problemas
}

function descreverTroca(ficha: Dados): string {
  if (ficha.tem_troca === false) return "Sem troca"
  if (ficha.tem_troca !== true) return NAO_INFORMADO
  const usado = obj(ficha.usado)
  const aparelho = descreverAparelho(usado.modelo, usado.capacidade) ?? "Aparelho usado"
  const problemas = problemasDoUsado(usado)
  const conhecido = ["tela_danificada", "traseira_danificada", "carcaca_marcada", "outros_defeitos"].some(
    (k) => usado[k] !== null && usado[k] !== undefined,
  )
  if (problemas.length) return `${aparelho} (${problemas.join(", ")})`
  return conhecido ? `${aparelho} (sem problemas informados)` : aparelho
}

function descreverData(valor: unknown): string {
  const iso = texto(valor)
  const m = iso?.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : NAO_INFORMADO
}

function descreverPagamento(valor: unknown): string {
  const p = obj(valor)
  const bandeira = titulo(p.bandeira)
  const parcelas = numero(p.parcelas)
  const entrada = formatarMoeda(p.entrada)
  let base: string
  switch (p.tipo) {
    case "pix":
      return "Pix ou dinheiro"
    case "debito":
      base = "Débito"
      break
    case "credito":
      base = parcelas ? `Crédito em ${parcelas}x` : "Crédito"
      break
    case "entrada_mais_credito":
      base = `${entrada ? `Entrada de ${entrada} + ` : "Entrada + "}crédito${parcelas ? ` em ${parcelas}x` : ""}`
      break
    default:
      return NAO_INFORMADO
  }
  return bandeira ? `${base} · ${bandeira}` : base
}

export type FichaDescrita = { aparelho: string; troca: string; dataPrevista: string; pagamento: string }

export function descreverFicha(ficha: Dados): FichaDescrita {
  const interesse = obj(ficha.interesse)
  return {
    aparelho: descreverAparelho(interesse.modelo, interesse.capacidade, interesse.cor) ?? NAO_INFORMADO,
    troca: descreverTroca(ficha),
    dataPrevista: descreverData(ficha.data_prevista_compra),
    pagamento: descreverPagamento(ficha.pagamento),
  }
}

export type PropostaDescrita = {
  precoAparelho: string
  troca: string | null
  desconto: string | null
  forma: string
  /** "10x de R$ 270,00"; null quando é à vista. */
  parcela: string | null
  total: string
}

/** Última proposta calculada pelo backend (valores já em string decimal); null se não houver. */
export function descreverProposta(proposta: Dados | null): PropostaDescrita | null {
  if (!proposta) return null
  const forma = obj(proposta.forma_escolhida)
  const rotulo = texto(forma.rotulo)
  const total = formatarMoeda(forma.total_pago ?? forma.valor_a_vista)
  const preco = formatarMoeda(proposta.preco_aparelho)
  if (!rotulo || !total || !preco) return null

  const troca = obj(proposta.troca)
  let valorTroca: string | null = null
  if (troca.status === "avaliada") valorTroca = formatarMoeda(troca.valor)
  else if (troca.status === "avaliacao_na_loja") valorTroca = "Avaliação na loja"

  const desconto = numero(obj(proposta.desconto).total)
  const parcelas = numero(forma.parcelas)
  const valorParcela = formatarMoeda(forma.valor_parcela)
  return {
    precoAparelho: preco,
    troca: valorTroca,
    desconto: desconto && desconto > 0 ? formatarMoeda(desconto) : null,
    forma: rotulo,
    parcela: parcelas && valorParcela ? `${parcelas}x de ${valorParcela}` : null,
    total,
  }
}
