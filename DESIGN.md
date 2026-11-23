# DESIGN.md — Painel do Agente de Atendimento Mobile

Fonte da verdade visual do frontend (`frontend/`). Em conflito com qualquer outro arquivo, este vence.

## 1. Direção visual

Painel **operacional**: sóbrio, denso, legível, em **pt-BR**. Quem usa é vendedor e gerente de loja, em sessões longas, alternando entre kanban, conversas e configuração.

- **Sóbrio**: superfícies neutras levemente azuladas; cor é informação (etapa, estado), não decoração.
- **Denso**: texto base 14px, espaçamento em múltiplos de 4px, listas e cards compactos. Muita informação sem rolagem desnecessária.
- **Legível**: contraste alto no texto, hierarquia por peso e tamanho (não por cor), ícones sempre acompanhados de rótulo na navegação.
- **Tema claro e escuro** desde o início; ambos usam os mesmos nomes de token.
- Fonte: Geist (sans) e Geist Mono (números, códigos, IDs). Idioma da interface e datas: pt-BR; moeda em R$.

## 2. Tokens

Definidos **somente** em `frontend/src/styles/tokens.css` (`:root` = claro, `.dark` = escuro) e ligados ao Tailwind em `frontend/src/app/globals.css` (`@theme inline`). Valores em `oklch`.

| Grupo | Tokens | Classe Tailwind |
|---|---|---|
| Superfície e texto | `--background`, `--foreground`, `--card`, `--popover`, `--muted`, `--muted-foreground`, `--secondary`, `--accent` (+ `-foreground`) | `bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`... |
| Ação principal | `--primary`, `--primary-foreground` | `bg-primary`, `text-primary-foreground` |
| Bordas e foco | `--border`, `--input`, `--ring` | `border-border`, `ring-ring` |
| Estados | `--success`, `--warning`, `--danger` (+ `-foreground`); `--destructive` é alias de `--danger` | `bg-success`, `text-warning`, `border-danger`... |
| Etapas do kanban | `--stage-novo-contato`, `--stage-interesse-identificado`, `--stage-interesse-qualificado`, `--stage-com-vendedor`, `--stage-venda-fechada` | `bg-stage-novo-contato`... |
| Sidebar | `--sidebar`, `--sidebar-foreground`, `--sidebar-accent`, `--sidebar-border`, `--sidebar-primary`, `--sidebar-ring` | `bg-sidebar`, `border-sidebar-border`... |
| Gráficos | `--chart-1` a `--chart-5`: ordem categórica fixa azul, laranja, violeta, verde, cinza (valores próprios, não derivados das etapas) | `bg-chart-1`, `fill-chart-2`... |
| Raio | `--radius` (0,5rem); escala `rounded-sm` a `rounded-4xl` derivada | `rounded-md`, `rounded-lg` |
| Espaçamento | `--space-unit` (0,25rem) alimenta `--spacing` do Tailwind | `p-4`, `gap-2`, `mb-6` |
| Tipografia | `--font-size-base` (0,875rem), `--line-height-base`; fontes `--font-sans`, `--font-mono` | `text-base`, `font-sans`, `font-mono` |
| Layout | `--sidebar-width` | `w-sidebar` |

**Cores de gráfico.** Séries entram sempre na ordem `chart-1`, `chart-2`, `chart-3`, `chart-4` (a cor segue a entidade, nunca o ranking) e nunca se geram matizes novos: acima de 4 séries, agrupe em "Outros" ou separe em gráficos. Os valores foram validados com o `validate_palette` da skill `dataviz` (OKLab ΔE ≥ 8 sob protanopia/deuteranopia nos pares vizinhos, ≥ 15 em visão normal, contraste ≥ 3:1 contra o card, faixa de luminosidade do tema): claro `oklch(0.62 0.13 235)`, `(0.64 0.15 62)`, `(0.58 0.15 285)`, `(0.56 0.14 150)`; escuro com L entre 0,65 e 0,66. Funil usa os tokens `stage-*` (a etapa é a entidade). Série única = uma cor. Mapa de calor = `chart-1` em degraus de opacidade.

