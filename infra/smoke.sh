#!/usr/bin/env bash
# Smoke test da infra local: healthchecks dos containers + portas + Evolution.
# Uso (Windows): wsl -e sh -c "cd '/mnt/d/.../repo' && bash infra/smoke.sh"
set -u
PROJECT="${COMPOSE_PROJECT_NAME:-atendimento}"
fail=0

ok()   { echo "[OK]   $1"; }
nok()  { echo "[FAIL] $1"; fail=1; }

check_health() {
  local svc="$1" status
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}sem-healthcheck{{end}}' "${PROJECT}-${svc}-1" 2>/dev/null) || status="ausente"
  if [ "$status" = "healthy" ]; then ok "healthcheck $svc"; else nok "healthcheck $svc ($status)"; fi
}

check_port() {
  local name="$1" port="$2"
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then ok "porta $port ($name)"; else nok "porta $port ($name)"; fi
}

for svc in postgres postgres-test redis evolution-postgres evolution-redis evolution-api erp-mock; do
  check_health "$svc"
done

check_port postgres 5432
check_port postgres-test 5433
check_port redis 6379
check_port evolution-api 8080
check_port erp-mock 8090

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8080/ 2>/dev/null || true)
if [ "$code" = "200" ]; then ok "Evolution GET / = 200"; else nok "Evolution GET / = ${code:-sem resposta}"; fi

# ERP simulado: /health sem auth, /produtos exige token
if [ -z "${ERP_MOCK_TOKEN:-}" ] && [ -f .env ]; then
  ERP_MOCK_TOKEN=$(grep -E '^ERP_MOCK_TOKEN=' .env | tail -n1 | cut -d= -f2- | sed 's/[[:space:]]*$//')
fi
ERP_MOCK_TOKEN="${ERP_MOCK_TOKEN:-token-dev}"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8090/health 2>/dev/null || true)
if [ "$code" = "200" ]; then ok "ERP mock GET /health = 200"; else nok "ERP mock GET /health = ${code:-sem resposta}"; fi
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8090/produtos 2>/dev/null || true)
if [ "$code" = "401" ]; then ok "ERP mock GET /produtos sem token = 401"; else nok "ERP mock GET /produtos sem token = ${code:-sem resposta}"; fi
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Authorization: Bearer ${ERP_MOCK_TOKEN}" "http://127.0.0.1:8090/produtos?tamanho=1" 2>/dev/null || true)
if [ "$code" = "200" ]; then ok "ERP mock GET /produtos com token = 200"; else nok "ERP mock GET /produtos com token = ${code:-sem resposta}"; fi

if [ "$fail" -ne 0 ]; then echo "SMOKE: FALHOU"; exit 1; fi
echo "SMOKE: OK"
