"use client"

import { Inbox, Moon, Sun } from "lucide-react"
import { useState, type ReactNode } from "react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge, DonoBadge, EtapaBadge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DataGrid,
  errosDeCelulas,
  type DataGridColumn,
  type DataGridRow,
} from "@/components/ui/data-grid"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { PageHeader } from "@/components/ui/page-header"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/toast"
import { ETAPAS } from "@/lib/etapas"

const COLUNAS: DataGridColumn[] = [
  { key: "bandeira", header: "Bandeira", type: "select", options: [
    { value: "visa", label: "Visa" },
    { value: "master", label: "Mastercard" },
  ] },
  { key: "parcelas", header: "Parcelas", type: "number" },
  { key: "taxa", header: "Taxa (%)", type: "number" },
  { key: "nota", header: "Observação", type: "text" },
]

const LINHAS_INICIAIS: DataGridRow[] = [
  { bandeira: "visa", parcelas: 1, taxa: 2.99, nota: "À vista no crédito" },
  { bandeira: "visa", parcelas: 12, taxa: 14.9, nota: "" },
  { bandeira: "master", parcelas: 6, taxa: -1, nota: "Taxa negativa (erro de exemplo)" },
]

function Secao({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="border-b border-border pb-1 text-base font-semibold">{titulo}</h2>
      {children}
    </section>
  )
}

