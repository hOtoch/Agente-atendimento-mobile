#!/usr/bin/env bash
# Gerencia a infra local. Rode dentro do WSL:
#   wsl -e sh -c "cd '/mnt/d/.../repo' && bash infra/dev.sh up"
set -eu
cd "$(dirname "$0")/.."
ENVARGS=""
[ -f .env ] && ENVARGS="--env-file .env"
# Docker dentro do WSL com a API rodando no Windows: `host-gateway` aponta para a VM do WSL, nao
# para o Windows, e o webhook da Evolution leva ECONNREFUSED. No WSL (modo NAT) o Windows e o
# gateway padrao; o IP muda a cada boot, entao e descoberto aqui. Fora do WSL fica host-gateway.
if [ -z "${API_HOST_IP:-}" ] && grep -qi microsoft /proc/version 2>/dev/null; then
  API_HOST_IP="$(ip route | awk '/^default/ {print $3; exit}')"
  export API_HOST_IP
fi
dc() { docker compose -f infra/docker-compose.yml $ENVARGS "$@"; }

case "${1:-}" in
  up)    dc up -d --wait ;;
  down)  dc down ;;
  logs)  shift; dc logs -f --tail=100 "$@" ;;
  ps)    dc ps ;;
  reset) dc down --volumes && dc up -d --wait ;;
  *) echo "uso: dev.sh {up|down|logs [servico]|ps|reset}"; exit 2 ;;
esac
