# Agente de Atendimento Mobile — Contexto do Projeto

> Documento vivo. É a fonte da verdade do plano, das decisões e do status.
> Atualizado ao final de cada milestone (ver seção **Status**).

---

## 1. O desafio

Processo seletivo: construir uma IA que atende leads de lojas de celular (foco em iPhone, com troca do usado) e entrega a venda pronta para o vendedor.

### Obrigatório
1. Atender o lead e entender qual aparelho ele quer.
2. Consultar o estoque (planilha ou API simulada — aqui: porta + adaptadores, incluindo um ERP simulado).
3. **Só passar preço depois de qualificar**: avaliar o usado (tela, bateria, traseira, câmera), saber a data da compra e a forma de pagamento.
4. Calcular o valor do usado pela tabela de descontos.
5. Passar a conversa para o vendedor com resumo do atendimento, com opção de **assumir** e de **devolver para a IA**.
6. Mover o lead num kanban: `Novo contato → Interesse identificado → Interesse qualificado → Com o vendedor → Venda fechada`.

Canal: WhatsApp (Evolution API) **e** chat web (simulador no painel).

### Diferenciais (em ordem de prioridade)
1. Ler foto do aparelho / print da saúde da bateria.
2. Resposta em áudio (e entender áudio recebido).
3. Distribuição de leads por porcentagem entre vendedores.
4. Follow-up automático.
5. Instagram (só adaptador + documentação; revisão do app Meta não cabe no prazo).

### Entrega
- Repositório com o código (este).
- Link funcionando **ou** vídeo de até 10 min.
- README com: arquitetura e stack (e por quê), custo por conversa e estimativa para 1 mil e 10 mil leads/mês, plano para Black Friday, como colocar uma loja nova no ar em menos de 1 dia.

### Agenda
| Data | Evento |
|---|---|
| Qui 2026-11-19 | Início |
| Sáb 2026-11-21 | Call de 15 min (mostrar andamento: conversa ponta a ponta no chat web + kanban) |
| Seg 2026-11-23 12:00 | **Entrega** |
| Seg 2026-11-23 tarde | Apresentação de 30 min — o avaliador testa a IA ao vivo como cliente |
| Sex 2026-11-27 | Black Friday real (usar como argumento no README) |

### Confidencialidade
O material recebido (vídeo do benchmark, formulários de onboarding, vídeo/PDF da metodologia) é confidencial: serve só como referência de fluxo. **Não copiar telas nem prompts, não commitar esse material.** A metodologia de atendimento do agente é nossa. As planilhas modelo recebidas definem regras de negócio (abaixo); recriamos nossos próprios modelos de importação.

---

## 2. Tese central

**A IA conduz a conversa; o código decide.**

- O LLM conversa, extrai dados para a ficha e chama ferramentas.
- O LLM **nunca** calcula preço, **nunca** move o kanban, **nunca** decide se pode passar preço.
- A trava de preço está nas ferramentas: `calcular_pagamento` / `avaliar_troca` com preço final recusam enquanto a ficha de qualificação estiver incompleta, devolvendo a lista de pendências.
- Consequência: um modelo barato é suficiente → custo por conversa baixo. Escolha do modelo feita por eval, não por achismo.

---

## 3. Regras de negócio (das planilhas modelo)

### 3.1 Tabela de troca (upgrade)
Uma linha por **modelo + capacidade**. Colunas: valor sem detalhes (R$), desconto tela/vidro frontal, desconto vidro traseiro, desconto carcaça marcada, desconto bateria, limite de bateria (%).

- `valor_troca = valor_sem_detalhes − Σ descontos dos problemas relatados`.
- Desconto de bateria só se aplica quando a saúde está **abaixo** do limite (%).
- `0` = problema não desconta. `SEM` = loja não dá valor pelo WhatsApp para aquele problema → resultado "avaliação na loja".
- Capacidade que não está na tabela → usa a **menor capacidade mais próxima**.
- Sempre "avaliação na loja": peça já trocada ou outro defeito (Face ID, **câmera**, alto-falante…), outra marca (a menos que a aba "Outras marcas" esteja preenchida), modelo fora da tabela, valor final ≤ 0.
- A tabela **não tem coluna de câmera**: defeito de câmera cai na regra "outro defeito" → loja.
- Exemplo: iPhone 16 128GB, tela trincada, bateria 79% (limite 80) → 3.100 − 600 − 190 = **R$ 2.310**.
- A avaliação do WhatsApp é **pré-análise**; o valor final é confirmado na loja com o aparelho em mãos (o agente sempre diz isso).

