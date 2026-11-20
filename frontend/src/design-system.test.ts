import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative } from "node:path"
import { describe, expect, it } from "vitest"

const SRC = join(__dirname)

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [full] : []
  })
}

const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
const UTILS =
  "bg|text|border|ring|fill|stroke|from|via|to|outline|divide|accent|caret|decoration|shadow|placeholder"

const RULES: { name: string; re: RegExp }[] = [
  { name: "classe arbitrária de cor (bg-[#...])", re: new RegExp(String.raw`\b(${UTILS})-\[#`) },
  { name: "função de cor crua (rgb/rgba/hsl/hsla)", re: /\b(rgba?|hsla?)\(/ },
  { name: "literal hexadecimal", re: /#[0-9a-fA-F]{3,8}\b/ },
  {
    name: "cor de paleta crua do Tailwind (bg-blue-500)",
    re: new RegExp(String.raw`\b(${UTILS})-(${PALETTE})-\d{2,3}\b`),
  },
  { name: "preto/branco cru (bg-white, text-black)", re: new RegExp(String.raw`\b(${UTILS})-(white|black)\b`) },
]

describe("design system: sem valores de cor hardcoded", () => {
  const files = walk(SRC)

  it("encontra arquivos para varrer", () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it.each(RULES)("nenhum arquivo viola: $name", ({ re }) => {
    const violations: string[] = []
    for (const file of files) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (re.test(line)) violations.push(`${relative(SRC, file)}:${i + 1}: ${line.trim()}`)
        })
    }
    expect(violations).toEqual([])
  })

  it("o detector pega exemplos ruins (sanidade)", () => {
    const bad = ['className="bg-[#fff]"', "text-blue-500", "color: rgb(0,0,0)", "bg-white"]
    for (const sample of bad) {
      expect(RULES.some((r) => r.re.test(sample)), sample).toBe(true)
    }
  })
})
