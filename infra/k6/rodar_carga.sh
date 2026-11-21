#!/usr/bin/env bash
# Teste de carga ponta a ponta numa pilha ISOLADA (nao toca a API/worker/banco de desenvolvimento).
#
#   bash infra/k6/rodar_carga.sh                        # 10x o pico (400 msg/min), 5 min, 1 worker
#   WORKERS=2 bash infra/k6/rodar_carga.sh              # com 2 workers
#   RATE_POR_MIN=40 DURACAO_S=120 bash infra/k6/rodar_carga.sh   # 1x (linha de base)
#
# Pre-requisitos: infra local no ar (Postgres de teste 5433 e Redis 6379), Docker (imagem
# grafana/k6) e uv. O banco `carga_<run>` e o DB 5 do Redis sao criados/apagados aqui.
# Sem chamadas pagas: o LLM e simulado (LLM_FAKE_LATENCIA_MS) e as chaves reais sao removidas
# do ambiente. A Evolution e uma falsa local (stub_evolution.py).
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$AQUI/../../backend" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

WORKERS="${WORKERS:-1}"
RATE_POR_MIN="${RATE_POR_MIN:-400}"
DURACAO_S="${DURACAO_S:-300}"
LEADS="${LEADS:-250}"
REENTREGA_A_CADA="${REENTREGA_A_CADA:-20}"
LLM_FAKE_LATENCIA_MS="${LLM_FAKE_LATENCIA_MS:-2750}"   # 1,5 a 4 s (media 2,75 s)
LLM_FAKE_JITTER_MS="${LLM_FAKE_JITTER_MS:-1250}"
API_PORTA="${API_PORTA:-8100}"
STUB_PORTA="${STUB_PORTA:-8199}"
REDIS_DB="${REDIS_DB:-5}"
CONTAINER_PG="${CONTAINER_PG:-atendimento-postgres-test-1}"
CONTAINER_REDIS="${CONTAINER_REDIS:-atendimento-redis-1}"
ESVAZIAR_TIMEOUT_S="${ESVAZIAR_TIMEOUT_S:-900}"
LOJA_ID="00000000-0000-4000-8000-00000000de30"   # loja demo (LOJA_DEMO_ID do seed)
TOKEN="token-carga"

RUN_ID="$(date +%s)"
BANCO="carga_${RUN_ID}"
SAIDA="$AQUI/saida/$RUN_ID"
mkdir -p "$SAIDA"
PIDS=()
VENV="$BACKEND/.venv/bin"   # direto do venv: o PID e do processo real (uv run criaria um intermediario)

URL_BANCO="postgresql+asyncpg://teste:teste@localhost:5433/${BANCO}"
URL_REDIS="redis://localhost:6379/${REDIS_DB}"

psql_admin() { docker exec "$CONTAINER_PG" psql -U teste -d postgres -v ON_ERROR_STOP=1 -qc "$1"; }
redis_cli() { docker exec "$CONTAINER_REDIS" redis-cli -n "$REDIS_DB" "$@"; }

limpar() {
  set +e
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null; done
  sleep 1
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null; done
  redis_cli flushdb >/dev/null 2>&1
  psql_admin "DROP DATABASE IF EXISTS \"${BANCO}\" WITH (FORCE)" >/dev/null 2>&1
  echo "limpeza: processos encerrados, banco ${BANCO} e DB ${REDIS_DB} do Redis apagados"
}
# Guardas ANTES do trap: a limpeza faz flushdb, entao nunca pode rodar num DB que ja tinha dados.
if [ "$REDIS_DB" = "0" ]; then
  echo "REDIS_DB=0 e o Redis de dev; escolha outro com REDIS_DB=<n>" >&2
  exit 2
fi
if [ "$(redis_cli dbsize)" != "0" ]; then
  echo "DB ${REDIS_DB} do Redis nao esta vazio; escolha outro com REDIS_DB=<n>" >&2
  exit 2
fi
trap limpar EXIT

# Nada de custo: sem chaves reais no ambiente dos processos de teste.
unset ANTHROPIC_API_KEY OPENAI_API_KEY
export DATABASE_URL="$URL_BANCO" REDIS_URL="$URL_REDIS"
export EVOLUTION_API_URL="http://127.0.0.1:${STUB_PORTA}" EVOLUTION_API_KEY="chave-carga"
export EVOLUTION_WEBHOOK_TOKEN="$TOKEN" MIDIA_DIR="$SAIDA/midias"
export LLM_FAKE_LATENCIA_MS LLM_FAKE_JITTER_MS