### 3.2 Taxas da maquininha
- Taxa (%) por número de parcelas (1 a 21 + débito) e por bandeira (Mastercard, Visa, Elo, Hipercard, Amex).
- "igual" numa bandeira → usa a taxa da Mastercard.
- `parcela = (preço − desconto − troca − entrada) × (1 + taxa/100) ÷ n`.
- Exemplo: R$ 4.830 em 12x a 10,54% → 4.830 × 1,1054 ÷ 12 = **R$ 444,92**.

### 3.3 Regras de preço (por loja)
- Máximo de parcelas (ex.: 18).
- Repassa taxa ao cliente? (sim/não).
- Desconto Pix/dinheiro (% ou R$, ou "preço à vista já é o Pix").
- Desconto máximo por cliente (ex.: R$ 100), liberado em degraus (ex.: de 50 em 50).
- "Oportunidade única": se a compra prevista está a mais de N dias (ex.: 14), oferecer R$ X (ex.: 100) para antecipar. → **"data da compra" = quando o cliente pretende comprar** (premissa; confirmar com o recrutador).
- Aceita entrada + parcelas no cartão? (sim/não).

### 3.4 Ficha de qualificação (pré-requisito para preço)
Campos obrigatórios:
- Aparelho desejado: modelo, capacidade (cor opcional), item do estoque confirmado.
- Usado (se houver troca): modelo, capacidade, tela, traseira, carcaça, saúde da bateria (%), câmera/outros defeitos, peça já trocada.
- Data prevista da compra.
- Forma de pagamento: Pix/dinheiro, cartão (n parcelas, bandeira), entrada + cartão.

"Sem troca" é uma resposta válida (pula o bloco do usado).

### 3.5 Kanban (derivado, nunca decidido pelo LLM)
| Etapa | Gatilho |
|---|---|
| Novo contato | primeira mensagem |
| Interesse identificado | aparelho desejado definido **e** estoque consultado |
| Interesse qualificado | ficha de qualificação completa |
| Com o vendedor | handoff (automático após preço/intenção de fechar, pedido do cliente, ou vendedor assume) |
| Venda fechada | só o vendedor marca |

Etapas não regridem automaticamente; movimentos manuais no painel respeitam as regras.

### 3.6 Handoff
- Toda conversa tem um **dono**: `ia` ou `vendedor:<id>`.
- **Assumir**: IA silencia. Mensagens do vendedor pelo painel ou direto no celular (Evolution `fromMe`) também pausam a IA.
- **Devolver**: IA volta e lê o que o vendedor falou antes de continuar.
- Resumo do handoff gerado a partir da ficha estruturada + últimas mensagens (aparelho, valor da troca, pagamento, objeções, próximo passo).

---

## 4. Arquitetura

```
 WhatsApp (Evolution) ─┐
 Chat web (simulador) ─┼─► CanalPort (adaptadores) ─► Webhook/API (responde rápido, só enfileira)
 Instagram (futuro)  ──┘                                   │
                                                           ▼
                                  Fila Redis + buffer ~4s por conversa + lock por conversa + idempotência
                                                           │
                                                           ▼
                  ┌──────────── Worker: orquestrador da conversa ───────────────┐
                  │ dono == vendedor? → só persiste                             │
                  │ LLMPort (Claude) + ferramentas → casos de uso → domínio     │
                  │ ficha atualizada → etapa do kanban recalculada              │
                  └──────────────────────────────────────────────────────────────┘
                                                           │
                              Postgres (multi-loja: store_id em tudo) ── SSE ──► Painel Next.js
                                                                                 (kanban, inbox,
                                                                                  onboarding, simulador)
```

