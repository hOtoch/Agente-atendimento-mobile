# Teste de carga (k6)

Simula webhooks da Evolution (`POST /webhooks/evolution`, `messages.upsert`) com **10× o pico
esperado** (400 msg/min; ver `context.md` §6) contra uma pilha **isolada** (API, workers, banco e
Redis próprios; não toca na API/worker/banco de desenvolvimento). Sem custo: o LLM é simulado e a
Evolution é um stub local. Resultados e plano: [`docs/black-friday.md`](../../docs/black-friday.md).

## Rodar

Pré-requisitos: infra local no ar (Postgres de teste na 5433 e Redis na 6379), Docker e `uv`
(`cd backend && uv sync`). O k6 não precisa estar instalado: roda pela imagem oficial.

```bash
bash infra/k6/rodar_carga.sh                       # 400 msg/min por 5 min, 1 worker
WORKERS=2 bash infra/k6/rodar_carga.sh             # 2 workers
RATE_POR_MIN=40 DURACAO_S=120 bash infra/k6/rodar_carga.sh   # 1x (linha de base)
```

Variáveis: `WORKERS`, `RATE_POR_MIN`, `DURACAO_S`, `LEADS`, `REENTREGA_A_CADA`,
`LLM_FAKE_LATENCIA_MS` (2750) e `LLM_FAKE_JITTER_MS` (1250, ou seja 1,5 a 4 s por chamada),
`API_PORTA` (8100), `STUB_PORTA` (8199), `REDIS_DB` (5; o script aborta se não estiver vazio).

O script: cria o banco `carga_<run>` no Postgres de teste, migra e roda o seed; sobe o stub da
Evolution, a API (uvicorn) e os workers (arq); amostra a fila a cada 1 s; roda o k6; espera a fila
esvaziar; roda a checagem de contagem e o resumo; e **apaga tudo** (processos, banco, DB do
Redis). A saída fica em `infra/k6/saida/<run>/` (ignorada pelo git), com `relatorio.txt`.
Código de saída ≠ 0 se alguma mensagem foi perdida ou duplicada.

Só o k6, à mão (com a pilha já no ar):

```bash
docker run --rm --network host --user "$(id -u):$(id -g)" \
  -v "$PWD/infra/k6:/scripts:ro" -v "$PWD/infra/k6/saida:/saida" \
  -e BASE_URL=http://localhost:8100 -e WEBHOOK_TOKEN=token-carga -e RUN_ID=manual1 \
  grafana/k6 run --out json=/saida/eventos.json --summary-export=/saida/resumo.json \
  /scripts/carga-webhook.js
```

## Peças

| Arquivo | Papel |
|---|---|
| `carga-webhook.js` | Cenário k6: taxa constante de chegada, leads em rajadas de 1 a 4 mensagens, reentrega simultânea do mesmo id a cada 20 mensagens. Cada requisição vira um ponto `msg_enviada` (id, status, resultado). |
| `stub_evolution.py` | Evolution falsa: aceita qualquer envio e registra quando chegou (mede a latência até a resposta ao cliente). |
| `rodar_carga.sh` | Orquestra a pilha isolada e a limpeza. |
| `backend/scripts/amostrar_fila.py` | CSV de 1 s com tamanho da fila arq (total, prontos, em execução) e contagem de mensagens. |
| `backend/scripts/analisar_carga.py` | Resumo: latência de ingestão (k6), fila, throughput do worker e latência até a resposta. |
| `backend/scripts/checar_contagem.py` | Checagem pós-teste: ids que o k6 enviou × `mensagens.id_externo` no banco (perdidas, duplicadas, inesperadas). Testada em `backend/tests/unit/infra`. |

O LLM simulado (`LLM_FAKE_LATENCIA_MS`, em `backend/app/infra/settings.py`) **nunca** liga por
padrão e, quando ligado, tem precedência sobre `ANTHROPIC_API_KEY`: nenhuma chamada paga é feita.
