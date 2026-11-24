# Agente de Atendimento Mobile

Uma IA que atende leads de lojas de celular (foco em iPhone, com troca do usado; também atende outras marcas), entende o aparelho desejado, consulta o estoque, qualifica o cliente, calcula troca e parcelas, fecha o acordo e entrega a venda pronta para o vendedor, com resumo, opção de assumir a conversa e opção de devolvê-la para a IA.

Link do Video: https://drive.google.com/file/d/1kEIpaAoYaiU3UbCPykw6S0TK0QW-jVX6/view?usp=sharing


**Neste README**, na ordem pedida:

1. [Arquitetura e stack (e por quê)](#1-arquitetura-e-stack-e-por-quê)
2. [Custo por conversa e estimativa para 1 mil e 10 mil leads/mês](#2-custo-por-conversa-e-estimativa-para-1-mil-e-10-mil-leadsmês)
3. [Plano para aguentar a Black Friday](#3-plano-para-aguentar-a-black-friday)
4. [Loja nova no ar em menos de 1 dia](#4-loja-nova-no-ar-em-menos-de-1-dia)

Depois: [o que já funciona](#o-que-já-funciona), [integração com o ERP](#integração-com-o-erp-mercado-phone), [como rodar local](#como-rodar-local), [qualidade](#qualidade), [decisões](#decisões-e-trade-offs), [riscos](#riscos-conhecidos-e-pendências) e [mapa de documentos](#mapa-de-documentos).

## O que já funciona

- **Atendimento**: entende o aparelho, consulta o estoque (capacidade primeiro, depois cor), qualifica (usado: tela, traseira, carcaça, bateria, câmera; data da compra; forma de pagamento) e só então passa preço, troca e parcelas.
- **Fechamento pela IA**: quando o cliente aceita, a IA registra o acordo, combina endereço/horário, passa a chave Pix da loja, agradece e entrega ao vendedor com o acordo no resumo.
- **Canais**: WhatsApp via Evolution API e chat web (simulador no painel e página pública `/chat/{loja}`). Instagram: adaptador testado com fixtures e com teste de paridade com o WhatsApp, não ligado à Graph API; plano de ação em [docs/instagram.md](docs/instagram.md).
- **Kanban** de 5 etapas (`Novo contato → Interesse identificado → Interesse qualificado → Com o vendedor → Venda fechada`), atualizado em tempo real por SSE.
- **Inbox** com ficha do cliente, resumo do handoff, **Assumir** e **Devolver para a IA**. O vendedor também pode responder direto pelo celular: a IA percebe o `fromMe` e silencia.
- **Distribuição de leads por porcentagem** entre vendedores (ex.: 50/30/20), com resumo e link da conversa enviados ao WhatsApp do vendedor.
- **Visão**: lê foto do aparelho e print da saúde da bateria.
- **Áudio**: entende áudio recebido (STT) e, se a loja quiser, responde a áudio só com nota de voz (TTS); o texto sai só se a voz falhar ([docs/audio.md](docs/audio.md)).
- **Follow-up automático** para o lead que parou de responder (padrão desligado; configurável por loja).
- **Onboarding** de loja no painel: 9 passos com importação das planilhas modelo.
- **Painel de desempenho da IA** (`/desempenho`): volume, funil, handoffs por motivo, custo e tokens por modelo, latência, erros, aparelhos procurados ([docs/desempenho.md](docs/desempenho.md)).
- **ERP Mercado Phone**: estoque, preços e vendedores sincronizados do ERP real (só leitura validada).
- **Qualidade**: 2.641 testes automatizados, eval do agente com LLM real, CI com lint, tipos e verificação de camadas.

O que **não** foi validado: conversa ponta a ponta com um celular pareado de verdade (formato real dos webhooks, mídia, entrega) e Instagram na Graph API. Ver [Riscos e pendências](#riscos-conhecidos-e-pendências).

---

## 1. Arquitetura e stack (e por quê)

### A tese: a IA conduz, o código decide

O LLM conversa, extrai dados para a ficha e chama ferramentas. Ele **nunca** calcula preço, nunca move o kanban e nunca decide se pode passar preço. Isso vira regra de domínio com teste, não instrução de prompt. Exemplos concretos:

| Decisão | Quem decide | Como |
|---|---|---|
| Pode passar preço? | Código | `consultar_estoque` nunca devolve preço. Troca, parcelas e desconto só saem de `calcular_proposta`/`liberar_desconto`, que **recusam** enquanto a ficha tiver pendências e devolvem a lista do que falta (`domain/ficha.py`). |
| Valor do usado | Código | `valor_troca = valor sem detalhes − Σ descontos`; desconto de bateria só abaixo do limite; `SEM`, peça trocada, câmera/outro defeito, modelo fora da tabela ou valor ≤ 0 mandam para "avaliação na loja" (`domain/troca.py`). Exemplo testado: iPhone 16 128GB, tela trincada, bateria 79% = R$ 2.310. |
| Parcela | Código | `(preço − desconto − troca − entrada) × (1 + taxa/100) ÷ n` em `Decimal` com `ROUND_HALF_UP`. Exemplo testado: R$ 4.830 em 12x a 10,54% = R$ 444,92. |
| Desconto | Código | Liberado em degraus até um **teto** por cliente, configurado pela loja. O LLM pede, o código concede ou nega. |
| Etapa do kanban | Código | Derivada de fatos (aparelho definido, estoque consultado, ficha completa, handoff). Nunca regride sozinha; "Venda fechada" só o vendedor marca (`domain/kanban.py`). |
| Leitura de imagem | Código | O LLM devolve a leitura estruturada (modelo, bateria, danos, confiança). O código só grava na ficha com **confiança ≥ 0,8**; abaixo disso, devolve a pergunta de confirmação ao cliente. |
| Follow-up | Código | `domain/followup.py` decide se, quando e quantas vezes (etapa, horas parado, tentativas, intervalo, horário comercial, dono = IA). O LLM só redige a mensagem, sem valores. |
| Resumo do handoff | Código | Aparelho, troca, pagamento e acordo vêm da ficha; o resumo sai completo mesmo sem o LLM. |

Consequência prática: como o modelo só conversa, um modelo barato basta (ver [custo](#2-custo-por-conversa-e-estimativa-para-1-mil-e-10-mil-leadsmês)). E o eval tem checagens automáticas que reprovam a conversa se aparecer um valor em reais que não veio de uma ferramenta.

### Visão geral

```mermaid
flowchart LR
    subgraph Canais
        WA[WhatsApp<br/>Evolution API]
        WEB[Chat web<br/>simulador / página pública]
        IG[Instagram<br/>esqueleto]
    end

    WA -->|webhook| API
    WEB -->|REST| API
    IG -.->|futuro| API

    subgraph Backend[Backend Python]
        API[FastAPI<br/>valida, grava, enfileira<br/>responde rápido]
        FILA[(Redis + arq<br/>debounce 10 s<br/>trava por conversa<br/>idempotência)]
        WORKER[Worker<br/>ProcessarConversa]
        LLM[LLMPort<br/>Anthropic ou OpenAI<br/>+ ferramentas]
        DOM[Domínio<br/>troca, pagamento, desconto,<br/>ficha, kanban, distribuição, follow-up]
    end

    API --> FILA --> WORKER
    WORKER <--> LLM
    WORKER --> DOM
    LLM -->|chama ferramentas| DOM

    subgraph Adaptadores
        PG[(Postgres<br/>multi-loja)]
        EST[EstoquePort<br/>planilha no banco /<br/>ERP simulado / Mercado Phone]
        CAN[CanalPort<br/>Evolution / webchat / Instagram]
        AUD[STT / TTS<br/>OpenAI]
    end

    WORKER --> PG
    WORKER --> EST
    WORKER --> CAN
    WORKER --> AUD
    CAN --> WA
    CAN --> WEB

    PNL[Painel Next.js<br/>kanban, inbox, onboarding,<br/>simulador, desempenho]
    PNL <-->|REST| API
    API -->|SSE via Redis pub/sub| PNL
```

**Fluxo de uma mensagem**: o webhook (ou a API do chat web) normaliza, grava com idempotência por `(canal, id_externo)` e só enfileira. O arq espera 10 s sem mensagem nova para juntar a rajada do cliente num único turno (debounce; `FILA_JANELA_S`) e uma trava por conversa no Redis garante um worker por vez e a ordem das mensagens. O `ProcessarConversa` roda o laço LLM + ferramentas, as ferramentas chamam casos de uso que chamam o domínio, o kanban é recalculado e a resposta sai pelo canal de origem; se chegou mensagem nova no meio, a resposta é descartada e o turno roda de novo. Se a conversa pertence a um vendedor, o worker só persiste. Todo `ErroLLM` (inclusive falta de chave) vira mensagem de espera e handoff para um vendedor: o cliente nunca fica sem resposta.

### Camadas (Clean Architecture / Ports & Adapters)

```
backend/app/
  domain/        regras puras (dinheiro, troca, pagamento, desconto, ficha, kanban, distribuição, follow-up). Sem IO.
  application/   casos de uso e portas (typing.Protocol). Importa só domain.
  adapters/      inbound (FastAPI, webhooks, SSE) e outbound (db, estoque, llm, canal, áudio).
  infra/         settings, composição das dependências, fila e worker.
services/erp-mock/   ERP simulado (FastAPI separado)
frontend/            painel Next.js
infra/               docker-compose, smoke, teste de carga k6
```

A regra de dependência é verificada pelo **import-linter** (`uv run lint-imports`), que quebra o build do CI se `domain` importar o projeto ou bibliotecas de infraestrutura, ou se `application` importar `adapters`/`infra`. Os adaptadores de uma mesma porta (ex.: os de estoque) passam na **mesma suíte de testes de contrato**. Por isso trocar de LLM, de ERP ou de canal é escrever um adaptador, sem tocar nas regras de negócio.

### Stack e por quê

| Camada | Escolha | Por quê |
|---|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, `uv` | Async para webhooks e chamadas ao LLM; ecossistema de IA; contrato OpenAPI que gera o cliente TypeScript do painel. |
| Banco | Postgres 16, SQLAlchemy 2 async, Alembic | Multi-loja (`loja_id` em tudo), transações, JSONB para a ficha, migrations versionadas. |
| Fila | Redis + arq | Debounce, trava e ordem por conversa; escala horizontal subindo mais workers; o mesmo Redis serve o pub/sub do SSE. |
| LLM | Anthropic SDK; Haiku 5.5 e Sonnet 5.5 (configuráveis por env); prompt caching. Alternativa: OpenAI (`LLM_PROVIDER=openai`, `gpt-4.1-mini` com reserva `gpt-4o-mini`, via `httpx`) | Tool use e visão nativos; **modelo reserva** em 429/5xx/rede; o cache do prefixo (ferramentas + system + conversa) corta o custo de entrada. Modelo escolhido por eval, não por achismo. O provedor é só um adaptador do `LLMPort`: trocar não mexe no domínio nem nas ferramentas. |
| WhatsApp | Evolution API v2 self-hosted (Docker) | Sem custo por mensagem, conecta por QR code, entrega `fromMe` (a IA silencia quando o vendedor digita no celular). Risco: não é a API oficial. |
| ERP | Mercado Phone pelo servidor MCP da plataforma, atrás de `EstoquePort` | Estoque e preço reais sem a IA tocar no ERP; allowlist de ferramentas; cache, retry, timeout e fallback no decorator `EstoqueResiliente`. |
| Tempo real | SSE (`/lojas/{id}/eventos`) sobre Redis pub/sub | Unidirecional basta para o painel; sem websockets nem serviço externo (descartamos Supabase para rodar tudo local). |
| Painel | Next.js 16, React 19, Tailwind 4, shadcn/ui, dnd-kit, Vitest + Testing Library | Produtividade; **design system** com tokens (CSS variables) e componentes próprios, sem cor ou espaçamento hardcoded (`DESIGN.md`). |
| Áudio | OpenAI `gpt-4o-mini-transcribe` e `gpt-4o-mini-tts` via `httpx` | Bom português, barato, sem SDK novo; chave opcional (sem ela o agente pede ao cliente que digite). |
| Testes | pytest (+ hypothesis no domínio), Vitest, k6 | TDD; propriedades para dinheiro e desconto; carga sem custo de LLM. |
| Qualidade | ruff, mypy, import-linter, ESLint, GitHub Actions | Erros pegos cedo; camadas garantidas por build. |
| Execução | Docker Compose para a infra; API, worker e painel no host | Simples e reprodutível; a Evolution alcança o webhook por `host.docker.internal`. |

---

## 2. Custo por conversa e estimativa para 1 mil e 10 mil leads/mês

### Custo por conversa (medido)

O custo abaixo é **medido** (uso de tokens registrado no eval com LLM real, 2026-11-21), só do agente. Detalhes, premissas e como regenerar: [docs/custos.md](docs/custos.md).

| Modelo | Cenários / aprovados | Custo médio por conversa | Máximo |
|---|---|---|---|
| **Haiku 5.5** | 15 / **14** | **~US$ 0,004** | US$ 0,009 |
| Sonnet 5.5 | 3 / 1 (amostra pequena; as 2 reprovações foram de uma checagem de handoff que depois saiu do eval) | ~US$ 0,079 | US$ 0,117 |
| `gpt-4.1-mini` (OpenAI) | 1 conversa de teste, fora do eval | ~US$ 0,009 | — |

- **O cache de prompt é o que deixa barato.** Quase toda a entrada é lida do cache; sem ele, a mesma conversa custaria 76% (Haiku) a 81% (Sonnet) mais. O cache incremental da conversa (commit `5a1145c`) cortou o custo do Sonnet em cerca de 55%.
- **Recomendação: Haiku 5.5 como principal**, cerca de 1/20 do custo do Sonnet. A única reprovação (`mente_tela_perfeita`) foi de tamanho de mensagem; as travas de negócio (valor só de ferramenta, desconto no teto) passaram em todos os cenários.
- **OpenAI**: 5 turnos até a proposta, estoque real do ERP, 13 chamadas ao modelo, 85 a 95% do prompt vindo do cache automático. É uma medição única, não o eval.
- **Configuração atual: o `.env.example` vem com `LLM_MODEL=claude-sonnet-5-5` e `LLM_FALLBACK_MODEL=claude-haiku-5-5`**. Para usar o Haiku como principal: `LLM_MODEL=claude-haiku-5-5` (e, se quiser, `LLM_FALLBACK_MODEL=claude-sonnet-5-5`). Nada mais muda.

### Projeção mensal (1 lead = 1 conversa)

LLM é medido × volume; áudio (30% das conversas com áudio) e infra são **estimativas**:

| Volume | Modelo | LLM | Áudio (STT+TTS) | Infra | Total | Por lead |
|---|---|---|---|---|---|---|
| **1 mil leads/mês** | **Haiku 5.5** | US$ 4,01 | US$ 5,04 | US$ 20 a 50 | **US$ 29 a 59** | US$ 0,03 a 0,06 |
| 1 mil leads/mês | Sonnet 5.5 | US$ 78,77 | US$ 5,04 | US$ 20 a 50 | **US$ 104 a 134** | US$ 0,10 a 0,13 |
| **10 mil leads/mês** | **Haiku 5.5** | US$ 40,09 | US$ 50,40 | US$ 40 a 100 | **US$ 130 a 190** | US$ 0,013 a 0,019 |
| 10 mil leads/mês | Sonnet 5.5 | US$ 787,74 | US$ 50,40 | US$ 40 a 100 | **US$ 878 a 938** | US$ 0,088 a 0,094 |

Leitura:

- **Com Haiku, o áudio pesa mais que o LLM**; o TTS é opcional por loja e é a principal alavanca de custo.
- **Infra**: uma VPS de 2 vCPU / 4 GB atende até ~10 mil leads/mês (o gargalo é o LLM, que é API, não CPU). A faixa inclui disco e backup.
- **Fora da conta**: WhatsApp (a Evolution self-hosted não cobra por mensagem; o custo da API oficial da Meta e o plano para sair da Evolution estão em [docs/whatsapp-oficial.md](docs/whatsapp-oficial.md)), domínio, monitoramento e mão de obra. A infra reforçada da Black Friday também não está nas faixas.
- **Amostra**: a média vem de conversas roteirizadas do eval, rodado **antes** do fechamento pela IA (M9), que acrescenta alguns turnos (endereço, horário, Pix); conversas reais mais curtas ou mais longas mudam o custo na mesma proporção. Para recalcular com as conversas reais: `uv run python scripts/custos.py --banco`. O painel `/desempenho` também mostra tokens e custo por modelo das conversas reais.

---

## 3. Plano para aguentar a Black Friday

### O que foi medido

Teste de carga (k6) contra o mesmo webhook do WhatsApp, LLM simulado sem custo, tudo na mesma máquina de 4 vCPU. Detalhes e limites em [docs/black-friday.md](docs/black-friday.md); para repetir: [infra/k6/README.md](infra/k6/README.md). O pico esperado de uma loja é ~40 msg/min (1.000 leads/dia, 20% numa hora).

| Cenário | Workers | Ingestão p99 | Fila máx. | Fila esvazia | Até a resposta p95 |
|---|---|---|---|---|---|
| 1x (40 msg/min) | 1 | 39 ms | 5 | 6 s | 8,3 s |
| **10x (400 msg/min)** | 1 | 42 ms | 618 | 65 s | 75,6 s |
| **10x (400 msg/min)** | **2** | 43 ms | 49 | 8 s | **8,1 s** |
| 20x (800 msg/min) | 2 | 37 ms | 755 | 41 s | 43,1 s |

O teste rodou com o debounce antigo de 4 s; com o padrão atual de 10 s, a coluna "até a resposta" ganha ~6 s (não medido de novo).

- **10x sem perda nem duplicação**: em todas as execuções, 0 mensagens perdidas, 0 duplicadas (inclusive com 5% de reentregas simultâneas do mesmo id) e todas as conversas respondidas.
- **2 workers aguentam 10x** com folga e ainda seguram ~20x com atraso moderado. Com 1 worker a fila cresce, mas só atrasa (até 80 s), não perde.
- **O webhook não é o gargalo**: só valida, grava e enfileira (p99 ≈ 43 ms), então a Evolution nunca dá timeout nem reenvia por culpa da API.
- **O gargalo real são os slots dos workers e o rate limit do LLM.** Em produção (~9 s por turno em vez dos 2,75 s simulados), 10x pede ~3 a 4 workers e ~28 chamadas simultâneas ao LLM por loja. O risco do WhatsApp (Evolution/Baileys) é o bloqueio do número, não a capacidade da API.

### Por que a arquitetura aguenta

- **Ingestão separada do processamento**: o webhook responde em milissegundos e a fila absorve o pico; atraso vira espera, nunca perda.
- **Idempotência** por `(canal, id_externo)`: reentrega da Evolution não duplica mensagem nem resposta.
- **Escala horizontal segura**: subir mais workers não exige nada além de mais processos, porque a trava por conversa no Redis garante um worker por conversa e a ordem das mensagens.
- **Degradação controlada**: LLM fora → retry com backoff → modelo reserva → "já te respondo" + vendedor. ERP fora → estoque local marcado como desatualizado.

### O plano

**Antes (uma a duas semanas)**

1. Pedir aumento do limite do LLM (requisições e tokens por minuto) e confirmar o limite efetivo da conta.
2. Subir a máquina da data: 4 vCPU / 8 GB, Postgres gerenciado, API, workers e Postgres separados.
3. Repetir `rodar_carga.sh` em staging com `WORKERS=3` ou mais a 10x. Critério de aceite: fila esvazia em menos de 30 s após o pico e p95 até a resposta < 20 s.
4. Dimensionar os workers pela conta `workers = ceil(turnos/min no pico × segundos por turno / 60 / 10)`: ~190 turnos/min a ~9 s por turno → 3 a 4 workers.
5. Rodar um eval real curto (com OK de custo) para medir segundos e chamadas reais por turno e refinar a conta.
6. Ensaiar a queda do LLM e do ERP. Usar chip secundário e aquecer o número do WhatsApp para reduzir o risco de bloqueio.

**No dia**

1. Subir os workers extras **antes** da campanha, não depois do backlog.
2. Acompanhar três números: jobs prontos na fila (alerta acima de ~100 por mais de 1 min), p95 até a resposta e taxa de erro/fallback do LLM (o painel `/desempenho` mostra latência, erros e handoffs por motivo).
3. Se o rate limit apertar, a fila segura o excesso; se o backlog crescer sem parar, subir mais workers. Pesos da distribuição entre vendedores são ajustáveis ao vivo.

**Depois**

1. Conferir recebidas × respondidas, handoffs por falha técnica e o custo real (`scripts/custos.py --banco`).

O teste **não** cobre o LLM real, a Evolution real nem várias lojas no mesmo worker.

---

## 4. Loja nova no ar em menos de 1 dia

A plataforma é multi-loja: loja nova é **dados**, não código nem deploy de backend. Tudo o que a loja precisa preencher está num assistente de 9 passos em `/onboarding`, com checklist de progresso (vem da API e persiste ao recarregar), grades editáveis com erro por célula e importação de planilha (validar → aplicar; nunca grava dados inválidos). As planilhas modelo vazias estão em [docs/modelos](docs/modelos): `modelo-troca.xlsx`, `modelo-taxas.xlsx` e `modelo-estoque.xlsx`.

**Passo 0 (nosso, ~10 min)**: criar a loja e o login do dono com `uv run python scripts/criar_loja.py --nome "Loja X" --email dono@loja.com` (em `backend/`; imprime a loja e uma senha provisória, uma vez). O dono entra no painel com esse e-mail e troca a senha no primeiro acesso; a loja do painel vem da sessão, sem variável de build. Plataforma já instalada; a primeira instalação (servidor, `.env`, Evolution) é uma vez só, na ordem de 1 a 2 h.

| # | Passo | O que fazer | Tempo estimado |
|---|---|---|---|
| 1 | Dados da loja e tom | Nome, endereço, horários, jeito de falar, opção de responder em áudio | 5 min |
| 2 | Vendedores e distribuição | Cadastrar vendedores (ou importar do ERP), WhatsApp de cada um e porcentagens (soma 100) | 5 min |
| 3 | Regras de preço | Máximo de parcelas, repasse de taxa, desconto Pix, teto de desconto, "oportunidade única" | 10 min |
| 4 | Formas de pagamento | O que a loja aceita e a chave Pix que a IA passa no fechamento | 5 min |
| 5 | Taxas da maquininha | Importar `modelo-taxas.xlsx` (taxa por parcela e bandeira) ou editar na grade | 10 min |
| 6 | Tabela de troca | Importar `modelo-troca.xlsx` (valor por modelo + capacidade e descontos por defeito). É o passo mais trabalhoso: a loja precisa decidir seus valores | 30 a 90 min |
| 7 | Estoque e SKU | Importar `modelo-estoque.xlsx`, ou conectar o Mercado Phone (`/configuracoes` > Conexão com o ERP > Testar > Sincronizar) | 15 a 45 min |
| 8 | Conectar WhatsApp | Escanear o QR code do número da loja (a instância é criada pela API) | 5 min |
| 9 | Conversa de teste | Conversar no simulador como cliente, conferir preço, troca, fechamento e handoff | 15 a 30 min |

**Total estimado: de ~1,5 h a ~4 h**, dominado por preencher a tabela de troca e o estoque; cabe numa manhã. Os tempos são **estimativas** nossas, não medição com um lojista real.

O que garante o prazo:

- **Nada de código por loja**: preço, troca, parcelas, desconto e tom vêm da configuração; o prompt e as regras são os mesmos para todas.
- **A configuração é lida a cada turno**: o que muda no painel vale na próxima mensagem, sem reiniciar nada.
- **Importação à prova de erro**: a planilha é validada antes de gravar e o erro aponta a célula (`troca!D7`); planilha inválida nunca apaga a configuração anterior.
- **Checklist objetivo**: o painel mostra exatamente o que falta; a loja está pronta quando todos os passos com checklist estão verdes e a conversa de teste passou.
- **ERP opcional**: com o Mercado Phone, estoque, preços e vendedores vêm prontos e a loja só confere os descartes.

---

## Integração com o ERP (Mercado Phone)

O estoque e os preços da loja podem vir do ERP Mercado Phone, lido por um servidor MCP. Quem fala com o ERP é o backend, por um adaptador atrás de `EstoquePort`; a IA nunca recebe as ferramentas do MCP nem a chave (uma allowlist de 8 ferramentas, sem nenhuma de exclusão).

- **Conectar**: `MERCADOPHONE_API_KEY` no `.env`; no painel, `/configuracoes` > **Conexão com o ERP** (unidade, filtro da loja, intervalo, **Testar conexão**, **Sincronizar agora**).
- **Sincronização**: cron do worker a cada 5 min respeitando o intervalo da loja. O estoque só é substituído quando a leitura vem completa; leitura vazia ou sem nada importável é erro e o estoque anterior fica.
- **Só celulares ofertáveis**: regras de descarte no domínio (sem preço, indisponível, sem capacidade, outra loja...), com relatório por motivo.
- **Confirmação ao vivo**: antes da proposta, o agente confere o SKU no ERP (timeout de 2 s); ERP fora = dado local marcado como desatualizado.
- **Vendedores** importados do ERP (botão no onboarding) e **handoff que cria cliente e orçamento** no ERP (desligado por padrão; escrita ainda a validar no ERP real).
- **Smoke de leitura** com a chave do `.env`: `cd backend && uv run python scripts/mercadophone_smoke.py --filtro-loja "Loja A"`.

Passo a passo, tabela de motivos de descarte, o que é escrito no ERP e limites: [docs/mercadophone.md](docs/mercadophone.md).

## Como rodar local

Testado do zero em um clone limpo (Linux). Os valores de `.env.example` já funcionam em desenvolvimento.

**Pré-requisitos**: Git, Docker com Compose, Python 3.12 + [`uv`](https://docs.astral.sh/uv/) (no PATH, ex.: `~/.local/bin`), Node 24 + npm (com nvm: `nvm use 24`; o Node 20 quebra o vitest).

```bash
git clone https://github.com/hOtoch/Agente-atendimento-mobile.git && cd Agente-atendimento-mobile
cp .env.example .env
```

No `.env`:

- `LLM_PROVIDER`: quem conversa com o cliente, `anthropic` (padrão) ou `openai`.
- `ANTHROPIC_API_KEY`: **obrigatória para a IA real com `LLM_PROVIDER=anthropic`** (e para o eval real). Sem a chave do provedor escolhido, o atendimento responde com a mensagem de espera e chama o vendedor.
- `OPENAI_API_KEY`: áudio (STT e TTS) e, com `LLM_PROVIDER=openai`, também a conversa (use `LLM_MODEL=gpt-4.1-mini` e `LLM_FALLBACK_MODEL=gpt-4o-mini`). Sem ela o agente pede ao cliente que digite e responde só em texto.
- `LLM_MODEL`: modelo principal (padrão `claude-sonnet-5-5`; troque por `claude-haiku-5-5` para o custo da seção [2](#2-custo-por-conversa-e-estimativa-para-1-mil-e-10-mil-leadsmês)).
- `MERCADOPHONE_API_KEY`: **opcional**, só para sincronizar estoque e vendedores com o ERP Mercado Phone ([docs/mercadophone.md](docs/mercadophone.md)). Sem ela a integração fica desligada.

```bash
# 1. Infra: Postgres dev (5432) e de teste (5433), Redis, Evolution API (8080), ERP simulado (8090)
bash infra/dev.sh up            # também: down | logs [serviço] | ps | reset
bash infra/smoke.sh             # confere healthchecks e portas

# 2. Backend: dependências, migrations e a loja demo (seed idempotente)
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.infra.seed

# 3. API (--host 0.0.0.0 para a Evolution, dentro do Docker, alcançar o webhook;
#    o timeout evita que o reload trave esperando os streams SSE do painel/webchat)
uv run uvicorn app.main:app --host 0.0.0.0 --reload --reload-dir app --timeout-graceful-shutdown 3     # http://localhost:8000/health

# 4. Worker do agente (outro terminal, em backend/)
uv run arq app.infra.worker.WorkerSettings

# 5. Painel (outro terminal)
cd frontend
npm ci
npm run dev                     # http://localhost:3000
```

**Entrar no painel.** O painel exige login (exceto `/login` e o chat público `/chat/{loja}`). O seed cria o usuário da loja demo: e-mail `demo@atendimento.local` e a senha de `SEED_SENHA_DEMO` no `.env` (o `.env.example` já traz um valor de dev; sem a variável o seed pula o usuário e avisa). Abra <http://localhost:3000>, entre e use o botão **Sair** quando quiser encerrar a sessão. No dev, painel (`localhost:3000`) e API (`localhost:8000`) contam como o mesmo "site" para o cookie de sessão (`SameSite=Lax`), e `CORS_ORIGINS` precisa conter `http://localhost:3000` (já está no `.env.example`).

- **Criar outra loja** (não há cadastro público): `cd backend && uv run python scripts/criar_loja.py --nome "Loja X" --email dono@loja.com [--senha-provisoria ...]`. Sem `--senha-provisoria` gera uma senha forte e a imprime uma única vez; o dono troca no primeiro acesso (`/conta/senha`).
- **Redefinir senha** (dono esqueceu): `uv run python scripts/redefinir_senha.py --email dono@loja.com` gera uma nova senha provisória, imprime uma vez e encerra as sessões abertas.
- **Público, sem login**: `/login`, o chat do cliente (`/chat/{loja}`, `POST /webchat/{loja}/...`), os webhooks (Evolution), `/health` e os arquivos de mídia.
- **Exige login da própria loja**: todo o resto do painel e toda rota `/lojas/{loja_id}/...` da API (kanban, leads, conversas, configuração, métricas, onboarding, importação, WhatsApp e o stream SSE `/lojas/{loja_id}/eventos`). Sem sessão a API responde 401; com a sessão de outra loja, 403 (ou 404 para um lead de outra loja). O teste `backend/tests/integration/test_isolamento_lojas.py` prova isso com duas lojas.
- Limite de tentativas: 5 falhas por e-mail e 20 por IP em 15 min viram `429` com `Retry-After` (`LOGIN_*` no `.env`).
- Produção na VPS (HTTPS, um domínio, cookie `Secure`): [docs/deploy-vps.md](docs/deploy-vps.md).

Depois de entrar: use o **Simulador** (`/simulador`) para conversar como cliente; o lead aparece no **Kanban** e na **Conversas** (inbox). A loja demo tem o ID fixo `00000000-0000-4000-8000-00000000de30` e o chat público fica em `http://localhost:3000/chat/00000000-0000-4000-8000-00000000de30`. Para o WhatsApp, conecte o número pelo QR no passo 8 do onboarding. Para ver o painel de desempenho com dados, popule a loja demo: `uv run python scripts/popular_metricas_demo.py --loja 00000000-0000-4000-8000-00000000de30 --dias 30` (em `backend/`; `--remover` desfaz).

**Conversar pelo terminal, sem painel, sem Redis e sem custo:**

```bash
cd backend
uv run python scripts/conversar.py --fake    # LLM eco: só testa o fio (linha vazia ou Ctrl+D encerra)
uv run python scripts/conversar.py           # LLM real: pago, usa o LLM_PROVIDER e a chave dele
```

**Testes e qualidade:**

```bash
cd backend
uv run pytest -m "not integration"                      # rápidos, sem banco
uv run pytest                                           # todos; precisa do Postgres de teste (5433)
uv run ruff check . && uv run ruff format --check . && uv run mypy app evals && uv run lint-imports
uv run python -m evals.rodar --modo fake                # eval sem custo (usado no CI)
# Eval com LLM real é PAGO: mostra a estimativa; só roda com --confirmo-custo
uv run python -m evals.rodar --modo real --modelo claude-haiku-5-5

cd ../frontend
npm test -- --run && npm run lint && npm run typecheck && npm run build

cd ../services/erp-mock && uv run pytest                # ERP simulado
```

Outros comandos úteis: `uv run alembic downgrade base` (desfaz tudo), `uv run python -m app.infra.seed` (de novo a qualquer hora), `bash infra/k6/rodar_carga.sh` (teste de carga, ver [infra/k6/README.md](infra/k6/README.md)), `uv run python scripts/exportar_openapi.py && cd ../frontend && npm run gerar:api` (regera o cliente TypeScript quando a API muda).

Portas locais: API 8000, painel 3000, Evolution 8080, ERP simulado 8090 (token `token-dev`), Postgres 5432 (dev) e 5433 (teste, em memória), Redis 6379.

## Qualidade

- **Testes** (contagem de 2026-11-23): backend **2.212** (1.947 unitários e de contrato + 265 de integração com Postgres), frontend **394**, ERP simulado **35**, eval fake **7/7**. Total **2.641** (sem contar o eval).
- **Eval do agente** (`backend/evals/`): cenários de conversa (preço logo de cara, cliente que mente sobre a tela, prompt injection, troca com defeito, pedir desconto três vezes contra o teto, fechamento com Pix, etc.) mais controles negativos (cenários que violam uma regra de propósito e **precisam** ser reprovados, para provar que a checagem funciona). Checagens automáticas: sem valor antes da proposta, valores só vindos de ferramenta, desconto dentro do teto, etapa final, handoff, uma pergunta por mensagem, tamanho máximo, frase de pré-avaliação, sem erro de ferramenta, sem frases proibidas, valores esperados ditos.
- **Modo fake** (grátis; valida o harness e as checagens, coberto pelos testes do CI); **modo real** só com `--confirmo-custo` (imprime a estimativa antes).
- **CI** (GitHub Actions): ruff, ruff format, mypy, import-linter, pytest com integração obrigatória, ESLint, typecheck, testes e build do frontend, testes do ERP simulado e validação do docker-compose.
- **Testes nunca chamam API paga**: LLM, STT e TTS são substituídos por fakes, e a suíte zera as chaves do `.env` local.

## Decisões e trade-offs

- **Inbox própria em vez de Chatwoot.** O handoff (assumir/devolver, resumo, "aguardando vendedor", pausar a IA quando o vendedor digita no celular) é o requisito central e precisa de controle fino do estado da conversa; um Chatwoot adicionaria um serviço pesado e uma integração só para isso no prazo. Em produção com várias equipes, Chatwoot (ou similar) como inbox é um caminho razoável: o `CanalPort` e os eventos de handoff já isolam essa troca.
- **ERP atrás de uma porta, com um ERP simulado e o Mercado Phone real.** O agente só enxerga `EstoquePort` (`buscar`, `obter`); há um adaptador de planilha (estoque no banco), um do ERP simulado (nomes "sujos", mapeamento de SKU, falhas e latência configuráveis) e o do Mercado Phone (MCP, só no backend, com allowlist), todos embrulhados por um decorator resiliente (cache, retry, timeout, fallback). Trocar de ERP é escrever um adaptador novo e passá-lo pela mesma suíte de contrato.
- **Dois provedores de LLM.** Anthropic é o padrão (eval e custos medidos); OpenAI entrou como adaptador do mesmo `LLMPort`. Os modelos da OpenAI precisaram do estado antes da fala do cliente e de uma instrução fixa de uso das ferramentas, senão respondiam só em texto e não preenchiam a ficha.
- **Instagram só como adaptador.** Normalizador, verificação de assinatura e envio estão prontos e testados com fixtures; a revisão do app Meta não cabe no prazo. O que falta para produção está listado em [docs/instagram.md](docs/instagram.md).
- **Rodar local na apresentação.** A Evolution conecta de dentro para fora, sem túnel; há vídeo de backup. Um túnel (cloudflared/ngrok) só se for preciso um link público.
- **Mídia em disco local** (`MIDIA_DIR`), atrás de uma porta (`ArmazenamentoMidia`): simples para a demo, mas não serve para várias instâncias; trocar por S3/R2 não toca o caso de uso.
- **Horário comercial em UTC-3 fixo** (sem `tzdata`): vale para o follow-up, para "hoje" nas regras e para as métricas; lojas em outros fusos pediriam fuso por loja.
- **Strict tool use com limites.** Na Anthropic, ferramentas com tipos que poderiam quebrar a ficha usam `strict`; as demais ficam sem. A API limita ferramentas strict (≤ 20), parâmetros opcionais (≤ 24) e uniões (≤ 16); um teste trava esses limites, mas o limite de uniões só aparece num `messages.create` real. Na OpenAI, nenhuma ferramenta é strict (o modo estrito exige todos os parâmetros obrigatórios).
- **Login simples, um usuário por loja.** Cada loja tem um login de dono criado por script (sem cadastro público, sem papéis, sem recuperação por e-mail: a senha é redefinida por comando no servidor). A loja do painel vem da sessão; o inbox ainda usa o seletor "Atendendo como" para escolher o vendedor. `/chat/{loja}` é público de propósito.
- **Evolution não oficial.** Risco de bloqueio do número: usar chip secundário e, em produção séria, migrar para a API oficial: custo e plano em [docs/whatsapp-oficial.md](docs/whatsapp-oficial.md).

## Riscos conhecidos e pendências

- **Sem ensaio com celular pareado**: formato real dos webhooks da Evolution, download de mídia e entrega ao cliente e ao vendedor não foram validados fora de testes e da instância sem conexão. Áudio e imagem pelo WhatsApp real também não.
- **O eval real é anterior ao fechamento pela IA (M9)** e o do Sonnet cobriu só 3 cenários; a comparação justa com o Haiku (os mesmos 15) custaria ~US$ 1,18 e depende de autorização.
- **A imagem recebida fica em base64 na transcrição e é reenviada a cada turno** (custo de tokens); redimensionar ou resumir depois de lida é melhoria futura.
- **Rate limit do LLM e bloqueio do WhatsApp** não são medidos pelo teste de carga (LLM e Evolution simulados). Sentry não está integrado; o acompanhamento no dia depende de logs, do painel `/desempenho` e do custo por conversa registrado nos eventos.
- **Escrita no Mercado Phone não validada no ERP real**: a leitura (estoque, vendedores) foi conferida no servidor da loja; o handoff que cria cliente e orçamento foi testado só contra um servidor falso e fica desligado por padrão. Premissas a validar (id criado, desconto em reais, valor do crédito) em [docs/mercadophone.md](docs/mercadophone.md#limites-conhecidos-e-premissas-a-validar).
- **Premissas de negócio a confirmar com a loja**: "data da compra" = quando o cliente pretende comprar; desconto Pix incide sobre a base já com troca e entrada; "oportunidade única" soma por fora do teto de desconto.
- **Pequenas dívidas**: cache do `EstoqueResiliente` sem limite de tamanho; a transcrição do áudio só aparece no painel ao recarregar; sem tela para reativar vendedor desativado; `npm audit` com avisos; a barra lateral do painel não recolhe no celular e os itens inativos dela quase somem no tema escuro.

## Mapa de documentos

| Documento | Conteúdo |
|---|---|
| [docs/roteiro-demo.md](docs/roteiro-demo.md) | Roteiro do vídeo (≤ 10 min) e da apresentação, tentativas de quebrar a IA, checklist e planos B/C |
| [docs/deploy-vps.md](docs/deploy-vps.md) | Subir na VPS: um domínio com Caddy (painel em `/`, API em `/api`), variáveis de produção, build fora da VPS, swap |
| [docs/custos.md](docs/custos.md) | Custo medido por conversa, efeito do cache, projeção 1 mil / 10 mil leads, premissas |
| [docs/whatsapp-oficial.md](docs/whatsapp-oficial.md) | Custo da API oficial do WhatsApp (1 mil e 10 mil leads, Black Friday), Evolution × Cloud API e plano de migração |
| [docs/black-friday.md](docs/black-friday.md) | Resultado do k6, interpretação, gargalos e plano da Black Friday |
| [infra/k6/README.md](infra/k6/README.md) | Como repetir o teste de carga |
| [docs/desempenho.md](docs/desempenho.md) | Painel de desempenho da IA e dados de demonstração |
| [docs/audio.md](docs/audio.md) | Áudio de entrada (STT) e de saída (TTS): regra, provedor, preço de referência |
| [docs/instagram.md](docs/instagram.md) | Plano de ação do Instagram Direct, adaptador e passos para produção |
| [docs/mercadophone.md](docs/mercadophone.md) | Integração com o ERP Mercado Phone: conectar, sincronizar, regras de descarte, o que é escrito no ERP, limites |
| [docs/modelos](docs/modelos) | Planilhas modelo de importação (troca, taxas, estoque) |
| [DESIGN.md](DESIGN.md) | Design system e fonte da verdade visual do painel |
| [context.md](context.md) | Plano, regras de negócio, decisões e status por milestone |
| [CLAUDE.md](CLAUDE.md) | Regras de engenharia e fluxo de trabalho do projeto |
