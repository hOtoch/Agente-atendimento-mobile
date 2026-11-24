# Deploy na VPS (1 vCPU, um domínio)

Guia para colocar a plataforma no ar numa VPS pequena, no formato usado no primeiro deploy
(Ubuntu 26.04, 1 vCPU, 4 GB, Hostinger). O desenho: **um domínio só**, com o Caddy na frente servindo
o painel em `/` e a API em `/api`. Assim o navegador fala com uma origem única (sem CORS entre sites)
e o cookie de sessão funciona com `Secure`.

```
navegador --HTTPS--> Caddy (443)
                      |-- /api/*  -> API (uvicorn, 127.0.0.1:8000)   (prefixo /api removido)
                      '-- /*      -> painel (next start, 127.0.0.1:3000)
Postgres, Redis e Evolution: Docker, só em 127.0.0.1 (5432, 6379, 8080)
```

Arquivos de produção em [`infra/prod/`](../infra/prod):

| Arquivo | Vai para |
|---|---|
| `docker-compose.prod.yml` | override do `infra/docker-compose.yml` (portas presas em `127.0.0.1`, `restart: unless-stopped`) |
| `Caddyfile` | `/etc/caddy/Caddyfile` (troque `DOMINIO`) |
| `atendimento-api.service`, `atendimento-worker.service`, `atendimento-painel.service` | `/etc/systemd/system/` |

## 1. Recursos

A pilha mede cerca de **1,5 a 2 GB de RAM**: Postgres + Redis ~130 MB, Evolution e seus bancos
~200 a 300 MB, API + 1 worker ~300 a 400 MB, painel (`next start`) ~150 a 250 MB, SO + Docker
~400 MB. Crie **2 GB de swap** como folga para picos.

## 2. Preparar a VPS (uma vez, como root)

- **Acesso por chave SSH** (não por senha): gere uma chave na sua máquina e cole a pública no painel
  da hospedagem (Hostinger: VPS → Gerenciar → Configurações → Chaves SSH).
- **Swap**: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
  e a linha `/swapfile none swap sw 0 0` no `/etc/fstab`.
- **Firewall**: `ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable`
  (libere o SSH **antes** de ligar). Atenção: portas publicadas pelo Docker passam por cima do ufw;
  por isso o override de produção prende Postgres, Redis e Evolution em `127.0.0.1`.
- **Usuário de serviço**: `useradd --system --create-home --home-dir /opt/atendimento --shell
  /usr/sbin/nologin atendimento && usermod -aG docker atendimento`.
- **Pacotes** (fontes oficiais): Docker + Compose, Caddy (repositório da Caddy), Node 24 (NodeSource)
  e `uv` (`curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh`).

## 3. Variáveis do `.env` de produção

O `.env` fica em `/opt/atendimento/app/.env` (raiz do repo; o backend lê `../.env`), dono
`atendimento`, permissão `600`. Gere os segredos **no servidor** (`openssl rand -hex 24`), nunca
copie os do dev. Troque `dominio.com` pelo seu domínio.

