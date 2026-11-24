# WhatsApp oficial (Cloud API da Meta): custo e plano para sair da Evolution

Hoje o WhatsApp roda pela Evolution API (não oficial, conecta por QR code). Este documento responde a duas perguntas do dono: **quanto custa a API oficial** e **o que é preciso para sair da Evolution**. Nada aqui está implementado: é a conta e o plano.

> Tarifas e regras da Meta mudam (as tarifas, só em 1/jan, 1/abr, 1/jul e 1/out). Tudo o que veio da Meta foi lido nas páginas oficiais em **2026-11-24**. O que é **premissa nossa** está marcado como tal; o que precisa ser conferido antes de decidir está marcado **(conferir)**.

## 1. Como a Meta cobra

Fontes (lidas em 2026-11-24):

- Preços e regras: <https://developers.facebook.com/docs/whatsapp/pricing>
- Tabela interativa de tarifas por país: <https://business.whatsapp.com/products/platform-pricing#rates>

O que vale:

- **Cobrança por mensagem entregue** (desde 2025-07-01; o modelo por conversa foi aposentado), por categoria e pelo país do destinatário. **Mensagem do cliente para a empresa não é cobrada.**
- **Categorias.** Com template: **marketing**, **utilidade** e **autenticação**. Sem template: **serviço**, que é a resposta dentro da **janela de 24 h** aberta por uma mensagem do cliente. A janela reinicia a cada mensagem do cliente; fora dela só vai template (aprovado pela Meta).
- **Desde 2026-10-01**: serviço tem **1.000 mensagens grátis por número por mês**; da 1.001ª em diante é cobrado. Utilidade dentro da janela aberta voltou a ser cobrada.
- **Janela de entrada grátis (FEP)**: conversa iniciada por anúncio Click-to-WhatsApp (Android/iOS) tem as mensagens grátis por até 7 dias.
- **Brasil**: utilidade e autenticação **US$ 0,0068** por mensagem (cerca de R$ 0,035); marketing **US$ 0,0625** (cerca de R$ 0,32). Faturamento em BRL disponível desde 2026-07-01. Faixas de desconto por volume existem só para utilidade e autenticação.
- **Premissa nossa (conferir no rate card):** o preço da mensagem de **serviço acima de 1.000/mês no Brasil**. Usamos o mesmo da utilidade, US$ 0,0068.

## 2. Conta de custo

### Premissas (todas nossas, a validar com a operação real)

| Item | Valor | De onde vem |
|---|---|---|
| Mensagens da IA por conversa | **6,5** (1 por turno) | média de turnos dos 15 cenários do eval real com Haiku (2026-11-21, ver [custos.md](custos.md)): 6,47 turnos. Se a IA mandar 2 mensagens por turno, o custo de serviço quase dobra |
| Número de WhatsApp | **1** (1 loja) | os 1.000 grátis valem por número; cada loja nova com número próprio ganha mais 1.000 |
| Aviso ao vendedor | **0,5 por lead** (50% dos leads chegam ao handoff), 1 template de **utilidade** | o eval roteirizado deu 11/15 handoffs, mas ele é enviesado para fechar; 50% é um valor conservador. O vendedor não escreve para o número da loja, então o aviso cai **fora da janela** e exige template |
| Follow-up | **1,0 template por lead** | o padrão da config é 2 tentativas por lead (`max_tentativas=2`); assumimos que metade dos leads para de responder e recebe as 2. Sai fora da janela de 24 h, então é template. Mostramos os dois casos: **utilidade** (US$ 0,0068, otimista) e **marketing** (US$ 0,0625, realista: a Meta tende a tratar mensagem de reengajamento de venda como marketing; **conferir** a classificação na aprovação do template) |
| Anúncio Click-to-WhatsApp (FEP) | 0% dos leads | conservador: se parte dos leads vier de anúncio, as mensagens dentro de 7 dias dessas conversas saem grátis |
| Faixas de volume | não aplicadas | conservador: a utilidade pode ficar mais barata acima de certo volume |
| Black Friday | **2,2 × os leads** | mesma premissa de `custos.md` e `context.md` |
| Câmbio | **R$ 5,20 por US$ 1** (premissa, 2026-11-24) | a Meta fatura em BRL desde 2026-07-01, então o valor real em reais vem da tarifa em BRL da tabela oficial |
| Custo de IA | Haiku 5.5: LLM US$ 0,004009 (medido) + áudio US$ 0,00504 (estimativa) por lead | [custos.md](custos.md) |

