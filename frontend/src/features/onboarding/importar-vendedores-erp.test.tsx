import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { criarCliente } from "@/lib/api"

import { ImportarVendedoresErp, resumirImportacaoVendedores } from "./importar-vendedores-erp"

const LOJA = "00000000-0000-4000-8000-00000000de61"
const ROTA = `/lojas/${LOJA}/vendedores/importar-erp`

function clienteCom(resposta: { status?: number; corpo: unknown } | (() => never)) {
  const chamadas: Request[] = []
  const fetchFalso = vi.fn(async (req: Request) => {
    chamadas.push(req.clone())
    if (typeof resposta === "function") resposta()
    const r = resposta as { status?: number; corpo: unknown }
    return new Response(JSON.stringify(r.corpo), {
      status: r.status ?? 200,
      headers: { "Content-Type": "application/json" },
    })
  })
  return { cliente: criarCliente("http://api.local", fetchFalso), chamadas }
}

describe("resumirImportacaoVendedores", () => {
  it("conta no singular e no plural", () => {
    expect(
      resumirImportacaoVendedores({ criados: 1, atualizados: 2, desativados: 0, sem_alteracao: 4 }),
    ).toBe("1 criado, 2 atualizados, 0 desativados.")
  })

  it("avisa quando nada mudou", () => {
    expect(
      resumirImportacaoVendedores({ criados: 0, atualizados: 0, desativados: 0, sem_alteracao: 3 }),
    ).toMatch(/nenhuma mudança/i)
  })
})

describe("ImportarVendedoresErp", () => {
  it("chama a API, mostra o resumo, lembra do percentual e avisa quem importou", async () => {
    const { cliente, chamadas } = clienteCom({
      corpo: { criados: 2, atualizados: 0, desativados: 1, sem_alteracao: 0 },
    })
    const aoImportar = vi.fn()
    const user = userEvent.setup()
    render(<ImportarVendedoresErp cliente={cliente} lojaId={LOJA} aoImportar={aoImportar} />)

    await user.click(screen.getByRole("button", { name: "Importar do ERP" }))

    const status = await screen.findByRole("status")
    expect(status).toHaveTextContent("2 criados, 0 atualizados, 1 desativado.")
    expect(status).toHaveTextContent(/0%/)
    expect(chamadas).toHaveLength(1)
    expect(chamadas[0].method).toBe("POST")
    expect(new URL(chamadas[0].url).pathname).toBe(ROTA)
    expect(aoImportar).toHaveBeenCalledTimes(1)
  })

  it("desabilita o botão enquanto importa (sem clique duplo)", async () => {
    let liberar: (r: Response) => void = () => {}
    const fetchFalso = vi.fn(
      () => new Promise<Response>((resolve) => (liberar = resolve)),
    )
    const cliente = criarCliente("http://api.local", fetchFalso)
    const user = userEvent.setup()
    render(<ImportarVendedoresErp cliente={cliente} lojaId={LOJA} aoImportar={() => {}} />)

    await user.click(screen.getByRole("button", { name: "Importar do ERP" }))
    expect(screen.getByRole("button", { name: /importando/i })).toBeDisabled()
    liberar(
      new Response(JSON.stringify({ criados: 0, atualizados: 0, desativados: 0, sem_alteracao: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    await waitFor(() => expect(screen.getByRole("button", { name: "Importar do ERP" })).toBeEnabled())
    expect(fetchFalso).toHaveBeenCalledTimes(1)
  })

  it("mostra a mensagem de erro da API e não recarrega a grade", async () => {
    const { cliente } = clienteCom({
      status: 409,
      corpo: { erros: [{ caminho: "erp", mensagem: "Loja sem conexão com o ERP." }] },
    })
    const aoImportar = vi.fn()
    const user = userEvent.setup()
    render(<ImportarVendedoresErp cliente={cliente} lojaId={LOJA} aoImportar={aoImportar} />)

    await user.click(screen.getByRole("button", { name: "Importar do ERP" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Loja sem conexão com o ERP.")
    expect(aoImportar).not.toHaveBeenCalled()
  })

  it("falha de rede vira mensagem clara", async () => {
    const { cliente } = clienteCom(() => {
      throw new TypeError("Failed to fetch")
    })
    const user = userEvent.setup()
    render(<ImportarVendedoresErp cliente={cliente} lojaId={LOJA} aoImportar={() => {}} />)

    await user.click(screen.getByRole("button", { name: "Importar do ERP" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(/não foi possível importar/i)
  })
})