| Variável | Valor em produção | Por quê |
|---|---|---|
| `COOKIE_SECURE` | `true` | O cookie `sessao` só trafega por HTTPS |
| `CONFIAR_PROXY` | `true` | A API está atrás do Caddy: usa o **último** IP do `X-Forwarded-For` no limite de tentativas de login |
| `CORS_ORIGINS` | `https://dominio.com` | Origem exata do painel; o CORS usa credenciais, não aceita `*` |
| `API_PUBLICA_URL` | `https://dominio.com/api` | Base das URLs de mídia (imagens/áudios) que a API devolve |
| `PAINEL_URL` | `https://dominio.com` | Base do link da conversa na mensagem ao vendedor |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | senha forte (a mesma nos dois) | Não deixe `atendimento/atendimento` |
| `EVOLUTION_API_KEY`, `EVOLUTION_WEBHOOK_TOKEN`, `EVOLUTION_DB_PASSWORD` | valores novos e secretos | Os do `.env.example` são só de dev |
| `EVOLUTION_WEBHOOK_URL` | `https://dominio.com/api/webhooks/evolution` | O webhook entra pelo domínio (a API escuta só em `127.0.0.1`) |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_FALLBACK_MODEL` | os mesmos do dev | Provedor e modelos |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | suas chaves | Só no `.env` do servidor; o dono coloca com `nano`, sem passar por histórico de shell |
| `SEED_SENHA_DEMO` | **ausente** | Em produção não rode o seed da loja demo |

`NEXT_PUBLIC_API_URL` não fica no `.env` do servidor: é lida **no build** do painel (abaixo).

## 4. Enviar o código

O repositório é privado: em vez de clonar na VPS (o que exigiria credencial do GitHub lá), envie um
pacote do `main`.

1. **Build do painel na sua máquina** (1 vCPU não aguenta o `next build` com folga), com a API em `/api`.
   No Windows, **rode pelo PowerShell**: o Git Bash converte `/api` num caminho do Windows
   (`C:/Program Files/Git/api`) e esse valor vai parar no bundle.
   ```powershell
   cd frontend; $env:NEXT_PUBLIC_API_URL = '/api'; npm run build
   ```
   Confira: `grep -r "Program Files" .next/static` não pode achar nada.
2. **Pacotes**: `git archive --format=tar.gz -o app.tar.gz HEAD` e
   `tar -czf next.tar.gz --exclude=.next/cache --exclude=.next/dev .next` (em `frontend/`; no Git Bash
   use `tar --force-local` se o destino tiver `C:`).
3. **Na VPS**: extraia `app.tar.gz` em `/opt/atendimento/app` (o `.env` é preservado), substitua
   `frontend/.next` pelo `next.tar.gz`, `chown -R atendimento:atendimento /opt/atendimento` e instale as
   dependências como `atendimento`:
   ```bash
   cd /opt/atendimento/app/backend && UV_CACHE_DIR=/opt/atendimento/.cache/uv uv sync --no-dev --frozen
   cd ../frontend && npm ci --omit=dev
   ```

## 5. Subir

Na raiz do repo na VPS:

```bash
docker compose -f infra/docker-compose.yml -f infra/prod/docker-compose.prod.yml --env-file .env \
  up -d --wait postgres redis evolution-postgres evolution-redis evolution-api
sudo -u atendimento -H bash -c 'cd backend && UV_CACHE_DIR=/opt/atendimento/.cache/uv uv run --no-sync alembic upgrade head'
cp infra/prod/*.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now atendimento-api atendimento-worker atendimento-painel
sed "s/^DOMINIO {/dominio.com {/" infra/prod/Caddyfile > /etc/caddy/Caddyfile && systemctl reload caddy
```

Não suba `postgres-test` (só testes) nem `erp-mock` (só dev/demo). O Caddy emite e renova o
certificado sozinho (o domínio precisa apontar para o IP da VPS e as portas 80/443 estarem abertas).

Sem domínio próprio ainda, `<ip-com-hifens>.sslip.io` (ex.: `189-24-10-237.sslip.io`) resolve para o
IP e recebe certificado de verdade; para trocar depois, mude a linha do domínio no Caddyfile e as três
URLs do `.env` (`CORS_ORIGINS`, `PAINEL_URL`, `API_PUBLICA_URL`, mais `EVOLUTION_WEBHOOK_URL`), recarregue o
Caddy e reinicie API e worker.

Crie a primeira loja e o login do dono (a senha provisória aparece uma única vez):

```bash
cd /opt/atendimento/app/backend && sudo -u atendimento -H env UV_CACHE_DIR=/opt/atendimento/.cache/uv \
  uv run --no-sync python scripts/criar_loja.py --nome "Loja X" --email dono@loja.com
```

Depois de mudar o `.env`: `systemctl restart atendimento-api atendimento-worker`. Logs:
`journalctl -u atendimento-api -f` (idem `-worker`, `-painel`, `caddy`).

## 6. Conferir

- `https://dominio.com/api/health` responde `{"status":"ok",...}` e `http://` redireciona para `https://`.
- `https://dominio.com/login` abre; entrar com o e-mail e a senha provisória pede a troca de senha.
- O cookie `sessao` aparece com `Secure` e `HttpOnly` nas ferramentas do navegador.
- O SSE passa pelo Caddy sem travar: `curl -sN --compressed https://dominio.com/api/webchat/<loja>/sessoes/<sessao>/stream`
  mostra `: heartbeat` a cada 15 s (abrir sessão de chat não cria lead; só a primeira mensagem).
- De fora, só 22, 80 e 443 respondem (5432, 6379, 8080, 8000 e 3000 fechadas).

## 7. Pendências de operação

- **Backup** do Postgres (snapshots da hospedagem ou `pg_dump` diário para fora da VPS).
- Atualizar uma versão: refaça os passos 4 e 5 (o `alembic upgrade head` aplica migrations novas) e
  `systemctl restart atendimento-api atendimento-worker atendimento-painel`.
