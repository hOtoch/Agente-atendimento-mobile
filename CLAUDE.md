# CLAUDE.md — Agente de Atendimento Mobile

Leia **`context.md`** antes de qualquer trabalho: é a fonte da verdade do plano, das regras de negócio, das decisões e do status.
Repositório: https://github.com/hOtoch/Agente-atendimento-mobile (privado). Backlog = GitHub Issues + Milestones.

---

## 1. Regras inegociáveis

1. **O código decide, o LLM conversa.** Preço, troca, parcelas, desconto, trava de qualificação e etapa do kanban são funções do domínio com testes. Nunca delegar cálculo ou decisão de negócio ao prompt.
2. **TDD sempre**: teste falhando (red) → implementação mínima (green) → refatoração (refactor). Nenhum código de produção sem teste que o exija.
3. **Clean Architecture / Ports & Adapters.** `domain` não importa nada do projeto nem faz IO; `application` importa só `domain` e define portas (`typing.Protocol`); `adapters` e `infra` implementam portas. O `import-linter` no CI quebra o build se a regra for violada.
4. **Design system no frontend.** Nada de cor, espaçamento ou fonte hardcoded: só tokens (CSS variables) e componentes de `frontend/src/components/ui` (base shadcn/ui). `DESIGN.md` é a fonte da verdade visual. Componente novo reutilizável vai para o design system, não para a feature.
5. **1 milestone = 1 branch. 1 issue = 1 commit.**
6. **Testes nunca chamam APIs pagas** (LLM, STT, TTS). Usar fakes (`FakeLLM` etc.). Eval/execução com LLM real só com OK explícito do usuário, informando custo estimado antes.
7. **Confidencialidade**: o material do benchmark, os formulários e a metodologia recebidos não entram no repositório nem em prompts. Telas e prompts são nossos.

---

## 2. Fluxo de trabalho por milestone (orquestração)

A sessão principal é o **agente orquestrador**. Para executar um milestone (ex.: "rode o M1"):

### 2.1 Preparar
1. `git checkout main && git pull`.
2. `git checkout -b milestone/<mN-slug>` (nome da branch está em `context.md` §9) e `git push -u origin <branch>`.
3. Listar as issues abertas do milestone: `gh issue list --milestone "<título>" --state open --json number,title,labels,body`.
4. Montar as **ondas** a partir do label `onda-N` e da linha `Depende de:` de cada issue. Uma onda = issues sem dependência pendente entre si.

### 2.2 Executar cada onda
- **Criar as worktrees à mão** (NÃO usar `isolation: "worktree"` do Agent: este repo está aninhado dentro de outro repo git em `D:\Otoch IA Solutions`, e a isolação automática cria a worktree no repo errado):
  `git worktree add .worktrees/issue-<N> -b issue/<N>-<slug> <SHA_BASE>` para cada issue da onda (`.worktrees/` está no `.gitignore`/`.git/info/exclude`).
- **Número de subagentes = número de issues da onda.** Um subagente por issue, todos lançados na **mesma mensagem** (em paralelo), com:
  - `model: "sonnet"` (Claude Sonnet 5.5)
  - sem `isolation` — o brief manda trabalhar só no caminho absoluto da worktree
  - `description`: `Issue #<N> — <título curto>`
  - `prompt`: o **brief do subagente** (§3) preenchido com o corpo da issue e o caminho da worktree.
- Docker: ligar o daemon antes da onda se alguma issue precisar (`wsl -u root service docker start`).
- Depois de integrar: `git worktree remove .worktrees/issue-<N>` e `git branch -D issue/<N>-<slug>`.
- Esperar todos terminarem. Cada um devolve: branch, SHA do commit único, arquivos alterados, saída dos testes (red e green).
- **Integrar** na branch do milestone, em ordem de número de issue: `git cherry-pick <sha>`. Resolver conflitos mantendo as duas intenções; se o conflito mudar comportamento, rodar os testes das duas issues.
- Depois de integrar a onda: rodar a bateria completa (§5). Se quebrar, corrigir antes da próxima onda (correção dobrada no commit da issue culpada via `git commit --amend` se for o último, ou um commit `fix(<escopo>): ... (#N)`).
- `git push`. A próxima onda parte do novo HEAD.

### 2.3 Fechar o milestone
1. Atualizar `context.md`: tabela de milestones (§9, status ✅), novas decisões (§10), questões (§11) e uma entrada em **Status** (§12) com o que foi feito, o que ficou de fora e riscos. Commit: `docs(context): fecha <mN>`.
2. Abrir o PR: `gh pr create --base main --head <branch> --title "<mN>: <título>" --body` listando as issues (`Closes #N` para cada) e como testar.
3. Lançar o **subagente revisor** (§4): `model: "sonnet"`, sem worktree (só leitura + testes), em contexto novo.
4. Veredito:
   - **APROVADO** → `gh pr merge <n> --rebase --delete-branch` (rebase preserva 1 commit por issue no `main`). `git checkout main && git pull`.
   - **REPROVADO** → corrigir os pontos (pode lançar subagentes para isso), push, e rodar o revisor de novo. Nunca fazer merge com testes vermelhos.
