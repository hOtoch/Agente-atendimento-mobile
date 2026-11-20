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
`LLM_FALLBACK_MODEL` (padrao `claude-haiku-5-5`), `ANTHROPIC_API_KEY` (opcional),
`TEST_DATABASE_URL` (Postgres de teste, padrao `...@localhost:5433/teste`).

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

## Banco e migrations (SQLAlchemy 2 async + Alembic)
Modelos em `app/adapters/outbound/db/models.py`, session/unidade de trabalho em `session.py`,
repositorios em `repositorios.py`. Migrations em `migrations/` (`alembic.ini` em `backend/`);
a URL vem de `DATABASE_URL`. Rodar dentro de `backend/`:

| O que | Comando |
|---|---|
| Aplicar tudo | `uv run alembic upgrade head` |
| Desfazer tudo | `uv run alembic downgrade base` |
| Voltar uma | `uv run alembic downgrade -1` |
| Nova migration (autogenerate) | `uv run alembic revision --autogenerate -m "descricao"` |
| Revisao atual | `uv run alembic current` |

Revise sempre a migration gerada. Idempotencia de mensagens: unique `(canal, id_externo)` e
`MensagemRepositorio.inserir_se_nova` (`ON CONFLICT DO NOTHING`, devolve `False` se ja existia).

Testes de integracao criam um banco `teste_<id>` isolado em `TEST_DATABASE_URL`, aplicam as
migrations e dropam no final; se o Postgres de teste estiver fora, sao PULADOS com mensagem.

Marcador `integration`: testes que precisam de Postgres/Redis (`@pytest.mark.integration`).

## Dados de demonstração
O seed cria (ou atualiza) a **"Loja Demo Celulares"** com ID fixo (`LOJA_DEMO_ID`,
`00000000-0000-4000-8000-00000000de30`), com tudo fictício, para a demo ao vivo:

```
uv run alembic upgrade head
uv run python -m app.infra.seed                      # usa DATABASE_URL
uv run python -m app.infra.seed --database-url postgresql+asyncpg://user:senha@host:5432/banco
```

Conteúdo: perfil (tom amigável e direto, seg–sáb), 3 vendedores (pesos 50/30/20), regras de preço
(até 18x, repassa taxa, preço à vista = Pix, teto R$ 100 em degraus de R$ 50, oportunidade única
de R$ 100 por fora do teto, entrada + cartão), taxas das 5 bandeiras de 1x a 18x e débito
(Mastercard do exemplo oficial; Visa "igual"), tabela de troca de iPhone 11 a 17 Pro Max e
estoque local com ~28 itens (novos e seminovos, alguns com quantidade 0).

Perfil, preço, taxas, troca e estoque são gravados pelos casos de uso (mesma validação do painel).
É idempotente: rodar de novo atualiza os valores sem duplicar, e o checklist de onboarding da loja
fica 100% completo. Os dados ficam em `app/infra/seed_data/`, separados da lógica (`app/infra/seed.py`).

## Verificando o contrato de camadas
Um import proibido deve quebrar o `lint-imports`:
```
echo "from app.adapters import inbound" > app/domain/tmp_violacao.py
uv run lint-imports   # FALHA: app.domain is not allowed to import app.adapters
rm app/domain/tmp_violacao.py
uv run lint-imports   # volta a passar
```

## Atendimento ponta a ponta (API + worker + infra)
O orquestrador (`ProcessarConversa`) roda no **worker**: a API só grava a mensagem e agenda; depois
de ~4 s sem mensagem nova (debounce) o worker monta o turno, chama o LLM + ferramentas e publica a
resposta no tópico do webchat (Redis pub/sub -> SSE).

```
# 1. infra (Postgres 5432, Redis 6379): ver CLAUDE.md §5 (bash infra/dev.sh up, dentro do WSL)
cd backend
uv run alembic upgrade head
uv run python -m app.infra.seed                      # loja demo (LOJA_DEMO_ID)
# 2. API e worker, em dois terminais (ANTHROPIC_API_KEY no .env; sem chave o cliente recebe a
#    mensagem de espera e o lead vai para "Com o vendedor")
uv run uvicorn app.main:app
uv run arq app.infra.worker.WorkerSettings
```

Conversar pelo webchat com `curl` (loja demo `00000000-0000-4000-8000-00000000de30`):

```
LOJA=00000000-0000-4000-8000-00000000de30
SESSAO=$(curl -s -X POST localhost:8000/webchat/$LOJA/sessoes | python -c "import sys,json;print(json.load(sys.stdin)['sessao'])")
curl -N localhost:8000/webchat/$LOJA/sessoes/$SESSAO/stream &          # respostas (SSE)
curl -X POST localhost:8000/webchat/$LOJA/sessoes/$SESSAO/mensagens \
  -H 'content-type: application/json' \
  -d '{"id_cliente":"m1","tipo":"texto","texto":"oi, quero um iphone 16 128"}'   # 202
```

Conversar pelo terminal, sem Postgres/Redis (loja demo em memória, ferramentas reais):

```
uv run python scripts/conversar.py --fake   # LLM eco, sem custo, testa o fio
uv run python scripts/conversar.py          # LLM REAL: precisa de ANTHROPIC_API_KEY (pago)
```

Transcrição do LLM: cada mensagem trocada com o modelo (user, assistant com `bruto`, tool_result e
a mensagem de estado do turno) é gravada só por acréscimo em `eventos` (`tipo="llm_mensagem"`,
payload com `conversa_id` e `seq`; detalhes em `app/adapters/outbound/db/transcricao.py`). Consulta:

```sql
SELECT payload FROM eventos
WHERE lead_id = :lead AND tipo = 'llm_mensagem' AND payload->>'conversa_id' = :conversa
ORDER BY (payload->>'seq')::int;
```
Outros eventos do turno: `ferramenta`, `ferramenta_erro`, `etapa_mudou`, `handoff`, `limite_iteracoes`
e `llm_uso` (tokens).
