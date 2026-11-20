# Infra local

Tudo roda local (Windows + WSL). O Docker vive **dentro do WSL (Ubuntu)**; no Git Bash/PowerShell não existe `docker`.

## Serviços (projeto compose `atendimento`)

| Serviço | Porta no Windows | Observação |
|---|---|---|
| postgres (16) | 5432 | dev, volume nomeado `pgdata` |
| postgres-test (16) | 5433 | banco `teste`, `tmpfs` (some ao parar) |
| redis (7) | 6379 | volume `redisdata` |
| evolution-api (v2.3.7) | 8080 | imagem oficial `evoapicloud/evolution-api` (o repo `atendai/*` foi descontinuado); usa `evolution-postgres` e `evolution-redis` próprios, sem porta publicada |

Backend, worker, frontend e erp-mock estão como placeholders comentados no compose.

## Subir

```bash
# daemon parado? (uma vez por boot)
wsl -u root service docker start

cp .env.example .env   # opcional: todos os valores têm default de dev
wsl -e sh -c "cd '/mnt/d/Otoch IA Solutions/PS Power' && bash infra/dev.sh up"
```

Ajuste o caminho `/mnt/<letra>/...` conforme onde o repo está (D:\x\y vira /mnt/d/x/y).

## Comandos (`infra/dev.sh`)

`up` (sobe e espera healthchecks) | `down` | `logs [serviço]` | `ps` | `reset` (derruba apagando volumes e sobe de novo)

## Verificar

```bash
wsl -e sh -c "cd '<repo>' && bash infra/smoke.sh"        # healthchecks + portas + GET / da Evolution
python -c "import socket; socket.create_connection(('localhost',5433),2)"   # a partir do Windows
```

`smoke.sh` sai com código diferente de 0 se algo falhar.

## Evolution API

`GET http://localhost:8080/` responde 200. Header `apikey: <EVOLUTION_API_KEY>` nas demais rotas. Troque a chave no `.env`.