### Resultado por mês (US$)

Serviço = (mensagens da IA − 1.000 grátis) × US$ 0,0068. Aviso = leads × 0,5 × US$ 0,0068. Follow-up = leads × 1,0 × tarifa do template.

| Cenário | Leads | Serviço | Aviso ao vendedor | Follow-up (utilidade / marketing) | **WhatsApp oficial** (utilidade / marketing) | Por lead (só WhatsApp) |
|---|---|---|---|---|---|---|
| 1 mil, mês normal | 1.000 | US$ 37,40 | US$ 3,40 | US$ 6,80 / US$ 62,50 | **US$ 47,60 / US$ 103,30** | US$ 0,048 / US$ 0,103 |
| 1 mil, Black Friday | 2.200 | US$ 90,44 | US$ 7,48 | US$ 14,96 / US$ 137,50 | **US$ 112,88 / US$ 235,42** | US$ 0,051 / US$ 0,107 |
| 10 mil, mês normal | 10.000 | US$ 435,20 | US$ 34,00 | US$ 68,00 / US$ 625,00 | **US$ 537,20 / US$ 1.094,20** | US$ 0,054 / US$ 0,109 |
| 10 mil, Black Friday | 22.000 | US$ 965,60 | US$ 74,80 | US$ 149,60 / US$ 1.375,00 | **US$ 1.190,00 / US$ 2.415,40** | US$ 0,054 / US$ 0,110 |

Em reais (câmbio R$ 5,20, premissa):

| Cenário | WhatsApp oficial, follow-up de utilidade | WhatsApp oficial, follow-up de marketing |
|---|---|---|
| 1 mil, mês normal | R$ 247,52 | R$ 537,16 |
| 1 mil, Black Friday | R$ 586,98 | R$ 1.224,18 |
| 10 mil, mês normal | R$ 2.793,44 | R$ 5.689,84 |
| 10 mil, Black Friday | R$ 6.188,00 | R$ 12.560,08 |

### Somado ao custo de IA (Haiku 5.5, [custos.md](custos.md))

IA = LLM + áudio, sem infra (US$ 9,05 por mil leads). Infra entra como faixa, igual a `custos.md` (US$ 20 a 50 com 1 mil leads; US$ 40 a 100 com 10 mil). Na Black Friday a faixa é a do volume-base, **sem o reforço de infra** (4 vCPU/8 GB, Postgres gerenciado, 2+ workers), que continua fora da conta.

| Cenário | IA (LLM + áudio) | Infra | **Total, follow-up de utilidade** | **Total, follow-up de marketing** | Por lead (utilidade / marketing) |
|---|---|---|---|---|---|
| 1 mil, mês normal | US$ 9,05 | US$ 20 a 50 | **US$ 76,65 a 106,65** (R$ 399 a 555) | **US$ 132,35 a 162,35** (R$ 688 a 844) | US$ 0,077 a 0,107 / US$ 0,132 a 0,162 |
| 1 mil, Black Friday (2.200 leads) | US$ 19,91 | US$ 20 a 50 | **US$ 152,79 a 182,79** (R$ 794 a 950) | **US$ 275,33 a 305,33** (R$ 1.432 a 1.588) | US$ 0,069 a 0,083 / US$ 0,125 a 0,139 |
| 10 mil, mês normal | US$ 90,49 | US$ 40 a 100 | **US$ 667,69 a 727,69** (R$ 3.472 a 3.784) | **US$ 1.224,69 a 1.284,69** (R$ 6.368 a 6.680) | US$ 0,067 a 0,073 / US$ 0,122 a 0,128 |
| 10 mil, Black Friday (22.000 leads) | US$ 199,08 | US$ 40 a 100 | **US$ 1.429,08 a 1.489,08** (R$ 7.431 a 7.743) | **US$ 2.654,48 a 2.714,48** (R$ 13.803 a 14.115) | US$ 0,065 a 0,068 / US$ 0,121 a 0,123 |

