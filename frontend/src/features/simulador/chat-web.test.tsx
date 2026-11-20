import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ChatWeb } from "./chat-web"
import type { MensagemWebchat, ServicoChat } from "./api"

const LOJA = "11111111-1111-1111-1111-111111111111"

const erroToast = vi.fn()
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ erro: erroToast, sucesso: vi.fn(), aviso: vi.fn(), info: vi.fn(), fechar: vi.fn() }),
}))

const gravador = {
  suportado: true,
  iniciar: vi.fn(),
  parar: vi.fn(),
}
vi.mock("./gravador-audio", async () => {
  const { useState } = await import("react")
  return {
    useGravadorAudio: () => {
      const [gravando, setGravando] = useState(false)
      return {
        suportado: gravador.suportado,
        gravando,
        iniciar: async () => {
          await gravador.iniciar()
          setGravando(true)
        },
        parar: async () => {
          setGravando(false)
          return gravador.parar()
        },
      }
    },
  }
})

function servicoFalso() {
  let entrega: ((m: MensagemWebchat) => void) | null = null
  const cancelar = vi.fn()
  let n = 0
  const servico = {
    criarSessao: vi.fn(async () => `sessao-${++n}`),
    enviarTexto: vi.fn(async () => {}),
    enviarMidia: vi.fn(async () => "http://api/midias/enviada.png"),
    assinar: vi.fn((_l: string, _s: string, onMensagem: (m: MensagemWebchat) => void) => {
      entrega = onMensagem
      return cancelar
    }),
  } satisfies ServicoChat
  return {
    servico,
    cancelar,
    emitir: (m: Partial<MensagemWebchat>) =>
      act(() => {
        entrega?.({ tipo: "texto", texto: null, midia_url: null, enviada_em: "2026-11-20T15:00:00Z", ...m })
      }),
  }
}

beforeEach(() => {
  window.sessionStorage.clear()
  erroToast.mockReset()
  gravador.suportado = true
  gravador.iniciar.mockReset().mockResolvedValue(undefined)
  gravador.parar.mockReset()
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:preview", revokeObjectURL: vi.fn() }))
})
afterEach(() => vi.unstubAllGlobals())

async function montar(f = servicoFalso()) {
  render(<ChatWeb lojaId={LOJA} servico={f.servico} />)
  await waitFor(() => expect(f.servico.assinar).toHaveBeenCalled())
  return f
}

