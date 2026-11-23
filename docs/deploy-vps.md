# Deploy na VPS (1 vCPU, um domínio)

Guia curto para colocar a plataforma no ar numa VPS pequena. O desenho: **um domínio só**, com o
Caddy na frente servindo o painel em `/` e a API em `/api`. Assim o navegador fala com uma origem
única (sem CORS entre sites) e o cookie de sessão funciona com `Secure`.

```
navegador --HTTPS--> Caddy (443)
                      |-- /api/*  -> API (uvicorn, 127.0.0.1:8000)   (prefixo /api removido)
                      '-- /*      -> painel (next start, 127.0.0.1:3000)
```

## 1. Recursos

A pilha mede cerca de **1,5 a 2 GB de RAM**: Postgres + Redis ~130 MB, Evolution e seus bancos
~200 a 300 MB, API + 1 worker ~300 a 400 MB, painel (`next start`) ~150 a 250 MB, SO + Docker
~400 MB. Para uma VPS de 2 GB:

- **Crie 2 GB de swap** (`fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile &&
  swapon /swapfile`, e registre em `/etc/fstab`). É a folga para picos, não capacidade.
- **Não suba** `postgres-test` (só testes) e `erp-mock` (só dev/demo) do `infra/docker-compose.yml`:
  suba apenas `postgres`, `redis` e os serviços `evolution-*` (por nome, `docker compose -f
  infra/docker-compose.yml up -d postgres redis evolution-postgres evolution-redis evolution-api`).
- **Build do painel fora da VPS** (1 vCPU não aguenta o `next build` com folga): gere o build na sua
  máquina ou no CI e copie `frontend/.next` e `node_modules` (ou rode `npm ci --omit=dev` lá).
  Na VPS use sempre `next start` (`npm run start`), nunca `next dev`.

## 2. Variáveis do `.env` que mudam em produção

Troque `dominio.com` pelo seu domínio.

| Variável | Valor em produção | Por quê |
|---|---|---|
| `COOKIE_SECURE` | `true` | O cookie `sessao` só trafega por HTTPS |
| `CONFIAR_PROXY` | `true` | A API está atrás do Caddy: usa o **último** IP do `X-Forwarded-For` (o que o Caddy acrescentou) no limite de tentativas de login. Com `false`, todo mundo parece vir do IP do proxy |
| `CORS_ORIGINS` | `https://dominio.com` | Origem exata do painel; o CORS usa credenciais, não aceita `*` |
| `API_PUBLICA_URL` | `https://dominio.com/api` | Base das URLs de mídia (imagens/áudios) que a API devolve |
| `PAINEL_URL` | `https://dominio.com` | Base do link da conversa na mensagem ao vendedor |
| `NEXT_PUBLIC_API_URL` | `/api` | Lida **no build** do painel: o navegador chama `/api/...` na mesma origem |
| `SESSAO_TTL_HORAS` | `168` (padrão) | Validade da sessão, renovada a cada uso |
| `LOGIN_MAX_FALHAS_EMAIL`, `LOGIN_MAX_FALHAS_IP`, `LOGIN_JANELA_MIN` | `5`, `20`, `15` (padrão) | Limite de tentativas de login (429 com `Retry-After`) |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | senha forte | Não deixe `atendimento/atendimento` |
| `EVOLUTION_API_KEY`, `EVOLUTION_WEBHOOK_TOKEN`, `EVOLUTION_DB_PASSWORD` | valores novos e secretos | Os do `.env.example` são só de dev |
| `ANTHROPIC_API_KEY` (e `OPENAI_API_KEY` para áudio) | suas chaves | Só no `.env` do servidor |
| `SEED_SENHA_DEMO` | **vazio/ausente** | Em produção não rode o seed da loja demo nem crie o usuário demo |

`NEXT_PUBLIC_LOJA_ID` não existe mais: a loja vem da sessão (`/auth/eu`).

### Webhook da Evolution

A Evolution chama a API em `EVOLUTION_WEBHOOK_URL` (visto **de dentro do container**). No dev o
padrão é `http://host.docker.internal:8000/webhooks/evolution`. Na VPS, com a API rodando no
host, esse mesmo padrão funciona se o container resolver `host.docker.internal` (o compose já
declara `extra_hosts` para isso). Se a API também rodar em container na mesma rede do Docker, use o
nome do serviço da API; se preferir passar pelo domínio, aponte para
`https://dominio.com/api/webhooks/evolution`. Em qualquer caso mantenha o `EVOLUTION_WEBHOOK_TOKEN`
secreto: ele é o que autentica o webhook (que é público, fora do login).

## 3. Caddy

`/etc/caddy/Caddyfile`:

```caddy
dominio.com {
    # API em /api: o prefixo é removido antes de chegar ao uvicorn
    handle_path /api/* {
        # SSE do painel e do chat: sem buffer, a conexão fica aberta
        reverse_proxy 127.0.0.1:8000 {
            flush_interval -1
        }
    }

    # todo o resto é o painel
    handle {
        reverse_proxy 127.0.0.1:3000
    }
}
```

O Caddy emite e renova o certificado sozinho (o domínio precisa apontar para o IP da VPS e as
portas 80/443 estarem abertas). Ele já envia `X-Forwarded-For` para a API.

## 4. Subir

Na VPS, em `backend/`: `uv sync`, `uv run alembic upgrade head`, e então os processos (use
`systemd` ou o gerenciador que preferir; um serviço por linha):

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000          # API (sem --reload)
uv run arq app.infra.worker.WorkerSettings                         # worker do agente (1 basta)
cd ../frontend && npm run start -- -H 127.0.0.1 -p 3000            # painel (build já copiado)
```

Crie a primeira loja e o login do dono (a senha provisória aparece uma única vez):

```bash
cd backend && uv run python scripts/criar_loja.py --nome "Loja X" --email dono@loja.com
```

## 5. Conferir

- `https://dominio.com/api/health` responde `{"status":"ok",...}`.
- `https://dominio.com/login` abre; entrar com o e-mail e a senha provisória pede a troca de senha.
- O cookie `sessao` aparece com `Secure` e `HttpOnly` nas ferramentas do navegador.
- O kanban atualiza em tempo real (SSE passa pelo Caddy sem travar) e `https://dominio.com/chat/<id da loja>` abre sem login.