Leitura:

- **Com a API oficial o WhatsApp passa a ser o maior item da conta**, maior que o LLM e o áudio juntos: com Haiku, a IA custa cerca de US$ 0,009 por lead; o WhatsApp custa US$ 0,05 a 0,11. Hoje (Evolution) esse item é zero.
- **O follow-up é a alavanca.** Utilidade custa US$ 0,0068 e marketing US$ 0,0625 (9,2 vezes mais), então a classificação do template pesa mais que qualquer outra premissa. Cortar para 1 tentativa por lead corta esse item pela metade.
- **Cada mensagem da IA acima de 6,5 por conversa** custa US$ 6,80 por mil leads (US$ 68 por 10 mil). Mensagens mais curtas e em menor número (o que o agente já tenta fazer) economizam dinheiro de verdade.
- **O modelo de IA não muda a parte do WhatsApp**: com Sonnet, soma-se o LLM de `custos.md` (US$ 0,079 por lead) ao mesmo WhatsApp.
- **Os 1.000 grátis de serviço pesam pouco:** valem US$ 6,80 por número por mês.

## 3. Evolution × Cloud API

| Ponto | Evolution (hoje) | Cloud API (oficial) |
|---|---|---|
| Custo | Sem tarifa por mensagem (só a VPS) | Por mensagem entregue (seção 2): US$ 0,05 a 0,11 por lead nas premissas acima |
| Risco de bloqueio do número | **Alto**: não oficial (Baileys), a Meta pode banir o número a qualquer momento; por isso o README manda usar chip secundário | Baixo: é o canal sancionado; o risco passa a ser de qualidade (denúncias, bloqueios de templates) |
| Vendedor responde pelo celular (`fromMe`) | Sim: o `fromMe` pausa a IA | **Não**: o número da API não fica no app do celular. O vendedor responde **pelo painel**, que já existe (a resposta do painel sai pelo canal). Existe um modo de coexistência (número no app Business e na API ao mesmo tempo) **(conferir elegibilidade e regras na Meta; não foi levantado aqui, não assumir)** |
| Follow-up e aviso ao vendedor | Texto livre a qualquer hora | Fora da janela de 24 h só **template aprovado**; dentro da janela, texto livre |
| Mídia recebida | A mídia vem pelo webhook/API da Evolution | O webhook traz só o **id** da mídia: é preciso baixar com o token (consulta ao id e depois à URL temporária) |
| Número | Qualquer chip pareado por QR code | **Número dedicado**, fora do app WhatsApp (ou ligado por coexistência) |
| Conexão | QR code, a sessão pode cair | Token de usuário de sistema, sem sessão para reconectar |
| Setup | Minutos | Dias a semanas (seção 4), com etapas que dependem da Meta |

## 4. Como sair da Evolution

### O que é preciso (por loja, ou por conta nossa)

1. **Portfólio empresarial na Meta (Business Manager) verificado**, com os dados da empresa.
2. **App Meta** com o produto WhatsApp, ligado ao portfólio.
3. **Número dedicado**, que **não esteja ativo no app WhatsApp** (se estiver, é preciso apagar a conta do app antes) e que receba o código de verificação por SMS ou ligação.
4. **Nome de exibição aprovado** pela Meta.
5. **Templates aprovados**: pelo menos um de follow-up e um de aviso ao vendedor (o aviso leva o resumo e o link do painel como variáveis).
6. **Token de usuário de sistema** (não expira), guardado por loja.
7. **Webhook** configurado no app, apontando para a nossa rota, com a assinatura do app.

### Prazo realista por etapa

Os prazos são estimativas nossas; os marcados **(Meta)** dependem da Meta e não controlamos.