5. Relatar ao usuário: issues fechadas, link do PR, veredito, o que ficou pendente.

Observação: o GitHub não deixa aprovar o próprio PR (mesma conta). O revisor registra o veredito com `gh pr review <n> --comment --body "..."`; o merge depende desse veredito.

---

## 3. Brief do subagente de issue (modelo)

```
Você implementa UMA issue do projeto "Agente de Atendimento Mobile" em uma worktree isolada.
Leia CLAUDE.md e context.md antes de começar.

Issue #<N>: <título>
<corpo completo da issue>

Worktree: <CAMINHO_ABSOLUTO>/.worktrees/issue-<N> (já na branch issue/<N>-<slug>, criada pelo orquestrador).
Trabalhe SOMENTE nesse caminho: `cd "<caminho>" && ...` em todo comando, ou caminhos absolutos.

Processo obrigatório (TDD):
1. Escreva os testes dos critérios de aceite primeiro. Rode e confirme que FALHAM (guarde a saída resumida).
2. Implemente o mínimo para passar. Rode e confirme que PASSAM.
3. Refatore mantendo verde. Respeite as camadas (domain → application → adapters/infra) e o design system no frontend.
4. Rode lint, typecheck e a bateria do pacote afetado (CLAUDE.md §5). Tudo verde.
5. Faça EXATAMENTE UM commit: `<tipo>(<escopo>): <título> (#<N>)` + corpo curto + `Closes #<N>` + a linha Co-Authored-By.
   Não faça push. Não altere context.md nem CLAUDE.md. Não mexa em arquivos fora do escopo da issue.
6. Não chame APIs pagas (LLM/STT/TTS) — use fakes.

Responda no final com:
- branch e SHA do commit
- arquivos criados/alterados
- saída resumida dos testes (red e green) e do lint/typecheck
- decisões tomadas e qualquer ponto que o orquestrador precise saber (conflitos prováveis, dívidas)
```

## 4. Brief do subagente revisor (modelo)

```
Você é o revisor do PR #<n> (milestone <mN>) do projeto "Agente de Atendimento Mobile". Contexto novo: leia CLAUDE.md e context.md.
1. `git fetch && git checkout <branch>`.
2. Rode a bateria completa (CLAUDE.md §5): lint, typecheck, import-linter, testes backend (unit + integração + contrato), testes frontend, build do frontend.
3. Para cada issue do PR (`gh pr view <n> --json body`, `gh issue view <N>`), confira os critérios de aceite contra o código e os testes.
4. Verifique: 1 commit por issue, regra de camadas, design system (sem valores hardcoded), nenhum teste chamando API paga, nenhum material confidencial.
5. Publique o veredito: `gh pr review <n> --comment --body "<VEREDITO>"` com a primeira linha `VEREDITO: APROVADO` ou `VEREDITO: REPROVADO`, seguida da saída resumida dos testes e da lista de problemas (arquivo:linha, o que está errado, como reproduzir).
Não altere código. Responda com o veredito e o resumo.
```

---

## 5. Comandos

> Docker roda dentro do WSL. Se o daemon estiver parado: `wsl -u root service docker start`.
> Em Linux/macOS (fora do WSL): `bash infra/dev.sh up` direto, `uv` no PATH (`~/.local/bin`) e Node 24 (`nvm use 24`; o Node 20 quebra o vitest).
> Comandos Docker: `wsl -e sh -c "cd '/mnt/d/Otoch IA Solutions/PS Power' && docker compose -f infra/docker-compose.yml <cmd>"`.

| O quê | Comando |
|---|---|
| Subir infra local | `wsl -e sh -c "cd '/mnt/d/Otoch IA Solutions/PS Power' && bash infra/dev.sh up"` (também: `down`, `logs [servico]`, `ps`, `reset`) |
| Smoke da infra | `wsl -e sh -c "cd '/mnt/d/Otoch IA Solutions/PS Power' && bash infra/smoke.sh"` |
| Migrations | `cd backend && uv run alembic upgrade head` (`downgrade base`, `revision --autogenerate -m "..."`) |
| Subir API | `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --reload --reload-dir app --timeout-graceful-shutdown 3` (0.0.0.0 para a Evolution, no Docker, alcançar o webhook; `--reload-dir app` ignora edições em testes/docs e o timeout evita que o reload trave esperando os streams SSE do painel/webchat) |
| Subir worker (agente) | `cd backend && uv run arq app.infra.worker.WorkerSettings` |
| Conversar pelo terminal | `cd backend && uv run python scripts/conversar.py --fake` (grátis); sem `--fake` usa a LLM real (pago, exige `ANTHROPIC_API_KEY`) |
| Eval (fake, CI) | `cd backend && uv run python -m evals.rodar --modo fake` |
| Eval (real, pago) | `cd backend && uv run python -m evals.rodar --modo real --modelo claude-sonnet-5-5` mostra a estimativa; só roda com `--confirmo-custo` **e OK do usuário** |
| Custo por conversa | `cd backend && uv run python scripts/custos.py --relatorios evals/relatorios/2026-11-21-real-claude-*.json --saida ../docs/custos.md` (ou `--banco` para as conversas reais) |
| Teste de carga (k6, sem custo) | `bash infra/k6/rodar_carga.sh` (pilha isolada; `WORKERS=2`, `RATE_POR_MIN`, `DURACAO_S`; ver `infra/k6/README.md`) |
| Smoke do Mercado Phone (só leitura, chave no `.env`) | `cd backend && uv run python scripts/mercadophone_smoke.py [--unidade N] [--filtro-loja "Loja A"]... [--conferir N]` (sem chave: exit 2; ver `docs/mercadophone.md`) |
| Seed da loja demo | `cd backend && uv run python -m app.infra.seed` (idempotente; `LOJA_DEMO_ID` fixo) |
| Dados de demonstração do painel de desempenho | `cd backend && uv run python scripts/popular_metricas_demo.py --loja <uuid> --dias 30 [--seed N]` (`--remover` apaga só o que ele criou; recusa o banco de teste; ver `docs/desempenho.md`) |
| Regerar modelos xlsx | `cd backend && PYTHONPATH=. uv run python scripts/gerar_modelos_xlsx.py` |
| Componente do design system | `cd frontend && npx shadcn@latest add <componente>` |
| Subir painel | `cd frontend && npm run dev` (http://localhost:3000; API em `NEXT_PUBLIC_API_URL`) |
| Exportar OpenAPI + gerar cliente TS | `cd backend && uv run python scripts/exportar_openapi.py && cd ../frontend && npm run gerar:api` (o teste `test_openapi.py` quebra se ficar defasado) |
| Backend — deps | `cd backend && uv sync` |
| Backend — testes rápidos | `cd backend && uv run pytest -m "not integration"` |
| Backend — todos os testes | `cd backend && uv run pytest` (precisa do Postgres de teste) |
| Backend — lint/tipos/camadas | `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app evals && uv run lint-imports` |
| Frontend — deps | `cd frontend && npm ci` |
| Frontend — testes | `cd frontend && npm test -- --run` |
| Frontend — lint/tipos/build | `cd frontend && npm run lint && npm run typecheck && npm run build` |
| ERP simulado — testes | `cd services/erp-mock && uv run pytest` |

Manter esta tabela atualizada quando os scripts mudarem.

Portas locais: Postgres dev 5432 (`atendimento`/`atendimento`), Postgres de teste 5433 (`teste`/`teste`, tmpfs), Redis 6379, Evolution 8080, ERP simulado 8090 (token `token-dev`).
Conflitos esperados ao integrar issues paralelas: `pyproject.toml`/`uv.lock` quando duas issues adicionam dependências — juntar as linhas e rodar `uv lock`. Os testes de integração leem `TEST_DATABASE_URL` e são pulados se o banco de teste estiver fora.

---

## 6. Convenções

- **Idioma**: docs, issues, PRs e mensagens de commit em português. Termos do domínio em português no código, sem acentos (`ficha`, `avaliar_troca`, `parcela`); termos técnicos/framework em inglês quando idiomático (`router`, `repository`, `settings`).
- **Commits**: Conventional Commits — `feat`, `fix`, `test`, `refactor`, `docs`, `chore`, `ci`. Escopo = módulo (`dominio`, `estoque`, `agente`, `painel`, `canal`, `infra`). Terminar com `Closes #N` (quando for issue) e `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (ou a atribuição do modelo que fez o commit).
- **Branches**: `milestone/<mN-slug>` (orquestrador) e `issue/<N>-<slug>` (subagentes, locais, descartáveis).
- **Dinheiro**: sempre `Decimal` em centavos/2 casas, arredondamento `ROUND_HALF_UP`; nunca `float`.
- **Erros de domínio**: exceções/resultados tipados (ex.: `AvaliacaoNaLoja(motivo)`), nunca strings mágicas.
- **Config da loja** é lida a cada turno da conversa (mudança no painel vale na próxima mensagem).
- **Testes**: `tests/unit` (domínio/aplicação, sem IO), `tests/integration` (Postgres/Redis, marcados `@pytest.mark.integration`, banco isolado por execução), `tests/contract` (mesma suíte para todos os adaptadores de uma porta). Frontend: testes de componente com Testing Library, por comportamento.
- **LLM**: provedor por env (`LLM_PROVIDER=anthropic|openai`), modelo por env (`LLM_MODEL`, `LLM_FALLBACK_MODEL`). Anthropic pelo SDK oficial; OpenAI pela Chat Completions via `httpx` (sem SDK). Todo provedor novo é um adaptador do `LLMPort` com testes de HTTP simulado. Prompt caching no prefixo estável (tools + system). Sem prefill. Thinking/effort baixos para chat.
- **Segredos** só em `.env` (nunca commitado); `.env.example` sempre atualizado.

## 7. Ao final de cada milestone
Atualizar `context.md` (§2.3 passo 1). Se uma convenção nova surgir, registrar aqui no CLAUDE.md no mesmo commit.