echo "== preparando pilha isolada (banco ${BANCO}, Redis DB ${REDIS_DB}, API :${API_PORTA}) =="
psql_admin "CREATE DATABASE \"${BANCO}\""
(cd "$BACKEND" && uv run alembic upgrade head >"$SAIDA/migracao.log" 2>&1 \
  && uv run python -m app.infra.seed >"$SAIDA/seed.log" 2>&1)

python3 "$AQUI/stub_evolution.py" --porta "$STUB_PORTA" --log "$SAIDA/stub.jsonl" &
PIDS+=($!)
(cd "$BACKEND" && exec "$VENV/uvicorn" app.main:app --port "$API_PORTA" --log-level warning \
  >"$SAIDA/api.log" 2>&1) &
PIDS+=($!)
for n in $(seq 1 "$WORKERS"); do
  (cd "$BACKEND" && exec "$VENV/arq" app.infra.worker.WorkerSettings >"$SAIDA/worker${n}.log" 2>&1) &
  PIDS+=($!)
done
(cd "$BACKEND" && exec "$VENV/python" scripts/amostrar_fila.py --redis-url "$URL_REDIS" \
  --database-url "$URL_BANCO" --saida "$SAIDA/fila.csv" >"$SAIDA/amostrador.log" 2>&1) &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -fs "http://localhost:${API_PORTA}/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fs "http://localhost:${API_PORTA}/health" >/dev/null
sleep 5  # workers sobem

echo "== k6: ${RATE_POR_MIN} msg/min por ${DURACAO_S}s, ${LEADS} leads, ${WORKERS} worker(s) =="
INICIO_CARGA="$(date +%s.%N)"
docker run --rm --network host --user "$(id -u):$(id -g)" \
  -v "$AQUI:/scripts:ro" -v "$SAIDA:/saida" \
  -e BASE_URL="http://localhost:${API_PORTA}" -e LOJA_ID="$LOJA_ID" -e WEBHOOK_TOKEN="$TOKEN" \
  -e RATE_POR_MIN="$RATE_POR_MIN" -e DURACAO_S="$DURACAO_S" -e LEADS="$LEADS" \
  -e REENTREGA_A_CADA="$REENTREGA_A_CADA" -e PREFIXO="carga-" -e RUN_ID="$RUN_ID" \
  grafana/k6 run --out json=/saida/eventos.json --summary-export=/saida/resumo.json \
  /scripts/carga-webhook.js | tee "$SAIDA/k6.log" || true
FIM_CARGA="$(date +%s.%N)"

echo "== aguardando a fila esvaziar (ate ${ESVAZIAR_TIMEOUT_S}s) =="
LIMITE=$(( $(date +%s) + ESVAZIAR_TIMEOUT_S ))
CALMA=0
while [ "$(date +%s)" -lt "$LIMITE" ]; do
  ULTIMA="$(tail -n 1 "$SAIDA/fila.csv")"
  IFS=, read -r _ zcard _ em_execucao _ <<<"$ULTIMA"
  if [ "${zcard:-1}" = "0" ] && [ "${em_execucao:-1}" = "0" ]; then CALMA=$((CALMA + 1)); else CALMA=0; fi
  [ "$CALMA" -ge 10 ] && break
  sleep 1
done
sleep 2
kill "${PIDS[${#PIDS[@]}-1]}" 2>/dev/null || true   # amostrador: fecha o CSV
sleep 1

echo "== checagem de contagem e metricas =="
{
  echo "run ${RUN_ID}: workers=${WORKERS} taxa=${RATE_POR_MIN}/min duracao=${DURACAO_S}s leads=${LEADS}"
  echo "llm simulado: ${LLM_FAKE_LATENCIA_MS}ms +/- ${LLM_FAKE_JITTER_MS}ms"
  (cd "$BACKEND" && uv run python scripts/analisar_carga.py --k6-json "$SAIDA/eventos.json" \
    --k6-resumo "$SAIDA/resumo.json" --stub-log "$SAIDA/stub.jsonl" --fila-csv "$SAIDA/fila.csv" \
    --fim-carga "$FIM_CARGA")
  echo "== Contagem de mensagens (k6 x banco) =="
  set +e
  (cd "$BACKEND" && uv run python scripts/checar_contagem.py --k6-json "$SAIDA/eventos.json" \
    --database-url "$URL_BANCO" --loja-id "$LOJA_ID" --prefixo "carga-${RUN_ID}-")
  echo $? >"$SAIDA/codigo_checagem"
  set -e
  echo "(inicio do k6: ${INICIO_CARGA}, fim: ${FIM_CARGA})"
} 2>&1 | tee "$SAIDA/relatorio.txt"
echo "saida completa em ${SAIDA}"
exit "$(cat "$SAIDA/codigo_checagem")"