function Linha({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2">{children}</div>
}

function GradeDemo() {
  const [linhas, setLinhas] = useState<DataGridRow[]>(LINHAS_INICIAIS)
  const erros = errosDeCelulas(
    linhas.flatMap((l, i) =>
      typeof l.taxa === "number" && l.taxa < 0
        ? [{ linha: i, coluna: "taxa", mensagem: "A taxa não pode ser negativa." }]
        : [],
    ),
  )
  return (
    <DataGrid
      aria-label="Taxas de exemplo"
      columns={COLUNAS}
      rows={linhas}
      errors={erros}
      onChange={({ rowIndex, columnKey, value }) =>
        setLinhas((atual) => atual.map((l, i) => (i === rowIndex ? { ...l, [columnKey]: value } : l)))
      }
      onAddRow={() => setLinhas((a) => [...a, { bandeira: "visa", parcelas: null, taxa: null, nota: "" }])}
      onRemoveRow={(i) => setLinhas((a) => a.filter((_, idx) => idx !== i))}
    />
  )
}

function ToastDemo() {
  const toast = useToast()
  return (
    <Linha>
      <Button variant="outline" onClick={() => toast.sucesso("Configuração salva")}>
        Sucesso
      </Button>
      <Button variant="outline" onClick={() => toast.aviso("Estoque baixo", { descricao: "Restam 2 unidades." })}>
        Aviso
      </Button>
      <Button
        variant="outline"
        onClick={() =>
          toast.erro("Arrasto proibido", { descricao: "A etapa Venda fechada só é definida pelo vendedor." })
        }
      >
        Erro
      </Button>
    </Linha>
  )
}

export function Vitrine() {
  const [escuro, setEscuro] = useState(false)

  function alternarTema() {
    const proximo = !escuro
    document.documentElement.classList.toggle("dark", proximo)
    setEscuro(proximo)
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Design system"
        description="Componentes base e estados. Só tokens de DESIGN.md; alterne o tema para conferir claro e escuro."
      >
        <Button variant="outline" onClick={alternarTema}>
          {escuro ? <Sun aria-hidden="true" data-icon="inline-start" /> : <Moon aria-hidden="true" data-icon="inline-start" />}
          {escuro ? "Tema claro" : "Tema escuro"}
        </Button>
      </PageHeader>

      <Secao titulo="Button">
        <Linha>
          <Button>Principal</Button>
          <Button variant="secondary">Secundário</Button>
          <Button variant="outline">Contorno</Button>
          <Button variant="ghost">Fantasma</Button>
          <Button variant="destructive">Destrutivo</Button>
          <Button variant="link">Link</Button>
          <Button disabled>Desabilitado</Button>
        </Linha>
        <Linha>
          <Button size="xs">xs</Button>
          <Button size="sm">sm</Button>
          <Button size="default">padrão</Button>
          <Button size="lg">lg</Button>
        </Linha>
      </Secao>

      <Secao titulo="Input, Textarea e Select">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="v-nome" className="text-sm font-medium">Nome</label>
            <Input id="v-nome" placeholder="Nome do cliente" />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="v-erro" className="text-sm font-medium">Com erro</label>
            <Input id="v-erro" aria-invalid defaultValue="valor inválido" aria-describedby="v-erro-msg" />
            <p id="v-erro-msg" className="text-xs text-danger">Campo obrigatório.</p>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="v-dis" className="text-sm font-medium">Desabilitado</label>
            <Input id="v-dis" disabled defaultValue="somente leitura" />
          </div>
          <div className="flex flex-col gap-1">
            <span id="v-sel" className="text-sm font-medium">Select</span>
            <Select defaultValue="visa">
              <SelectTrigger aria-labelledby="v-sel" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="visa">Visa</SelectItem>
                <SelectItem value="master">Mastercard</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1 sm:col-span-2">
            <label htmlFor="v-obs" className="text-sm font-medium">Observação</label>
            <Textarea id="v-obs" placeholder="Anotações da conversa" />
          </div>
        </div>
      </Secao>

      <Secao titulo="Card">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Maria Souza</CardTitle>
              <CardDescription>iPhone 15 128 GB · há 5 min</CardDescription>
            </CardHeader>
            <CardContent>
              <Linha>
                <EtapaBadge etapa="interesse_qualificado" />
                <DonoBadge dono="ia" />
              </Linha>
            </CardContent>
          </Card>
          <Card size="sm">
            <CardHeader>
              <CardTitle>Card compacto</CardTitle>
              <CardDescription>Variante sm para listas densas.</CardDescription>
            </CardHeader>
          </Card>
        </div>
      </Secao>

      <Secao titulo="Badge">
        <Linha>
          {ETAPAS.map((e) => (
            <EtapaBadge key={e.valor} etapa={e.valor} />
          ))}
        </Linha>
        <Linha>
          <DonoBadge dono="ia" />
          <DonoBadge dono="vendedor" />
        </Linha>
        <Linha>
          <Badge>Padrão</Badge>
          <Badge variant="secondary">Secundário</Badge>
          <Badge variant="outline">Contorno</Badge>
          <Badge variant="success">Sucesso</Badge>
          <Badge variant="warning">Atenção</Badge>
          <Badge variant="danger">Erro</Badge>
        </Linha>
      </Secao>

      <Secao titulo="Avatar">
        <Linha>
          <Avatar size="sm"><AvatarFallback>MS</AvatarFallback></Avatar>
          <Avatar><AvatarFallback>JP</AvatarFallback></Avatar>
          <Avatar size="lg"><AvatarFallback>AB</AvatarFallback></Avatar>
        </Linha>
      </Secao>

      <Secao titulo="Dialog">
        <Linha>
          <Dialog>
            <DialogTrigger render={<Button variant="outline">Abrir diálogo</Button>} />
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Devolver ao atendimento da IA?</DialogTitle>
                <DialogDescription>O lead volta para a fila automática.</DialogDescription>
              </DialogHeader>
              <DialogFooter showCloseButton />
            </DialogContent>
          </Dialog>
        </Linha>
      </Secao>

      <Secao titulo="Sheet">
        <Linha>
          <Sheet>
            <SheetTrigger render={<Button variant="outline">Abrir painel lateral</Button>} />
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Detalhes do lead</SheetTitle>
                <SheetDescription>Ficha, conversa e histórico de etapas.</SheetDescription>
              </SheetHeader>
            </SheetContent>
          </Sheet>
        </Linha>
      </Secao>

      <Secao titulo="Tabs">
        <Tabs defaultValue="taxas">
          <TabsList aria-label="Seções de exemplo">
            <TabsTrigger value="taxas">Taxas</TabsTrigger>
            <TabsTrigger value="troca">Troca</TabsTrigger>
            <TabsTrigger value="estoque">Estoque</TabsTrigger>
          </TabsList>
          <TabsContent value="taxas">Conteúdo das taxas.</TabsContent>
          <TabsContent value="troca">Conteúdo da tabela de troca.</TabsContent>
          <TabsContent value="estoque">Conteúdo do estoque.</TabsContent>
        </Tabs>
      </Secao>

      <Secao titulo="Table">
        <Table aria-label="Estoque de exemplo">
          <TableHeader>
            <TableRow>
              <TableHead>Modelo</TableHead>
              <TableHead>Capacidade</TableHead>
              <TableHead className="text-right">Preço</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>iPhone 15</TableCell>
              <TableCell>128 GB</TableCell>
              <TableCell className="text-right font-mono">R$ 4.599,00</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>iPhone 14</TableCell>
              <TableCell>256 GB</TableCell>
              <TableCell className="text-right font-mono">R$ 4.199,00</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Secao>

      <Secao titulo="DataGrid">
        <p className="text-sm text-muted-foreground">
          Células editáveis, erro por célula (aria-invalid), adicionar e remover linha.
        </p>
        <GradeDemo />
      </Secao>

      <Secao titulo="Toast">
        <ToastDemo />
      </Secao>

      <Secao titulo="Skeleton">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-80" />
          <Skeleton className="h-16 w-full" />
        </div>
      </Secao>

      <Secao titulo="EmptyState">
        <EmptyState
          icon={Inbox}
          title="Nenhuma conversa"
          description="Quando um cliente escrever, a conversa aparece aqui."
          action={<Button variant="outline">Abrir simulador</Button>}
        />
      </Secao>
    </div>
  )
}