describe("ChatWeb", () => {
  it("cria a sessão da loja, assina o stream e mostra estado vazio", async () => {
    const f = await montar()
    expect(f.servico.criarSessao).toHaveBeenCalledWith(LOJA)
    expect(f.servico.assinar).toHaveBeenCalledWith(LOJA, "sessao-1", expect.any(Function), expect.anything())
    expect(screen.getByText(/envie uma mensagem/i)).toBeInTheDocument()
  })

  it("envia texto: mostra o balão do cliente, chama o serviço e limpa o campo", async () => {
    const user = userEvent.setup()
    const f = await montar()

    await user.type(screen.getByRole("textbox", { name: /mensagem/i }), "Oi, tem iPhone 16?")
    await user.click(screen.getByRole("button", { name: "Enviar" }))

    expect(f.servico.enviarTexto).toHaveBeenCalledWith(LOJA, "sessao-1", expect.any(String), "Oi, tem iPhone 16?")
    expect(within(screen.getByRole("log")).getByText("Oi, tem iPhone 16?")).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: /mensagem/i })).toHaveValue("")
  })

  it("não envia mensagem vazia", async () => {
    const user = userEvent.setup()
    const f = await montar()
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled()
    await user.type(screen.getByRole("textbox", { name: /mensagem/i }), "   {enter}")
    expect(f.servico.enviarTexto).not.toHaveBeenCalled()
  })

  it("enter envia a mensagem", async () => {
    const user = userEvent.setup()
    const f = await montar()
    await user.type(screen.getByRole("textbox", { name: /mensagem/i }), "oi{enter}")
    expect(f.servico.enviarTexto).toHaveBeenCalledTimes(1)
  })

  it("mostra em tempo real o que chega pelo SSE (texto e áudio)", async () => {
    const f = await montar()
    await f.emitir({ tipo: "texto", texto: "Olá! Como posso ajudar?" })
    await f.emitir({ tipo: "audio", midia_url: "http://api/midias/resp.webm" })

    const log = screen.getByRole("log")
    expect(within(log).getByText("Olá! Como posso ajudar?")).toBeInTheDocument()
    expect(log.querySelector("audio")).toHaveAttribute("src", "http://api/midias/resp.webm")
  })

  it("sinaliza falha de envio com aviso e marca o balão", async () => {
    const user = userEvent.setup()
    const f = await montar()
    f.servico.enviarTexto.mockRejectedValueOnce(new Error("Loja não encontrada."))

    await user.type(screen.getByRole("textbox", { name: /mensagem/i }), "oi{enter}")

    await waitFor(() => expect(erroToast).toHaveBeenCalledWith("Loja não encontrada."))
    expect(screen.getByText("Não enviada")).toBeInTheDocument()
  })

  it("imagem: escolhe o arquivo, mostra preview, envia e exibe no chat", async () => {
    const user = userEvent.setup()
    const f = await montar()
    const arquivo = new File(["x"], "foto.png", { type: "image/png" })

    await user.upload(screen.getByLabelText(/arquivo de imagem/i), arquivo)
    expect(screen.getByRole("img", { name: /pré-visualização/i })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /enviar imagem/i }))

    expect(f.servico.enviarMidia).toHaveBeenCalledWith(LOJA, "sessao-1", expect.any(String), arquivo, "imagem")
    await waitFor(() => expect(screen.queryByRole("img", { name: /pré-visualização/i })).toBeNull())
    expect(within(screen.getByRole("log")).getByRole("img", { name: /imagem enviada/i })).toHaveAttribute(
      "src",
      "http://api/midias/enviada.png",
    )
  })

  it("cancelar descarta a imagem escolhida sem enviar", async () => {
    const user = userEvent.setup()
    const f = await montar()
    await user.upload(screen.getByLabelText(/arquivo de imagem/i), new File(["x"], "a.png", { type: "image/png" }))
    await user.click(screen.getByRole("button", { name: /cancelar/i }))
    expect(screen.queryByRole("img", { name: /pré-visualização/i })).toBeNull()
    expect(f.servico.enviarMidia).not.toHaveBeenCalled()
  })

  it("áudio: grava, para e envia o arquivo gravado", async () => {
    const user = userEvent.setup()
    const f = await montar()
    const gravado = new File(["voz"], "audio.webm", { type: "audio/webm" })
    gravador.parar.mockResolvedValue(gravado)
    f.servico.enviarMidia.mockResolvedValueOnce("http://api/midias/voz.webm")

    await user.click(screen.getByRole("button", { name: /gravar áudio/i }))
    expect(gravador.iniciar).toHaveBeenCalled()
    await user.click(await screen.findByRole("button", { name: /parar e enviar áudio/i }))

    expect(gravador.parar).toHaveBeenCalled()
    await waitFor(() =>
      expect(f.servico.enviarMidia).toHaveBeenCalledWith(LOJA, "sessao-1", expect.any(String), gravado, "audio"),
    )
    await waitFor(() =>
      expect(screen.getByRole("log").querySelector("audio")).toHaveAttribute("src", "http://api/midias/voz.webm"),
    )
  })

  it("avisa quando o microfone é negado", async () => {
    const user = userEvent.setup()
    await montar()
    gravador.iniciar.mockRejectedValue(new DOMException("negado", "NotAllowedError"))
    await user.click(screen.getByRole("button", { name: /gravar áudio/i }))
    await waitFor(() => expect(erroToast).toHaveBeenCalledWith(expect.stringMatching(/microfone/i)))
  })

  it("desabilita a gravação quando o navegador não suporta", async () => {
    gravador.suportado = false
    await montar()
    expect(screen.getByRole("button", { name: /gravar áudio/i })).toBeDisabled()
  })

  it("Nova conversa fecha o stream, limpa o chat e abre outra sessão", async () => {
    const user = userEvent.setup()
    const f = await montar()
    await f.emitir({ texto: "resposta antiga" })
    expect(screen.getByText("resposta antiga")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /nova conversa/i }))

    await waitFor(() => expect(f.servico.criarSessao).toHaveBeenCalledTimes(2))
    expect(f.cancelar).toHaveBeenCalled()
    await waitFor(() =>
      expect(f.servico.assinar).toHaveBeenLastCalledWith(LOJA, "sessao-2", expect.any(Function), expect.anything()),
    )
    expect(screen.queryByText("resposta antiga")).toBeNull()
    expect(window.sessionStorage.getItem(`simulador:sessao:${LOJA}`)).toBe("sessao-2")
  })

  it("reaproveita a sessão guardada no sessionStorage após recarregar", async () => {
    window.sessionStorage.setItem(`simulador:sessao:${LOJA}`, "sessao-guardada")
    const f = await montar()
    expect(f.servico.criarSessao).not.toHaveBeenCalled()
    expect(f.servico.assinar).toHaveBeenCalledWith(LOJA, "sessao-guardada", expect.any(Function), expect.anything())
  })

  it("funciona mesmo se o sessionStorage lançar erro", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("bloqueado")
    })
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("bloqueado")
    })
    const f = await montar()
    expect(f.servico.criarSessao).toHaveBeenCalledTimes(1)
    vi.restoreAllMocks()
  })

  it("fecha o stream ao desmontar", async () => {
    const f = servicoFalso()
    const { unmount } = render(<ChatWeb lojaId={LOJA} servico={f.servico} />)
    await screen.findByRole("textbox", { name: /mensagem/i })
    unmount()
    expect(f.cancelar).toHaveBeenCalled()
  })

  it("avisa quando não consegue abrir a sessão", async () => {
    const f = servicoFalso()
    f.servico.criarSessao.mockRejectedValueOnce(new Error("Loja não encontrada."))
    render(<ChatWeb lojaId={LOJA} servico={f.servico} />)
    expect(await screen.findByText(/não foi possível iniciar a conversa/i)).toBeInTheDocument()
    expect(screen.getByText("Loja não encontrada.")).toBeInTheDocument()
  })

  describe("layout responsivo (celular, 375px)", () => {
    beforeEach(() => {
      Object.defineProperty(window, "innerWidth", { value: 375, configurable: true })
      window.dispatchEvent(new Event("resize"))
    })

    it("ocupa a largura toda sem estourar: coluna, rolagem só na lista, campo encolhível", async () => {
      await montar()
      const raiz = screen.getByTestId("chat-web")
      expect(raiz.className).toMatch(/\bw-full\b/)
      expect(raiz.className).toMatch(/\bmax-w-lg\b/)
      expect(raiz.className).toMatch(/\bh-dvh\b/)
      expect(raiz.className).toMatch(/\bflex-col\b/)
      expect(raiz.className).not.toMatch(/\bw-\[\d+px\]/)

      const lista = screen.getByRole("log")
      expect(lista.className).toMatch(/\boverflow-y-auto\b/)
      expect(lista.className).toMatch(/\bflex-1\b/)
      expect(lista.className).toMatch(/\bmin-h-0\b/)

      expect(screen.getByRole("textbox", { name: /mensagem/i }).className).toMatch(/\bmin-w-0\b/)
      // alvos de toque confortáveis: botões de ação são icon-lg (>= 36px)
      for (const nome of [/anexar imagem/i, /gravar áudio/i]) {
        expect(screen.getByRole("button", { name: nome }).className).toMatch(/\bsize-9\b/)
      }
    })
  })
})