### 4.1 Camadas (Clean Architecture / Ports & Adapters)
```
backend/app/
  domain/         # regras puras: dinheiro, troca, pagamento, desconto, ficha, kanban, distribuição. Zero IO.
  application/    # casos de uso + portas (Protocol): EstoquePort, LLMPort, CanalPort, RepositorioPorts, STTPort, TTSPort, RelogioPort
  adapters/
    inbound/      # FastAPI routers, webhooks (Evolution), SSE
    outbound/     # db (SQLAlchemy), estoque (planilha, erp_simulado), llm (anthropic, fake), canal (evolution, webchat), audio
  infra/          # settings, container de dependências, workers (arq), logging
services/erp-mock/ # ERP simulado (FastAPI separado)
frontend/          # Next.js (painel)
infra/             # docker-compose, k6
```
Regra de dependência: `domain` não importa nada do projeto; `application` importa só `domain`; `adapters`/`infra` implementam portas. Verificada por `import-linter` no CI.

### 4.2 Portas principais
| Porta | Adaptadores |
|---|---|
| `EstoquePort` (`buscar`, `obter`) | `PlanilhaAdapter`, `ErpSimuladoAdapter`, (futuro: Bling/Tiny/…) + decorator `EstoqueResiliente` (cache, retry, timeout, fallback) |
| `LLMPort` | `AnthropicAdapter` (principal + modelo reserva), `FakeLLM` (testes) |
| `CanalPort` | `WebChatAdapter`, `EvolutionAdapter`, (`InstagramAdapter` esqueleto) |
| `STTPort` / `TTSPort` | adaptador de API + fake |
| Repositórios | SQLAlchemy + in-memory (testes) |

ERP ainda não definido → porta mínima (`buscar`, `obter`). Capacidades opcionais declaradas (`suporta_reserva`, `suporta_webhook`). Escrita no ERP (reserva/baixa) seria uma `PedidoPort` futura. Todos os adaptadores de estoque passam na **mesma suíte de testes de contrato**.

### 4.3 Painel web
- Next.js (App Router) + TypeScript + Tailwind + **shadcn/ui** como base do design system; tokens em CSS variables; `DESIGN.md` é a fonte da verdade visual.
- Telas: Kanban, Inbox (conversa + ficha + Assumir/Devolver), Onboarding (assistente com grades editáveis + importar xlsx), Simulador de cliente, Configurações.
- Tempo real via SSE do backend.
- Onboarding (loja nova < 1 dia): dados da loja/tom → vendedores e % → regras de preço → taxas → tabela de troca → estoque/ERP + mapeamento de SKU → conectar WhatsApp (QR) → conversa de teste. A config é lida a cada turno: mudou no painel, a IA usa na próxima mensagem.

---

## 5. Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, uv | Async para webhooks/LLM, ecossistema de IA, familiaridade |
| Persistência | Postgres 16, SQLAlchemy 2 async, Alembic | Multi-loja, transações, JSONB para ficha |
| Fila | Redis + arq | Debounce, lock e ordem por conversa, escala horizontal |
| LLM | Anthropic SDK — `claude-sonnet-5-5` vs `claude-haiku-5-5` decidido por eval (configurável por env) | Tool use, visão, prompt caching, fallback de modelo |
| Painel | Next.js + TS + Tailwind + shadcn/ui, TanStack Query, dnd-kit, Vitest + Testing Library | Produtividade, design system consistente |
| WhatsApp | Evolution API (Docker) | Grátis, `fromMe` para pausar IA. Risco: não oficial → chip secundário |
| Testes | pytest, pytest-asyncio, hypothesis (domínio), Vitest, k6 (carga) | TDD |
| Qualidade | ruff, mypy, import-linter, ESLint, GitHub Actions | Erros pegos cedo |
| Execução | docker-compose (Docker no WSL) — roda local na apresentação; túnel (cloudflared/ngrok) só se precisar de link | Simples e reprodutível |

---

## 6. Infra e capacidade

Gargalo **não** é CPU (LLM e STT são APIs): é rate limit do LLM e risco de bloqueio do número WhatsApp.

| Cenário | Máquina |
|---|---|
| Demo / até ~10 mil leads/mês | 2 vCPU, 4 GB RAM, 20–40 GB SSD |
| Black Friday | 4 vCPU, 8 GB, Postgres gerenciado, 2+ workers |
| Muitas lojas | Evolution em máquina própria a partir de dezenas de números |

