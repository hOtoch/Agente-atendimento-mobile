# Black Friday: teste de carga e plano

Este documento reúne o resultado do teste de carga (k6) e o plano operacional para a Black Friday.
O plano resumido está em `context.md` §8; aqui ficam os números medidos e o que eles mostraram.
O teste está em `infra/k6/` (README com o passo a passo) e pode ser repetido a qualquer momento:

```bash
bash infra/k6/rodar_carga.sh                 # 10x o pico, 5 min, 1 worker
WORKERS=2 bash infra/k6/rodar_carga.sh       # 2 workers
```

## O que foi simulado

| Item | Valor |
|---|---|
| Entrada | `POST /webhooks/evolution` (`messages.upsert`), o mesmo caminho do WhatsApp real: normalização, idempotência por `id_externo`, gravação no Postgres, enfileiramento no arq |
| Volume | pico esperado de uma loja = ~40 msg/min (`context.md` §6); **10x = 400 msg/min**, por 5 min (2.000 mensagens). Também rodados: 1x (40/min) e 20x (800/min) |
| Leads | 250 remetentes distintos, em rajadas de 1 a 4 mensagens seguidas (exercita debounce de 4 s e trava por conversa) |
| Reentrega | a cada 20 mensagens, o mesmo id é enviado 2x simultaneamente (a Evolution reenvia sem esperar o 200): 5% de duplicatas |
| LLM | simulado, sem custo: texto fixo após 1,5 a 4 s (média 2,75 s) por chamada, 1 chamada por turno |
| Saída para o WhatsApp | Evolution falsa local (`stub_evolution.py`): aceita o envio e registra a hora de chegada |
| Isolamento | pilha própria: banco `carga_<run>` no Postgres de teste, DB 5 do Redis, API na porta 8100, workers arq próprios. Tudo é apagado no fim |

Máquina: **4 vCPU, 11 GiB de RAM** (Linux 6.8). API (uvicorn, 1 processo), workers, Postgres, Redis,
Docker do k6 e o amostrador rodaram **todos na mesma máquina**, portanto os números abaixo já
incluem a competição por CPU entre eles (um servidor dedicado só melhora).

## Resultados

Cada linha é uma execução completa. "Fila" é o Redis do arq. "Até a resposta" é o tempo desde a
última mensagem do cliente (mesmo número) até o texto chegar à Evolution falsa, o que inclui os 4 s
de debounce, a espera na fila e a chamada ao LLM.

| Cenário | Workers | Ingestão p50 / p95 / p99 (ms) | Fila máx. (total / prontos) | Jobs simultâneos | Throughput do worker (média / pico, respostas/min) | Fila esvazia | Até a resposta p50 / p95 / p99 (s) |
|---|---|---|---|---|---|---|---|
| 1x (40/min) | 1 | 21,4 / 34,0 / 39,2 | 5 / 3 | 2 | 19,5 / 21 | 6,3 s | 7,2 / 8,3 / 8,5 |
| **10x (400/min)** | **1** | 17,8 / 29,2 / 42,2 | **618 / 604** | 10 | 158 / 172 | **65 s** | **34,6 / 75,6 / 79,4** |
| **10x (400/min)** | **2** | 17,9 / 28,8 / 42,8 | **49 / 16** | 13 | 188 / 193 | **8 s** | **7,0 / 8,1 / 8,2** |
| 20x (800/min) | 2 | 18,4 / 29,5 / 36,6 | 755 / 697 | 20 | 317 / 336 | 41 s | 20,8 / 43,1 / 44,3 |

Ingestão máxima observada em qualquer cenário: 521 ms (picos isolados, sem tendência). Nenhuma requisição falhou (`http_req_failed` 0%).

### Contagem de mensagens (critério de aceite)

Em **todas** as execuções, a checagem pós-teste (`backend/scripts/checar_contagem.py`) comparou os
ids que o k6 enviou com `mensagens.id_externo` no banco:

| Cenário | Requisições | Ids únicos | Reentregas | No banco | Perdidas | Duplicadas | Conversas sem resposta |
|---|---|---|---|---|---|---|---|
| 1x | 127 | 121 | 6 | 121 | 0 | 0 | 0 |
| 10x, 1 worker | 2.101 | 2.001 | 100 | 2.001 | 0 | 0 | 0 |
| 10x, 2 workers | 2.100 | 2.000 | 100 | 2.000 | 0 | 0 | 0 |
| 20x, 2 workers | 2.521 | 2.401 | 120 | 2.401 | 0 | 0 | 0 |

Nenhuma mensagem perdida ou duplicada, inclusive as reentregas simultâneas do mesmo id (o
`UNIQUE (canal, id_externo)` mais o tratamento do caso de uso respondem `duplicada` sem gravar de
novo) e mesmo com a fila saturada. Todas as conversas terminaram com resposta da IA.

## Interpretação

1. **A ingestão não é o gargalo.** O webhook só valida, grava e enfileira: p99 de 43 ms a 10x e de
   37 ms a 20x, com uma única API (1 processo uvicorn). A latência de ingestão não muda com a
   saturação dos workers, então a Evolution nunca vai ver timeout nem reenviar por culpa da API.
