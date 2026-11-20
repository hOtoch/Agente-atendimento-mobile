#!/usr/bin/env bash
# Gerencia a infra local. Rode dentro do WSL:
#   wsl -e sh -c "cd '/mnt/d/.../repo' && bash infra/dev.sh up"
set -eu
cd "$(dirname "$0")/.."
ENVARGS=""
[ -f .env ] && ENVARGS="--env-file .env"
dc() { docker compose -f infra/docker-compose.yml $ENVARGS "$@"; }

case "${1:-}" in
  up)    dc up -d --wait ;;
  down)  dc down ;;
  logs)  shift; dc logs -f --tail=100 "$@" ;;
  ps)    dc ps ;;
  reset) dc down --volumes && dc up -d --wait ;;
  *) echo "uso: dev.sh {up|down|logs [servico]|ps|reset}"; exit 2 ;;
esac