Para criar um token novo: declare em `tokens.css` nos **dois** temas, ligue em `globals.css` e documente aqui.

## 3. Regras de uso

1. **Nunca valores hardcoded.** Sem `#hex`, `rgb()/hsl()`, classes arbitrárias de cor (`bg-[#...]`) nem paleta crua do Tailwind (`bg-blue-500`, `text-white`). Use as classes semânticas da tabela acima. O teste `src/design-system.test.ts` varre `src/**/*.{ts,tsx}` e quebra o build se isso ocorrer.
2. **Componentes reutilizáveis em `frontend/src/components/ui`** (base shadcn/ui; adicione com `npx shadcn@latest add <componente>`). Se dois lugares precisam do mesmo elemento visual, ele vai para `ui`, não para a feature.
3. **Features em `frontend/src/features/*`** (ex.: `features/kanban`, `features/conversas`). Features compõem componentes de `ui` e não definem estilos próprios de cor, raio ou fonte.
4. **Layout estrutural** (shell, sidebar) fica em `frontend/src/components/layout`.
5. **Cor comunica estado**: etapa do kanban usa `stage-*`; sucesso, atenção e erro usam `success`, `warning`, `danger`. Não reutilize essas cores como decoração.
6. **Tema escuro** é a classe `dark` no `<html>`; nenhum componente ramifica por tema (`dark:` só em casos que os tokens não resolvem, e nunca com cor crua).
7. **Acessibilidade**: foco visível (`ring`), `aria-current="page"` na rota ativa, `aria-label` em landmarks, texto em pt-BR.
8. **Texto da interface** em pt-BR, com acentos; identificadores de código seguem as convenções do `CLAUDE.md`.

## 9. Componentes base (`frontend/src/components/ui`)

Vitrine viva em **`/design`** (todos os componentes e estados; o botão no topo alterna tema claro/escuro). Features importam só de `@/components/ui/...`.

| Componente | Arquivo | Notas |
|---|---|---|
| Button | `button.tsx` | variantes `default`, `secondary`, `outline`, `ghost`, `destructive`, `link`; tamanhos `xs` a `lg` e `icon*` |
| Input, Textarea | `input.tsx`, `textarea.tsx` | erro via `aria-invalid` (borda `danger`); sempre associar `<label htmlFor>` |
| Select | `select.tsx` | base-ui; `SelectTrigger` precisa de `aria-labelledby` ou `aria-label` |
| Card | `card.tsx` | `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`; `size="sm"` para listas densas |
| Badge | `badge.tsx` | variantes semânticas `success`, `warning`, `danger`; `EtapaBadge etapa=...` (5 etapas, tokens `stage-*`); `DonoBadge dono="ia"` ou `dono="vendedor"` |
| Avatar | `avatar.tsx` | `Avatar`, `AvatarFallback` (iniciais); tamanhos `sm`, `default`, `lg` |
| Dialog | `dialog.tsx` | foco entra no diálogo e volta ao gatilho; Esc fecha; `DialogFooter showCloseButton` |
| Sheet | `sheet.tsx` | painel lateral (`side`), mesmo contrato de acessibilidade do Dialog |
| Tabs | `tabs.tsx` | `role` tablist/tab/tabpanel; setas navegam |
| Table | `table.tsx` | tabela somente leitura |
| DataGrid | `data-grid.tsx` | tabela editável (base do onboarding): colunas tipadas, `onChange` por célula, erro por célula, adicionar/remover linha |
| Campo | `campo.tsx` | rótulo + controle + dica + erro; `children` recebe `{ id, aria-labelledby, aria-invalid, aria-describedby }` para espalhar no `Input`, `Textarea` ou `SelectTrigger` |
| SeletorCampo | `seletor-campo.tsx` | `Select` de lista fechada pronto para dentro de um `Campo`: `controle` (do `Campo`), `valor`, `itens` `{ value, label }[]`, `aoMudar(valor)` |
| Toast | `toast.tsx` | `<Toaster />` no layout raiz; `useToast()` com `sucesso`, `aviso`, `erro`, `info`, `fechar` (pt-BR) |
| Skeleton | `skeleton.tsx` | `aria-hidden`; pulsa sobre `bg-muted` |
| MessageBubble | `message-bubble.tsx` | balão de conversa: `lado` (`cliente`/`atendente`, quem escreveu), `tipo` (`texto`, `imagem`, `audio` com `<audio controls>`), `texto`, `midiaUrl`, `horario` (HH:mm pt-BR), `autor`, `erro`; `perspectiva` define quem está olhando (as mensagens dele ficam à direita e em `primary`; padrão `atendente` para a inbox, o simulador usa `cliente`) |
| EmptyState | `empty-state.tsx` | ícone decorativo, título (h3), descrição e ação |
| Chart | `chart.tsx` | base shadcn sobre recharts: `ChartContainer` (`config` {série: rótulo + token de cor}, `rotulo` vira `aria-label`, `altura`), `ChartTooltipContent`, `ChartLegendContent`; cor só por `var(--color-<série>)` |
| GraficoSerie, GraficoBarras | `graficos.tsx` | linha/área por dia (uma série = área; várias = linhas, legenda, lacuna em `null`, último valor rotulado) e barras horizontais com valor na ponta; teclado via `accessibilityLayer` |
| CartaoGrafico | `cartao-grafico.tsx` | moldura do gráfico: título (h3), descrição curta e `<details>` "Ver dados em tabela" (`tabela` {colunas, linhas}); `role="region"` nomeada |
| StatTile | `stat-tile.tsx` | KPI: `rotulo`, `valor` (`null` vira "—" + `dicaSemValor`), `variacao` {texto, tom `bom`/`ruim`/`neutro`, direcao, descricao para leitor de tela}; `null` = "Sem comparação"; `children` para um `Medidor` |
| Medidor | `medidor.tsx` | barra de proporção (`role="meter"`) sobre trilha neutra |
| MapaCalor | `mapa-calor.tsx` | grade linhas x colunas como `<table>` (valor em texto para leitor de tela, `title` com a descrição), 4 degraus de `chart-1` |

