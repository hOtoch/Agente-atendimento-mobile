import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { MessageBubble } from "./message-bubble"

const HORA = new Date(2026, 10, 20, 15, 30)

describe("MessageBubble", () => {
  it("mostra o texto e o horário em pt-BR", () => {
    render(<MessageBubble lado="cliente" tipo="texto" texto="Oi, tem iPhone 16?" horario={HORA} />)
    expect(screen.getByText("Oi, tem iPhone 16?")).toBeInTheDocument()
    expect(screen.getByText("15:30")).toBeInTheDocument()
  })

  it("alinha à direita as mensagens de quem vê (perspectiva) e à esquerda as do outro lado", () => {
    const { rerender } = render(
      <MessageBubble lado="cliente" tipo="texto" texto="x" perspectiva="cliente" />,
    )
    expect(screen.getByTestId("balao")).toHaveAttribute("data-alinhamento", "direita")
    rerender(<MessageBubble lado="atendente" tipo="texto" texto="x" perspectiva="cliente" />)
    expect(screen.getByTestId("balao")).toHaveAttribute("data-alinhamento", "esquerda")
    rerender(<MessageBubble lado="cliente" tipo="texto" texto="x" />)
    expect(screen.getByTestId("balao")).toHaveAttribute("data-alinhamento", "esquerda")
    rerender(<MessageBubble lado="atendente" tipo="texto" texto="x" />)
    expect(screen.getByTestId("balao")).toHaveAttribute("data-alinhamento", "direita")
  })

  it("renderiza imagem com texto alternativo", () => {
    render(<MessageBubble lado="cliente" tipo="imagem" midiaUrl="http://api/midias/a.png" />)
    const img = screen.getByRole("img", { name: /imagem enviada/i })
    expect(img).toHaveAttribute("src", "http://api/midias/a.png")
  })

  it("renderiza áudio com controles nativos", () => {
    const { container } = render(
      <MessageBubble lado="atendente" tipo="audio" midiaUrl="http://api/midias/a.webm" />,
    )
    const audio = container.querySelector("audio")
    expect(audio).not.toBeNull()
    expect(audio).toHaveAttribute("controls")
    expect(audio).toHaveAttribute("src", "http://api/midias/a.webm")
  })

  it("identifica o autor quando informado e sinaliza erro de envio", () => {
    render(
      <MessageBubble lado="atendente" tipo="texto" texto="oi" autor="Atendente" erro="Não enviada" />,
    )
    expect(screen.getByText("Atendente")).toBeInTheDocument()
    expect(screen.getByText("Não enviada")).toBeInTheDocument()
  })
})