| Etapa | Prazo | Quem |
|---|---|---|
| Criar portfólio, app e número dedicado | 1 dia | nós + dono da loja |
| Verificação do negócio (documentos da empresa) | 2 a 10 dias úteis | **(Meta)** |
| Nome de exibição aprovado | 1 a 3 dias úteis | **(Meta)** |
| Aprovação dos templates | de minutos a 1 dia útil cada; reprovação pede reescrita | **(Meta)** |
| Código no sistema (abaixo) | 9 a 11 dias de trabalho | nós |
| Homologação com número real, ensaio de ponta a ponta | 2 dias | nós + loja |

As etapas da Meta correm **em paralelo** ao código. Prazo total realista: **2 a 3 semanas** do início até o primeiro cliente real, boa parte esperando a verificação do negócio.

### O que muda no código

Segue o padrão do Instagram ([instagram.md](instagram.md)), que já tem a assinatura `X-Hub-Signature-256` e o desafio `hub.*` como funções puras.

| Mudança | Detalhe | Estimativa |
|---|---|---|
| `CloudApiAdapter` (implementa `CanalPort`) | envio de texto, áudio e imagem pela Graph API; erro tipado quando a janela fechou | 1,5 dia |
| Rota `GET/POST /webhooks/whatsapp-cloud` | desafio de verificação (GET) e `X-Hub-Signature-256` (POST), reaproveitando a validação do Instagram; responde 200 rápido e enfileira | 1 dia |
| Normalizador do payload | `entry[].changes[].value.messages[]` para `MensagemEntrada`: texto, áudio, imagem, documento; ignora status de entrega e leitura; a idempotência por `(canal, id_externo)` já existe | 1,5 dia |
| Download de mídia por id | consulta ao id e depois à URL temporária com o token, entregue ao STT e à visão como hoje | 1 dia |
| Janela de 24 h e templates | saber se a janela está aberta (última mensagem do cliente, já registrada) e, fora dela, enviar **template** no follow-up e no aviso ao vendedor, com as variáveis; os dois passam a escolher "texto" ou "template" pela janela | 2 dias |
| Canal por loja na config | campo de canal (`evolution` ou `cloud_api`) e credenciais por loja (token, id do número); a composição escolhe o adaptador | 1 dia |
| Painel: conectar e acompanhar | tela para informar o número e o token, testar a conexão, e aviso quando a janela do lead fechou (o vendedor só responde por template depois disso) | 1 a 2 dias |
| Testes de contrato e homologação | a mesma suíte de `CanalPort`, fixtures reais do payload, ensaio com o número real | 1 a 2 dias |
| **Total** | | **cerca de 9 a 11 dias de código** |

### O que **não** muda

O agente, as travas de negócio (preço, troca, parcelas, desconto), o kanban, o painel de conversas e de desempenho, o ERP, o áudio. Eles só veem `MensagemEntrada` e `MensagemSaida`.

### Migração gradual

O canal é escolhido **por loja** na configuração (item acima), então a troca pode ser loja a loja: uma loja piloto na Cloud API com número novo, as outras na Evolution, e a Evolution sai quando a última migrar. Cada loja migrada passa a ter o próprio número, com seus 1.000 grátis de serviço, e o custo da seção 2 passa a valer para ela.

## 5. Resumo para decidir

- **Custo:** de US$ 0,05 a 0,11 por lead só de WhatsApp (utilidade ou marketing no follow-up), contra zero hoje. Com 10 mil leads por mês: US$ 537 a 1.094 de WhatsApp, e US$ 668 a 1.285 com IA e infra (mês normal, Haiku).
- **Ganho:** some o risco de banimento do número e a sessão por QR code; sai o `fromMe` (o vendedor passa a responder pelo painel).
- **Esforço:** 9 a 11 dias de código e 2 a 3 semanas de calendário, a maior parte esperando a Meta.
- **Antes de decidir, conferir:** o preço de serviço acima de 1.000/mês no rate card do Brasil; a classificação (utilidade ou marketing) dos templates de follow-up; o modo de coexistência, se o vendedor precisar mesmo do celular.
