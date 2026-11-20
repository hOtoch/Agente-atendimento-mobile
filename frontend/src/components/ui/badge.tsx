import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"
import { ETAPAS, type Etapa } from "@/lib/etapas"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
        success: "bg-success/15 text-foreground border-success/40",
        warning: "bg-warning/20 text-foreground border-warning/50",
        danger: "bg-danger/15 text-foreground border-danger/40",
        ia: "bg-primary/10 text-foreground border-primary/30",
        vendedor: "bg-secondary text-secondary-foreground border-border",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

/* Classes literais (o Tailwind só gera o que enxerga no código). Ponto colorido + texto em foreground. */
const ETAPA_CLASSES: Record<Etapa, string> = {
  novo_contato:
    "gap-1.5 border-stage-novo-contato/40 bg-stage-novo-contato/15 text-foreground before:size-1.5 before:rounded-full before:bg-stage-novo-contato",
  interesse_identificado:
    "gap-1.5 border-stage-interesse-identificado/40 bg-stage-interesse-identificado/15 text-foreground before:size-1.5 before:rounded-full before:bg-stage-interesse-identificado",
  interesse_qualificado:
    "gap-1.5 border-stage-interesse-qualificado/40 bg-stage-interesse-qualificado/15 text-foreground before:size-1.5 before:rounded-full before:bg-stage-interesse-qualificado",
  com_o_vendedor:
    "gap-1.5 border-stage-com-vendedor/40 bg-stage-com-vendedor/15 text-foreground before:size-1.5 before:rounded-full before:bg-stage-com-vendedor",
  venda_fechada:
    "gap-1.5 border-stage-venda-fechada/40 bg-stage-venda-fechada/15 text-foreground before:size-1.5 before:rounded-full before:bg-stage-venda-fechada",
}

function EtapaBadge({
  etapa,
  className,
  ...props
}: { etapa: Etapa } & Omit<React.ComponentProps<typeof Badge>, "variant" | "children" | "render">) {
  const rotulo = ETAPAS.find((e) => e.valor === etapa)?.rotulo ?? etapa
  return (
    <Badge
      variant="outline"
      data-etapa={etapa}
      className={cn(ETAPA_CLASSES[etapa], className)}
      {...props}
    >
      {rotulo}
    </Badge>
  )
}

type Dono = "ia" | "vendedor"

function DonoBadge({
  dono,
  className,
  ...props
}: { dono: Dono } & Omit<React.ComponentProps<typeof Badge>, "variant" | "children" | "render">) {
  return (
    <Badge variant={dono} data-dono={dono} className={className} {...props}>
      {dono === "ia" ? "IA" : "Vendedor"}
    </Badge>
  )
}

export { Badge, badgeVariants, DonoBadge, EtapaBadge }
export type { Dono, Etapa }