Conta de pico (estimativa): 1.000 leads/dia numa loja → ~12 mil mensagens; pico de 20% numa hora ≈ 40 msg/min; ~6 s por chamada ao LLM → ~6 chamadas simultâneas.

## 7. Custos (estimativa — validar com dados reais do eval)
Premissas: ~12 mensagens do cliente, ~18 chamadas ao LLM por conversa, ~7k tokens de entrada (maior parte em cache) e ~400 de saída por chamada.

| Modelo | Preço (US$/MTok in/out) | Por conversa | 1 mil leads/mês | 10 mil leads/mês |
|---|---|---|---|---|
| Haiku 5.5 | 0,10 / 0,50 | ~US$ 0,008 | ~US$ 8 | ~US$ 80 |
| Sonnet 5.5 | 2 / 10 (cache read 0,10) | ~US$ 0,14 | ~US$ 140 | ~US$ 1.400 |

+ infra (~US$ 20–50/mês), áudio (STT/TTS — conferir preço), WhatsApp (self-hosted sem custo por mensagem; API oficial cobra templates de follow-up).

## 8. Plano Black Friday
- Webhook só enfileira; workers escalam horizontalmente; lock por conversa mantém ordem.
- LLM: retry com backoff → modelo reserva → "já te respondo" + vendedor.
- k6 simulando 10× o volume; métricas de latência, fila e custo.
- Estoque em cache curto + confirmação antes do preço; pesos de distribuição ajustáveis ao vivo.
- Sentry + logs estruturados com custo por conversa.

---

## 9. Milestones

