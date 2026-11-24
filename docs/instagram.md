# Instagram Direct: plano de ação e referência técnica

Status: **adaptador pronto, canal não ligado**. Normalização do webhook, verificação de
assinatura e envio existem e são testados com fixtures e transporte HTTP falso. Falta a rota, a
ligação conta ↔ loja e, principalmente, a aprovação da Meta. Este documento tem duas partes:
o **Plano de ação** (para decidir) e a **Referência técnica** (para implementar).

> Fatos da Meta abaixo foram conferidos nas páginas oficiais em 2026-11-24 (URLs citadas).
> O que é **premissa** está marcado como tal. Regra e prazo da Meta mudam: reconferir antes de
> começar.

## Plano de ação

### 1. O que é preciso

Do lado da loja:

- Conta **profissional** do Instagram (comercial ou criador).
- Página do Facebook ligada à conta (exigida no fluxo com Facebook Login; no fluxo
  "Instagram API with Instagram Login" é premissa que dispensa, conferir).
- O dono da conta autoriza o app por um login (OAuth) na tela de conexão do painel.

Do lado nosso (uma vez, vale para todas as lojas):

- **Portfólio empresarial** da Otoch na Meta, com **verificação da empresa** (premissa: exigida
  para acesso avançado como provedor de outras empresas).
- **App Meta** (tipo Negócios) com o produto Instagram e Webhooks.
- **Permissões** e App Review. Como o produto é multi-loja (atendemos contas de outras
  empresas), vale a página "apps for other businesses": `instagram_manage_messages`
  (obrigatória), `business_management` (dependência) e `instagram_basic`. Fonte:
  https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review/apps-for-other-businesses
  (para uma loja usando só a própria conta, a lista é menor:
  https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review/apps-for-your-own-business).
- **Screencast** para o App Review. O revisor precisa conseguir configurar a experiência
  automatizada por um fluxo de login e ver a resposta automática em **até 30 s**; ele também
  testa respostas rápidas, ice breakers e mensagem apagada. O formulário pede ainda o @ do
  perfil de teste e a plataforma "Website".
