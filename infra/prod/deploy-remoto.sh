#!/usr/bin/env bash
# Parte do deploy que roda NA VPS (como root). Chamado pelo infra/prod/deploy.ps1, de dentro do
# release ja extraido:  bash <release>/infra/prod/deploy-remoto.sh <release> <dominio>
#
# Layout:
#   /opt/atendimento/releases/<data>-<sha>/   um diretorio por deploy (os 3 mais recentes ficam)
#   /opt/atendimento/app -> releases/<atual>  link usado pelos servicos systemd
#   /opt/atendimento/shared/.env              .env de producao (fica fora dos releases)
#   /opt/atendimento/shared/midias/           midias do chat (backend/.midias aponta para ca)
#
# Se a API ou o painel nao responderem depois do restart, volta o link para o release anterior.
set -euo pipefail

RELEASE="$1"
DOMINIO="$2"
BASE=/opt/atendimento
APP="$BASE/app"
SHARED="$BASE/shared"
COMO_ATENDIMENTO=(sudo -u atendimento -H env "UV_CACHE_DIR=$BASE/.cache/uv")

passo() { printf '\n== %s\n' "$*"; }

[ -d "$RELEASE/backend" ] && [ -f "$RELEASE/frontend/.next/BUILD_ID" ] || {
  echo "release incompleto: $RELEASE" >&2
  exit 1
}

passo "layout compartilhado"
mkdir -p "$SHARED/midias" "$BASE/releases" "$BASE/.cache"
if [ -d "$APP" ] && [ ! -L "$APP" ]; then
  # Primeira vez: o app era um diretorio comum. Move .env e midias para shared/ e guarda o resto.
  [ -f "$APP/.env" ] && [ ! -f "$SHARED/.env" ] && mv "$APP/.env" "$SHARED/.env"
  if [ -d "$APP/backend/.midias" ]; then
    cp -a "$APP/backend/.midias/." "$SHARED/midias/" 2>/dev/null || true
  fi
  mv "$APP" "$BASE/releases/legado-$(date +%Y%m%d%H%M%S)"
  echo "app antigo movido para releases/ (legado)"
fi
[ -f "$SHARED/.env" ] || { echo "falta $SHARED/.env" >&2; exit 1; }
chmod 600 "$SHARED/.env"
ln -sfn "$SHARED/.env" "$RELEASE/.env"
rm -rf "$RELEASE/backend/.midias"
ln -sfn "$SHARED/midias" "$RELEASE/backend/.midias"
chown -R atendimento:atendimento "$RELEASE" "$SHARED" "$BASE/.cache"

passo "dependencias"
"${COMO_ATENDIMENTO[@]}" bash -c "cd '$RELEASE/backend' && uv sync --no-dev --frozen -q"
"${COMO_ATENDIMENTO[@]}" bash -c "cd '$RELEASE/frontend' && npm ci --omit=dev --no-audit --no-fund --loglevel=error"

passo "infra (docker compose)"
cd "$RELEASE"
docker compose -f infra/docker-compose.yml -f infra/prod/docker-compose.prod.yml --env-file "$SHARED/.env" \
  up -d --wait postgres redis evolution-postgres evolution-redis evolution-api

passo "migrations"
"${COMO_ATENDIMENTO[@]}" bash -c "cd '$RELEASE/backend' && uv run --no-sync alembic upgrade head"

passo "systemd e caddy"
ANTERIOR="$(readlink -f "$APP" 2>/dev/null || true)"
for unidade in "$RELEASE"/infra/prod/*.service; do
  install -m 644 "$unidade" /etc/systemd/system/
done
systemctl daemon-reload
sed "s/^DOMINIO {/$DOMINIO {/" infra/prod/Caddyfile > /tmp/Caddyfile.novo
if ! cmp -s /tmp/Caddyfile.novo /etc/caddy/Caddyfile; then
  caddy validate --config /tmp/Caddyfile.novo --adapter caddyfile >/dev/null
  install -m 644 /tmp/Caddyfile.novo /etc/caddy/Caddyfile
  systemctl reload caddy
  echo "Caddyfile atualizado"
fi
rm -f /tmp/Caddyfile.novo

trocar_para() {
  ln -sfn "$1" "$APP.novo" && mv -T "$APP.novo" "$APP"
  systemctl restart atendimento-api atendimento-worker atendimento-painel
}

no_ar() {
  local _
  for _ in $(seq 1 40); do
    if curl -fs -m 3 http://127.0.0.1:8000/health >/dev/null &&
      curl -fs -m 5 -o /dev/null http://127.0.0.1:3000/login; then
      return 0
    fi
    sleep 3
  done
  return 1
}

passo "trocar para o release novo"
trocar_para "$RELEASE"
if ! no_ar; then
  echo "API ou painel nao responderam em 2 min." >&2
  journalctl -u atendimento-api -u atendimento-painel -n 30 --no-pager -o cat >&2 || true
  if [ -n "$ANTERIOR" ] && [ -d "$ANTERIOR" ] && [ "$ANTERIOR" != "$RELEASE" ]; then
    echo "ROLLBACK para $ANTERIOR" >&2
    trocar_para "$ANTERIOR"
    no_ar && echo "release anterior de volta no ar" >&2
  fi
  exit 1
fi
systemctl is-active atendimento-worker >/dev/null || { echo "worker nao subiu" >&2; exit 1; }

passo "limpeza (mantem os 3 releases mais recentes)"
ATUAL="$(readlink -f "$APP")"
find "$BASE/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2- |
  tail -n +4 | while read -r antigo; do
  [ "$antigo" = "$ATUAL" ] || [ "$antigo" = "$ANTERIOR" ] || { rm -rf "$antigo" && echo "removido: $antigo"; }
done

echo
echo "OK: $(basename "$RELEASE") no ar"
