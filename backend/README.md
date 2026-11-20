# Backend — Agente de Atendimento Mobile

Python 3.12, FastAPI, Pydantic v2, uv. Arquitetura em camadas (ports & adapters), ver `context.md` §4.1.

```
app/domain        regras puras, sem IO, nao importa nada do projeto
app/application   casos de uso e portas (Protocol); importa so domain
app/adapters      inbound (FastAPI, webhooks) e outbound (db, llm, canal, estoque)
app/infra         settings, container de dependencias, workers
```

## Configuracao
`app/infra/settings.py` le variaveis de ambiente e o `.env` da **raiz do repo** (procura `../.env` e `.env`).
Variaveis: `DATABASE_URL`, `REDIS_URL`, `LLM_MODEL` (padrao `claude-sonnet-5-5`),
`LLM_FALLBACK_MODEL` (padrao `claude-haiku-5-5`), `ANTHROPIC_API_KEY` (opcional).

## Comandos (rodar dentro de `backend/`)
| O que | Comando |
|---|---|
| Instalar deps | `uv sync` |
| Subir a API | `uv run uvicorn app.main:app --reload` (GET `/health`) |
| Testes rapidos | `uv run pytest -m "not integration"` |
| Todos os testes | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Formatacao | `uv run ruff format --check .` (corrigir: `uv run ruff format .`) |
| Tipos (estrito) | `uv run mypy app` |
| Camadas | `uv run lint-imports` |

Marcador `integration`: testes que precisam de Postgres/Redis (`@pytest.mark.integration`).

## Verificando o contrato de camadas
Um import proibido deve quebrar o `lint-imports`:
```
echo "from app.adapters import inbound" > app/domain/tmp_violacao.py
uv run lint-imports   # FALHA: app.domain is not allowed to import app.adapters
rm app/domain/tmp_violacao.py
uv run lint-imports   # volta a passar
```