2. **O gargalo é a concorrência dos workers.** Cada worker arq roda até 10 jobs ao mesmo tempo
   (padrão do arq). Cada turno ocupa um slot durante a chamada ao LLM (~2,75 s simulados, ~3,5 s
   por job no total). Isso dá um teto de **~170 respostas/min por worker** nesta máquina, medido (pico
   de 172/min). O debounce junta as rajadas: 2.000 mensagens viraram ~940 turnos (0,47 turno por
   mensagem), então a demanda a 10x é de ~188 turnos/min. Um worker (teto 172) fica abaixo da
   demanda e a fila cresce até 604 jobs prontos; dois workers (teto ~340) seguram com folga.
3. **Backlog não perde nada, só atrasa.** Com 1 worker a 10x, o cliente esperou até 80 s pela
   resposta, mas a fila esvaziou 65 s depois do fim da carga e nenhuma mensagem se perdeu. A trava
   por conversa e o debounce mantiveram a ordem e não houve resposta duplicada.
4. **Dois workers resolvem 10x e ainda aguentam ~20x com atraso moderado.** A 20x (demanda ~376
   turnos/min contra teto de ~336) houve backlog de 697 jobs, mas a fila esvaziou em 41 s e o p99
   até a resposta ficou em 44 s.
5. **Sem sinal de saturação do Postgres nem do Redis.** A fila (zset do Redis) chegou a 755 jobs
   e a ingestão (que grava no Postgres) manteve a mesma latência. Não medimos a CPU de cada
   processo; o que saturou primeiro foram os slots dos workers.

### Do teste para a produção (estimativa, não medida)

O teste usa 1 chamada de ~2,75 s por turno. Em produção `context.md` §6 estima ~6 s por chamada e
`context.md` §7 ~1,5 chamada por turno (ferramentas), ou seja ~9 s por turno. Com 10 slots por
worker isso cai para ~65 turnos/min por worker:

- 10x (~190 turnos/min) pede **~3 workers** (4 com folga). O pico simultâneo de chamadas ao
  LLM sobe para ~190 x 9 / 60 = **~28 chamadas simultâneas** por loja em 10x.
- 1x (~19 turnos/min) cabe em 1 worker com sobra.

## Gargalos reais fora do que o teste mede

- **Rate limit do LLM.** É o limite de verdade: ~28 chamadas simultâneas e ~285 chamadas/min por
  loja a 10x, cada uma com ~7k tokens de entrada (a maior parte em cache). Confirme o limite
  (requisições/min e tokens/min) do nível da conta Anthropic **antes** da data e peça aumento. O
  teste não consegue medir isso: o LLM foi simulado.
- **WhatsApp (Evolution/Baileys).** O risco é o bloqueio do número por volume e padrão de envio,
  não a capacidade da API. O teste usou uma Evolution falsa e não diz nada sobre isso.
- **CPU compartilhada.** Tudo rodou em 4 vCPU junto com o k6. Em produção, separar API, workers e
  Postgres.

## Plano Black Friday

Complementa `context.md` §8 com o que os números mostraram.

**Antes (uma a duas semanas)**
1. Subir o aumento do limite do LLM (requisições e tokens por minuto) e confirmar o limite efetivo.
2. Repetir `rodar_carga.sh` no ambiente de produção/staging (Postgres gerenciado, 4 vCPU, 8 GB),
   com `WORKERS=3` ou mais e o mesmo volume de 10x. Critério de aceite: fila esvazia em menos de 30 s
   após o fim do pico e p95 até a resposta < 20 s.
3. Definir o número de workers pela conta: `workers = ceil(turnos/min no pico x segundos por turno
   / 60 / 10)`. Para ~190 turnos/min a ~9 s por turno, 3 a 4 workers.
4. Rodar o eval em modo real (com OK e custo estimado) para medir segundos e chamadas reais por turno
   e refinar a conta acima.
5. Ensaiar a perda do LLM: com falha, o fluxo é retry com backoff, modelo reserva (Haiku) e, se
   persistir, mensagem "já te respondo" e aviso ao vendedor. O teste de carga não cobre isso.

**No dia**
1. Subir os workers extras antes do início da campanha (não depois do backlog).
2. Acompanhar três números: jobs prontos na fila (alerta se passar de ~100 por mais de 1 min),
   segundos até a resposta (p95) e taxa de erro/fallback do LLM. A fila é o primeiro sinal de falta
   de workers (foi o que o teste mostrou).
3. Estoque em cache curto e confirmação antes do preço; pesos de distribuição ajustáveis ao vivo.
4. Se o rate limit do LLM apertar: a fila segura o excesso (nada se perde), aceitando respostas
   mais lentas; avaliar trocar o modelo principal pelo reserva só para conversas simples.
5. Se o backlog crescer sem parar: escalar workers é seguro (a trava por conversa no Redis garante
   um worker por conversa), e o webhook continua aceitando.

**Depois**
1. Verificar a contagem: mensagens recebidas x respondidas por conversa (a mesma checagem do teste).
2. Medir custo por conversa real e ajustar `context.md` §7.

## Limites deste teste

- O LLM é simulado com 1 chamada por turno, sem ferramentas, estoque ou preço: mede fila, worker e
  banco, não o custo nem o tempo real do agente.
- A Evolution é falsa e responde na hora; a Evolution real pode ser mais lenta e tem limites próprios.
- A "latência até a resposta" é uma aproximação por número: da última mensagem do cliente até o
  envio à Evolution falsa (não inclui o tempo real do WhatsApp).
- Uma loja só (a demo). Várias lojas num mesmo worker dividem os mesmos slots.
- Um processo de API e todos os componentes na mesma máquina.