### Gráficos

Regras do método `dataviz`, já embutidas nos componentes: marcas finas (linha 2px, barra ≤ 24px com ponta de 4px arredondada, área a ~10%), grade só horizontal em hairline, legenda sempre que houver 2+ séries, valor rotulado só no último ponto/ponta da barra, texto em `foreground`/`muted-foreground` (nunca na cor da série), nunca dois eixos Y (duas grandezas = dois gráficos), cor de bom/ruim só nos indicadores (`success`/`danger`) e sempre com seta e texto. Todo gráfico tem título, descrição e tabela equivalente.

### Etapas e donos

`@/lib/etapas` exporta `ETAPAS` (valor, rótulo pt-BR, token) na ordem do funil, espelhando `Etapa` do backend (`novo_contato`, `interesse_identificado`, `interesse_qualificado`, `com_o_vendedor`, `venda_fechada`). O ponto colorido do badge usa `--stage-*`; o texto fica em `foreground` para manter o contraste. Dono: `ia` (`primary` suave) e `vendedor` (`secondary`).

### DataGrid

- `columns`: `{ key, header, type?: "text" | "number" | "select", options?, readOnly?, align?, widthClass? }[]`; `rows`: `Record<string, string | number | null>[]`.
- Controlado: o pai guarda `rows`. `onChange({ rowIndex, columnKey, value, row })` dispara a cada edição; coluna `number` aceita vírgula e entrega `number | null`.
- `errors`: `{ [linha]: { [coluna]: mensagem } }` (linha 0-based). `errosDeCelulas([{ linha, coluna, mensagem }])` monta o mapa a partir de erros da API. A célula recebe `aria-invalid` e `aria-describedby` apontando para a mensagem (cor `danger`).
- `onAddRow` e `onRemoveRow(rowIndex)` ligam os botões "Adicionar linha" e "Remover linha N"; sem os callbacks, os botões não aparecem.
- Cada campo tem rótulo acessível `"<Coluna>, linha <n>"`.
