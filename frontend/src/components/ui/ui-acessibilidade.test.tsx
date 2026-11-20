import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { Avatar, AvatarFallback } from "./avatar"
import { Button } from "./button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./card"
import { Input } from "./input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "./sheet"
import { Skeleton } from "./skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs"
import { Textarea } from "./textarea"

describe("acessibilidade básica dos componentes de ui", () => {
  it("Input e Textarea são associados ao rótulo e sinalizam erro", () => {
    render(
      <>
        <label htmlFor="n">Nome</label>
        <Input id="n" aria-invalid />
        <label htmlFor="o">Observação</label>
        <Textarea id="o" />
      </>,
    )
    expect(screen.getByRole("textbox", { name: "Nome" })).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("textbox", { name: "Observação" })).toBeInTheDocument()
  })

  it("Button é focável por teclado e respeita disabled", async () => {
    const user = userEvent.setup()
    render(
      <>
        <Button>Salvar</Button>
        <Button disabled>Enviar</Button>
      </>,
    )
    await user.tab()
    expect(screen.getByRole("button", { name: "Salvar" })).toHaveFocus()
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled()
  })

  it("Tabs expõe tablist/tab/tabpanel e troca de painel por clique e setas", async () => {
    const user = userEvent.setup()
    render(
      <Tabs defaultValue="a">
        <TabsList aria-label="Seções">
          <TabsTrigger value="a">Taxas</TabsTrigger>
          <TabsTrigger value="b">Estoque</TabsTrigger>
        </TabsList>
        <TabsContent value="a">painel taxas</TabsContent>
        <TabsContent value="b">painel estoque</TabsContent>
      </Tabs>,
    )
    expect(screen.getByRole("tablist", { name: "Seções" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Taxas" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tabpanel")).toHaveTextContent("painel taxas")

    await user.click(screen.getByRole("tab", { name: "Estoque" }))
    expect(screen.getByRole("tabpanel")).toHaveTextContent("painel estoque")

    screen.getByRole("tab", { name: "Estoque" }).focus()
    await user.keyboard("{ArrowLeft}")
    expect(screen.getByRole("tab", { name: "Taxas" })).toHaveFocus()
  })

  it("Table usa semântica de tabela", () => {
    render(
      <Table aria-label="Estoque">
        <TableHeader>
          <TableRow>
            <TableHead>Modelo</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>iPhone 15</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    )
    expect(screen.getByRole("table", { name: "Estoque" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Modelo" })).toBeInTheDocument()
    expect(screen.getByRole("cell", { name: "iPhone 15" })).toBeInTheDocument()
  })

  it("Sheet abre como dialog nomeado e fecha com Esc", async () => {
    const user = userEvent.setup()
    render(
      <Sheet>
        <SheetTrigger render={<Button>Detalhes</Button>} />
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Lead</SheetTitle>
            <SheetDescription>Resumo</SheetDescription>
          </SheetHeader>
        </SheetContent>
      </Sheet>,
    )
    await user.click(screen.getByRole("button", { name: "Detalhes" }))
    expect(await screen.findByRole("dialog", { name: "Lead" })).toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  it("Card compõe título e descrição; Avatar mostra fallback; Skeleton é decorativo", () => {
    render(
      <>
        <Card>
          <CardHeader>
            <CardTitle>Resumo</CardTitle>
            <CardDescription>Hoje</CardDescription>
          </CardHeader>
          <CardContent>corpo</CardContent>
        </Card>
        <Avatar>
          <AvatarFallback>AB</AvatarFallback>
        </Avatar>
        <Skeleton data-testid="sk" />
      </>,
    )
    expect(screen.getByText("Resumo")).toBeInTheDocument()
    expect(screen.getByText("AB")).toBeInTheDocument()
    expect(screen.getByTestId("sk")).toHaveAttribute("aria-hidden", "true")
  })
})
