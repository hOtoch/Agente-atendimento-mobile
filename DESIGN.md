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
| Gráficos | `--chart-1` a `--chart-5` (derivados das etapas) | `bg-chart-1`... |
| Raio | `--radius` (0,5rem); escala `rounded-sm` a `rounded-4xl` derivada | `rounded-md`, `rounded-lg` |
| Espaçamento | `--space-unit` (0,25rem) alimenta `--spacing` do Tailwind | `p-4`, `gap-2`, `mb-6` |
| Tipografia | `--font-size-base` (0,875rem), `--line-height-base`; fontes `--font-sans`, `--font-mono` | `text-base`, `font-sans`, `font-mono` |
| Layout | `--sidebar-width` | `w-sidebar` |

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