- **Política de privacidade** publicada (URL exigida no app).
- **Webhook HTTPS público**: a VPS já tem (`docs/deploy-vps.md`).
- **Escalada para humano**: a Meta exige caminho para falar com uma pessoa
  (https://developers.facebook.com/documentation/business-messaging/instagram-messaging/overview).
  Já temos: handoff para o vendedor.

### 2. Cronograma

Duas trilhas que correm **em paralelo**; a Meta é o gargalo.

| Trilha | Etapa | Duração |
|---|---|---|
| Código (nós) | Rota `GET/POST /webhooks/instagram` + composição do canal | 1 a 2 dias |
| Código | Conta ↔ loja, token por loja (criptografado) e renovação | 2 a 3 dias |
| Código | Download da mídia recebida (a URL da CDN expira) | 1 dia |
| Código | Tela de conexão no onboarding (OAuth) | 2 dias |
| Código | Falha fora da janela de 24 h vira handoff; follow-up desligado no canal | 1 dia |
| Código | Teste ponta a ponta em modo desenvolvimento (conta de teste) + screencast | 1 a 2 dias |
| Meta | Verificação da empresa | **premissa: dias a algumas semanas; conferir** |
| Meta | App Review (pode ter mais de uma rodada) | **premissa: dias a algumas semanas; conferir** |

Código: cerca de **8 a 11 dias úteis**, todo antes do envio ao App Review (o revisor precisa
de um fluxo funcionando). A verificação da empresa pode começar **hoje**, sem esperar o código.
Estimativa: **no ar em 3 a 6 semanas** (premissa), com o gargalo na Meta, não no código. Em modo
de desenvolvimento já dá para testar com contas que tenham função no app, antes da aprovação.

### 3. Custo

- **Sem tarifa por mensagem**: as páginas do Instagram Messaging não listam cobrança por
  mensagem (diferente do WhatsApp oficial). O custo é o da IA e o da infra.
- **IA**: igual ao WhatsApp, por conversa. Valores medidos e projeção em
  [docs/custos.md](custos.md); o Instagram usa o mesmo agente, então a conta não muda.
- **Janela de resposta de 24 h**: o padrão é só responder dentro de 24 h da última mensagem do
  cliente. Consequência de produto: **desligar o follow-up automático no Instagram** (mensagem
  de reativação depois de 24 h não é permitida fora das tags). O recurso opcional **Human
  Agent** estende para **7 dias** com a tag `human_agent`, mas serve **só para resposta de uma
  pessoa**, não para a IA nem para disparo. Fonte: a página "apps for your own business"
  citada acima.
- Infra extra: nenhuma relevante (mesma VPS, mesmo worker).

### 4. Por que a IA funciona igual nas duas plataformas

O agente nunca vê o canal. Ele recebe `MensagemEntrada` e devolve `MensagemSaida` pela porta
`CanalPort` (`app/application/canal.py`). Tudo o que decide fica em código, igual para todo
canal: ficha, preço, troca, parcelas, desconto, trava de qualificação, etapa do kanban e
handoff. O LLM só conversa.

Garantia por teste: `backend/tests/unit/application/test_paridade_canais.py` roda a **mesma
conversa roteirizada** (FakeLLM, ferramentas reais) entrando pelo normalizador da Evolution
(WhatsApp) e pelo do Instagram, e confere que o estado do atendimento (ficha), a etapa do
kanban e os textos de saída são idênticos nos dois canais. Só muda o destinatário (telefone x
IGSID) e o adaptador de saída. A rota do Instagram ainda não existe; o teste monta a cadeia no
nível de `ReceberMensagem` + orquestrador.

Onde os canais realmente diferem, e como tratamos:

| Diferença | WhatsApp (Evolution) | Instagram | Tratamento |
|---|---|---|---|
| Identidade do cliente | telefone | IGSID (sem nome nem telefone) | lead criado com o IGSID; nome exigiria consulta ao perfil |
| Áudio recebido | baixado pela Evolution | URL da CDN que expira | baixar na hora e salvar (como `ReceberMidia`) |
| Eco da própria loja | `fromMe` (pode ser o vendedor no celular) | `is_echo` | ignorado; vendedor no Instagram falaria pelo painel |
| Imagem com legenda | legenda junto | sem legenda em anexo | legenda segue como texto separado |
| Texto longo | sem divisão | limite da Meta (conferir) | hoje não divide; dividir antes de enviar se a Meta recusar |
| Fora da janela de 24 h | sem janela | envio recusado | vira handoff, sem retentativa |
| Follow-up automático | permitido | só dentro de 24 h | desligar no canal |

---

# Referência técnica

## 1. Arquitetura

O Instagram entra como mais um canal, igual ao WhatsApp (`Canal.INSTAGRAM` já existe no
domínio e no CHECK do banco). Nada no agente, no kanban ou no painel muda: eles só veem
`MensagemEntrada`/`MensagemSaida`.

```
Meta (webhook "instagram") --POST--> rota HTTP  [FALTA]
        |  verifica X-Hub-Signature-256       adapters/inbound/instagram/webhook.py
        v
   normalizar(payload)                          adapters/inbound/instagram/normalizar.py
        |  -> list[MensagemEntrada | Ignorado]
        v
   ReceberMensagem (application/canal.py)  -> agenda o worker -> agente
        |
        v
   CanalPort.enviar(MensagemSaida)              adapters/outbound/canal/instagram.py
        |  POST /{versao}/me/messages
        v
   Graph API --> DM do cliente
```

| Peça | Arquivo | Estado |
|---|---|---|
| Normalização do payload (`entry[].messaging[]`) | `app/adapters/inbound/instagram/normalizar.py` | pronto, testado com fixtures |
| Desafio `hub.*` e assinatura `X-Hub-Signature-256` | `app/adapters/inbound/instagram/webhook.py` | pronto (funções puras), testado |
| `InstagramAdapter` (`CanalPort`) | `app/adapters/outbound/canal/instagram.py` | pronto, testado com `httpx.MockTransport` |
| Rota FastAPI `GET/POST /webhooks/instagram` | — | **falta** |
| Registro do canal na composição (`composicao.py`) | — | **falta** |
| Conta Instagram ↔ loja, token por loja | — | **falta** |
| Download da mídia recebida | — | **falta** |
| App Meta, permissões, revisão | — | **falta** (fora do código) |

### O que o normalizador faz

- Texto, imagem (com ou sem legenda) e áudio viram `MensagemEntrada` (`canal=instagram`,
  `remetente` = IGSID do cliente, `id_externo` = `message.mid`, `recebida_em` a partir do
  `timestamp` em milissegundos).
- Resposta a story vira texto normal.
- Ignorados com motivo: eco (`is_echo`, mensagem enviada pela própria conta), reação, leitura,
  postback, mensagem apagada, mensagem não suportada, anexos de outros tipos (vídeo,
  compartilhamento, etc.), `object` diferente de `instagram`, conta sem loja.
- `entry[].id` (id da conta profissional) é traduzido em loja por um `loja_da_conta` injetado.
  Hoje não existe cadastro dessa ligação; ver "O que falta".
- Nunca levanta exceção: o webhook deve responder 200 mesmo para lixo, para a Meta não reenviar.

### O que o adaptador de saída faz

- Texto: `POST {graph}/{versao}/me/messages` com `Authorization: Bearer <token da loja>` e corpo
  `{"recipient": {"id": <IGSID>}, "message": {"text": ...}, "messaging_type": "RESPONSE"}`.
- Imagem/áudio: anexo por URL pública (a Meta baixa o arquivo); a legenda vai em seguida como
  mensagem de texto separada.
- Erros da Graph API viram `ErroInstagram(status, codigo)`; `codigo` é o `error.code` devolvido
  (usado para detectar, por exemplo, resposta fora da janela de 24 h).
- O token vem de um `token_da_loja(loja_id)` injetado. Sem token, não há chamada.
- Host e versão da Graph API são parâmetros (`graph.instagram.com` e `v21.0` por padrão;
  **conferir a versão e o host vigentes** na documentação da Meta).

## 2. Passos para produção

### 2.1 Conta e app

1. Conta **profissional** do Instagram (comercial ou criador) da loja, ligada a uma **Página do
   Facebook** (necessário no fluxo com Facebook Login; **conferir** se o fluxo "Instagram API
   with Instagram Login" dispensa a Página).
2. Conta **Meta for Developers** e um **app** do tipo Negócios (Business) criado em um
   **Business Portfolio** (Meta Business Suite) da empresa.
3. Adicionar ao app o produto **Instagram** (API de mensagens) e, se usar Facebook Login, o
   produto **Messenger**/Webhooks.
4. Em Configurações do app, anotar **App ID** e **App Secret** (o secret assina os webhooks) e
   definir a URL de política de privacidade e demais campos obrigatórios.

### 2.2 Permissões

Pedir (e justificar no App Review) **(conferir nomes e exigências atuais na documentação da Meta)**:

| Permissão | Para quê |
|---|---|
| `instagram_basic` | ler o perfil básico da conta e identificar o cliente |
| `instagram_manage_messages` | receber e enviar DMs |
| `pages_manage_metadata` | assinar os webhooks da Página/conta |
| `pages_show_list` / `pages_messaging` | podem ser exigidas no fluxo com Facebook Login (**conferir**) |

Em modo de **desenvolvimento**, essas permissões funcionam só para quem tem função no app
(administrador, desenvolvedor, testador): serve para testar com contas internas antes da revisão.

### 2.3 App Review e verificação de empresa

1. Concluir a **Verificação da empresa** (Business Verification) do portfólio; costuma ser
   exigida para acesso avançado **(conferir)**.
2. Pedir **Acesso avançado** às permissões acima via **App Review**: vídeo de screencast
   mostrando o fluxo (cliente manda DM, o atendente responde), descrição do caso de uso,
   credenciais de teste e política de privacidade.
3. Prazo e taxa de aprovação variam e podem exigir várias rodadas **(conferir; não planejar
   com data fixa)**. Foi esse o motivo de o Diferencial 5 ficar como esqueleto.
4. Depois de aprovado, colocar o app em modo **Live**.

### 2.4 Webhook

1. Subir a rota (item 3) em uma URL **HTTPS pública**.
2. No painel do app, em Webhooks, objeto **Instagram**, informar a URL de callback e um
   **Verify Token** (segredo nosso). A Meta faz um `GET` com `hub.mode=subscribe`,
   `hub.verify_token` e `hub.challenge`; a rota responde o challenge em texto puro se o token
   bater (`responder_desafio`) e 403 caso contrário.
3. Assinar o campo **`messages`** (e, se quiser tratar, `messaging_postbacks`,
   `message_reactions`, `messaging_seen`; hoje esses são ignorados).
4. Assinar o app na conta/Página de cada loja (chamada à API de `subscribed_apps` **(conferir
   o endpoint e os campos)**).
5. Cada `POST` traz `X-Hub-Signature-256: sha256=<hmac>`: HMAC-SHA256 do **corpo cru** com o App
   Secret. Validar com `assinatura_valida(corpo, cabecalho, app_secret)` **antes** de fazer
   `json.loads` (a rota deve ler `await request.body()`), e responder 200 rápido, processando
   no worker.
6. A Meta reenvia entregas que não receberam 200 **(conferir política de retentativa)**. A
   idempotência já existe: `registrar_entrada` ignora o `mid` repetido por `(canal, id_externo)`.

### 2.5 Tokens

- Cada loja autoriza o app (OAuth) e gera um **token de acesso de longa duração** da conta
  profissional; ele expira e precisa ser **renovado** **(conferir validade e fluxo de refresh)**.
- Armazenar por loja, criptografado, nunca em `.env` versionado. Hoje não há tabela para isso.

## 3. Regras de mensagens (conferir na documentação da Meta)

- **Janela de resposta de 24 h**: a loja só pode responder dentro de uma janela contada a
  partir da última mensagem do cliente. Fora dela a API recusa o envio (erro com `error.code`
  específico, exposto em `ErroInstagram.codigo`). O agente deve tratar essa falha como "passar
  para o vendedor", e não tentar reenviar.
- **Tags de mensagem**: existe uma tag para atendimento humano que estende a janela
  (`HUMAN_AGENT`, a Meta fala em até 7 dias) e exige permissão/uso específico. O adaptador
  hoje manda sempre `messaging_type=RESPONSE`; usar a tag exigiria um campo novo em
  `MensagemSaida` ou outro adaptador. **Não usar para disparar promoção**: é motivo de rejeição.
- **Respostas a comentários e a stories/menções**: tratadas por outros eventos/fluxos; só
  resposta a story (DM) é normalizada hoje.
- **Limites**: tamanho máximo do texto de uma DM, tipos e tamanhos de mídia aceitos, e taxa de
  envio por conta. O adaptador **não divide** textos longos nem valida mídia: se a Meta recusar,
  vira `ErroInstagram`. Conferir os limites e, se preciso, dividir o texto antes de enviar.
- **Mídia recebida**: a URL do anexo é um link da CDN da Meta que expira. Hoje `midia_url`
  carrega esse link bruto; para o fluxo de áudio/imagem funcionar, é preciso baixar logo ao
  receber e salvar no armazenamento de mídia (como o WhatsApp faz com `ReceberMidia`).
- **Cliente**: o webhook traz só o IGSID; nome e usuário exigem uma consulta ao perfil
  **(conferir permissão e campos)**. O lead é criado com o IGSID como contato.

## 4. O que falta (checklist para o próximo ciclo)

1. Rota `GET/POST /webhooks/instagram` em `adapters/inbound/http/`, com `include_in_schema=False`:
   `GET` usa `responder_desafio`; `POST` lê o corpo cru, valida `assinatura_valida`, chama
   `normalizar`, descarta `Ignorado` e chama `ReceberMensagem` para cada `MensagemEntrada`.
   Registrar só se as variáveis `INSTAGRAM_*` estiverem preenchidas (vazio = desligado, sem
   mudar o comportamento atual). Variáveis previstas: `INSTAGRAM_APP_SECRET`,
   `INSTAGRAM_VERIFY_TOKEN`, `INSTAGRAM_GRAPH_VERSAO`.
2. Cadastro conta Instagram ↔ loja (`loja_da_conta`) e token por loja (`token_da_loja`),
   com tela de conexão no painel (OAuth) e renovação do token.
3. Registrar `InstagramAdapter` como o `CanalPort` do `Canal.INSTAGRAM` em `composicao.py`
   (hoje a composição só conhece webchat e WhatsApp).
4. Baixar e armazenar mídia recebida (ver acima).
5. Tratar falha de envio fora da janela de 24 h (handoff para o vendedor) e desligar o
   follow-up automático para o canal `instagram`.
6. Criar o app Meta, a verificação da empresa e submeter o App Review.
7. Teste ponta a ponta com uma conta de teste do Instagram em modo desenvolvimento, antes da
   revisão; só depois, o teste com a conta real da loja.

## 5. Como testar o que existe

```bash
cd backend
uv run pytest tests/unit/adapters/test_instagram_normalizar.py \
              tests/unit/adapters/test_instagram_webhook.py \
              tests/unit/adapters/test_instagram_adapter.py
```

O teste de paridade com o WhatsApp está em
`tests/unit/application/test_paridade_canais.py`.

Fixtures anonimizadas do webhook em `backend/tests/fixtures/instagram/` (texto, imagem, áudio,
resposta a story, eco, reação, leitura, postback, apagada, lote com duas mensagens, etc.). Os
ids e URLs são fictícios; ao capturar payloads reais para novas fixtures, anonimizar IGSID,
contas e assinaturas de URL.