| # | Milestone | Branch | Meta de data | Status |
|---|---|---|---|---|
| M0 | Fundações | `milestone/m0-fundacoes` | 2026-11-20 | ✅ concluído (PR #45) |
| M1 | Motor de preço (domínio) | `milestone/m1-motor-de-preco` | 2026-11-20 | ✅ concluído (PR em revisão) |
| M2 | Configuração da loja e estoque | `milestone/m2-loja-e-estoque` | 2026-11-20 | ✅ concluído (PR em revisão) |
| M3 | Agente conversacional | `milestone/m3-agente` | 2026-11-21 | ⏳ pendente |
| M4 | Painel web | `milestone/m4-painel` | 2026-11-21 | ⏳ pendente |
| M5 | Handoff, WhatsApp e distribuição | `milestone/m5-handoff-whatsapp` | 2026-11-22 | ⏳ pendente |
| M6 | Diferenciais | `milestone/m6-diferenciais` | 2026-11-22 | ⏳ pendente |
| M7 | Entrega | `milestone/m7-entrega` | 2026-11-23 09:00 | ⏳ pendente |

Issues detalhadas (escopo, critérios de aceite, testes TDD, dependências, onda) estão no GitHub: https://github.com/hOtoch/Agente-atendimento-mobile/issues

### Ondas (issues paralelas = subagentes simultâneos)
| Milestone | Onda 1 | Onda 2 | Onda 3 | Onda 4 |
|---|---|---|---|---|
| M0 | #1 backend, #2 frontend, #3 infra | #4 CI, #5 banco | | |
| M1 | #6 value objects, #46 CI exige integração | #7 troca, #8 pagamento, #9 desconto, #10 ficha/trava, #11 kanban | | |
| M2 | #12 config loja, #13 EstoquePort, #14 ERP simulado | #15 adaptador ERP, #16 resiliência, #17 importador xlsx, #18 seed demo | | |
| M3 | #19 LLMPort, #20 canal web, #21 fila | #22 ferramentas, #23 prompt | #24 orquestrador | #25 eval |
| M4 | #26 design system, #27 API painel + SSE | #28 kanban, #29 inbox, #30 onboarding, #31 simulador | | |
| M5 | #32 handoff, #33 Evolution, #34 distribuição % | #35 notificação + QR | | |
| M6 | #36 visão, #37 STT, #38 TTS, #39 follow-up | #40 Instagram | | |
| M7 | #41 carga k6, #42 custos | #43 README, #44 roteiro demo | | |

Para a call de sábado: M0–M3 completos + kanban (M4) já mostrando a conversa ponta a ponta no chat web.

---

## 10. Decisões registradas
| Data | Decisão | Motivo |
|---|---|---|
| 2026-11-19 | Código decide preço/kanban/trava; LLM só conversa e chama ferramentas | Robustez no teste ao vivo; modelo barato viável |
| 2026-11-19 | Onboarding e planilhas no painel (grade editável + importar xlsx) | Loja faz tudo sozinha; "loja nova < 1 dia" |
| 2026-11-19 | Sem Chatwoot no PS; inbox própria no painel. Chatwoot citado no README como caminho de produção | Peso/tempo; handoff é requisito central |
| 2026-11-19 | Estoque via porta + adaptadores (ERP ainda indefinido), ERP simulado com falhas | Troca de ERP sem tocar no agente |
| 2026-11-19 | Roda local (docker-compose) na apresentação; vídeo de backup | Evolution conecta de dentro para fora, sem túnel |
| 2026-11-19 | Postgres local + SSE em vez de Supabase | Tudo local, menos dependências |
| 2026-11-20 | Worktrees dos subagentes criadas à mão em `.worktrees/` (sem isolação automática) | Repo aninhado em outro repo git; isolação automática apontava para o repo errado |
| 2026-11-20 | Evolution API `evoapicloud/evolution-api:v2.3.7` (sobrescrevível por `EVOLUTION_IMAGE`) | Imagem `atendai/*` não está mais disponível |
| 2026-11-20 | Frontend: Next 16, React 19, Tailwind 4 (config em CSS), shadcn (base-nova), Vitest 5; `.npmrc` com `legacy-peer-deps` | Versões estáveis atuais; conflito de peers do shadcn |
| 2026-11-20 | Testes de integração criam um banco Postgres isolado por teste e são pulados se o banco de teste estiver fora | Isolamento total entre subagentes paralelos |
| 2026-11-20 | Idempotência de mensagens por `(canal, id_externo)` com `ON CONFLICT DO NOTHING` | Webhooks duplicados não duplicam mensagens |
| 2026-11-20 | `leads.etapa` como texto livre no banco; validação no domínio | Schema não acopla à lista de etapas |
| 2026-11-20 | Ficha guarda dados PARCIAIS (tipos próprios, campos Optional); troca e pagamento recebem dados COMPLETOS; a conversão ficha → `CondicaoUsado`/`FormaPagamento` fica na aplicação (M3) | Módulos de domínio independentes e paralelizáveis |
| 2026-11-20 | Kanban recebe `FatosDoLead` (booleanos), não a ficha; nunca regride sozinho; "Venda fechada" só manual por vendedor | Etapa é consequência de fatos, nunca do LLM |
| 2026-11-20 | Precedência da troca: peça trocada → outro defeito/câmera → modelo/marca fora da tabela → capacidade abaixo → SEM relatado → valor ≤ 0 | Defeitos mandam para a loja seja qual for o modelo |
| 2026-11-20 | Desconto Pix incide sobre a base já com desconto, troca e entrada; só na forma Pix | Premissa — confirmar com a loja |
| 2026-11-20 | Oportunidade única soma por fora do teto de desconto (configurável `conta_no_teto`) | Regra das planilhas não define; default mais simples de explicar |
| 2026-11-20 | Parse de dinheiro pt-BR: `"2.310"` = 2310; ponto decimal só fora do padrão de milhar | Entrada típica de lojista |
| 2026-11-20 | SEM no banco = `desconto_x NULL` + `desconto_x_sem true` (CHECK exclusivo); "igual" = linha de taxa com `taxa_pct NULL` | R$ 0, SEM e "igual" nunca se confundem |
| 2026-11-20 | Validação de config na aplicação (comandos primitivos → domínio), erros como `ErroCampo(caminho, mensagem)`; 422 uniforme `{"erros": [...]}` | Domínio nunca estoura 500; painel mostra erro na célula |
| 2026-11-20 | Importação xlsx: `validar` (padrão) nunca grava; `aplicar` valida tudo e grava numa transação; erros apontam a célula (`troca!D7`); planilha vazia é erro | Não apagar config por engano |
| 2026-11-20 | Estoque: `PlanilhaAdapter(FonteEstoqueLocalSql)` lê o estoque do banco; `ErpSimuladoAdapter` usa mapeamento de SKU da loja e só cai no parser heurístico com confiança alta; tudo envolvido por `EstoqueResiliente` | Troca de fonte sem tocar no agente |
| 2026-11-20 | Seed da loja demo com `LOJA_DEMO_ID` fixo, gravado pelos casos de uso; iPhone 16 128GB novo a R$ 4.830 (casa com o exemplo da parcela) | Demo coerente com os exemplos oficiais |

## 11. Questões em aberto (perguntar ao recrutador)
1. "Data da compra" = quando pretende comprar (premissa atual) ou quando comprou o usado?
2. Teste ao vivo será pelo WhatsApp ou pode ser chat web?
3. Existe formato de planilha de estoque ou definimos o nosso?
4. Qual ERP (quando souber).

---

## 12. Status
_Atualizado ao final de cada milestone._

- **2026-11-19** — Plano, CLAUDE.md, milestones e issues criados. Próximo: M0.
- **2026-11-20 — M0 Fundações concluído** (#1–#5).
  - Backend FastAPI com camadas verificadas pelo import-linter, `/health`, settings.
  - Banco SQLAlchemy async + Alembic com schema multi-loja: lojas, vendedores, leads, conversas, mensagens, fichas, eventos.
  - Frontend Next.js com tokens claro/escuro, layout com sidebar e teste anti-cor-hardcoded.
  - docker-compose com Postgres dev/teste, Redis e Evolution, mais smoke test.
  - CI com jobs de backend, frontend e infra.
  - Testes: backend 7 (3 de integração), frontend 29.
  - Pontos de atenção:
    - Defaults de settings alinhados ao `.env.example`.
    - `npm audit` com avisos não tratados.
    - 1 warning do Starlette TestClient no pytest.
    - Evolution leva ~60 s no primeiro boot.
    - Webhook global da Evolution desligado até o M5.
  - Próximo: M1 Motor de preço.
- **2026-11-20 — M1 Motor de preço concluído** (#6–#11, #46).
  - Domínio puro em `backend/app/domain/`: `valores` (Dinheiro, Capacidade, ModeloAparelho com 35 iPhones, Bandeira), `troca`, `pagamento`, `desconto`, `ficha` (pendências + `pode_passar_preco`, serialização JSONB) e `kanban`.
  - Exemplos oficiais cobertos por teste: troca do iPhone 16 128GB = R$ 2.310; 12x de R$ 4.830 a 10,54% = R$ 444,92.
  - CI exige os testes de integração (`EXIGIR_INTEGRACAO=1`); teste automatizado do contrato de camadas.
  - Testes: backend 362, com propriedades hypothesis em dinheiro, desconto, ficha e kanban.
  - Pontos de atenção: premissas do Pix e da oportunidade única (ver decisões); conversão ficha → entradas de cálculo pendente para o M3.
  - Próximo: M2 Loja e estoque.
- **2026-11-20 — M2 Loja e estoque concluído** (#12–#18).
  - Configuração da loja: migration 0002 (perfil, regras de preço, taxas, tabela de troca, estoque local, mapeamento de SKU), casos de uso com validação por campo, checklist de onboarding e API REST `/lojas/{id}/config/*`.
  - Estoque: `EstoquePort` + suíte de contrato reutilizável, `PlanilhaAdapter` sobre o banco, `ErpSimuladoAdapter` com parser de nomes "sujos" (39 celulares do ERP, acessórios ignorados) e decorator `EstoqueResiliente`.
  - ERP simulado em `services/erp-mock` (porta 8090), no compose, no smoke e no CI.
  - Importador xlsx (`POST /lojas/{id}/importar/{tipo}`) e modelos vazios em `docs/modelos/`.
  - Seed da loja demo: 3 vendedores (50/30/20), 95 taxas, 89 linhas de troca, 28 itens de estoque; checklist 100%.
  - Testes: backend 621, erp-mock 35.
  - Pontos de atenção:
    - O cache do `EstoqueResiliente` não tem limite de tamanho.
    - `skus_nao_mapeados` do adaptador do ERP fica em memória.
    - Ainda não há CRUD de vendedores (só validação de pesos).
    - `oportunidade_conta_no_teto` não tem pergunta na planilha (fixo em `False`).
  - Próximo: M3 Agente conversacional.
