import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const css = readFileSync(join(__dirname, "tokens.css"), "utf8")

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`)
  if (start < 0) return ""
  const end = css.indexOf("\n}", start)
  return css.slice(start, end)
}

function vars(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}

const root = vars(block(":root"))
const dark = vars(block(".dark"))

const SEMANTIC = [
  "--background",
  "--foreground",
  "--primary",
  "--primary-foreground",
  "--muted",
  "--muted-foreground",
  "--border",
  "--success",
  "--warning",
  "--danger",
  "--stage-novo-contato",
  "--stage-interesse-identificado",
  "--stage-interesse-qualificado",
  "--stage-com-vendedor",
  "--stage-venda-fechada",
  "--radius",
  "--space-unit",
  "--font-size-base",
]

describe("tokens de design", () => {
  it.each(SEMANTIC)("define %s no tema claro", (name) => {
    expect(root[name], name).toBeTruthy()
  })

  it("tema escuro (classe .dark) troca as variáveis de cor", () => {
    for (const name of [
      "--background",
      "--foreground",
      "--primary",
      "--muted",
      "--border",
      "--success",
      "--warning",
      "--danger",
    ]) {
      expect(dark[name], name).toBeTruthy()
      expect(dark[name], `${name} igual nos dois temas`).not.toBe(root[name])
    }
  })

  it("aplica a classe dark ao documento sem quebrar a lista de classes", () => {
    document.documentElement.classList.add("dark")
    expect(document.documentElement.matches(".dark")).toBe(true)
    document.documentElement.classList.remove("dark")
    expect(document.documentElement.matches(".dark")).toBe(false)
  })
})
