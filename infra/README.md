# Infra local

Tudo roda local com Docker Compose. Em Linux/macOS os comandos abaixo rodam direto; no Windows o Docker vive **dentro do WSL (Ubuntu)** (veja o fim deste arquivo).

## Serviços (projeto compose `atendimento`)

| Serviço | Porta local | Observação |
|---|---|---|
| postgres (16) | 5432 | dev, volume nomeado `pgdata` |
| postgres-test (16) | 5433 | banco `teste`, `tmpfs` (some ao parar) |
| redis (7) | 6379 | volume `redisdata` |
| evolution-api (v2.3.7) | 8080 | imagem oficial `evoapicloud/evolution-api` (o repo `atendai/*` foi descontinuado); usa `evolution-postgres` e `evolution-redis` próprios, sem porta publicada |

O ERP simulado (`erp-mock`, porta 8090, token em `ERP_MOCK_TOKEN`) sobe junto com a infra. Backend, worker e frontend ainda estão como placeholders comentados no compose.

## Subir

```bash
cp .env.example .env   # opcional: todos os valores têm default de dev
bash infra/dev.sh up
```

## Comandos (`infra/dev.sh`)

`up` (sobe e espera healthchecks) | `down` | `logs [serviço]` | `ps` | `reset` (derruba apagando volumes e sobe de novo)

## Verificar

```bash
bash infra/smoke.sh        # healthchecks + portas + GET / da Evolution
```

`smoke.sh` sai com código diferente de 0 se algo falhar.

## Evolution API

`GET http://localhost:8080/` responde 200. Header `apikey: <EVOLUTION_API_KEY>` nas demais rotas. Troque a chave no `.env`.

## Windows (WSL)

O Docker roda dentro do WSL; no Git Bash/PowerShell não existe `docker`. Ligue o daemon uma vez por boot com `wsl -u root service docker start` e rode os mesmos scripts por `wsl -e sh -c "cd '/mnt/<letra>/<caminho do repo>' && bash infra/dev.sh up"` (D:\x\y vira /mnt/d/x/y). As portas publicadas ficam acessíveis no Windows em `localhost`.
