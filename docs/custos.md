# Custos

Gerado por `backend/scripts/custos.py` a partir dos relatórios do eval de 2026-11-21. Valores em US$. O custo de LLM é **medido** (usage registrado); áudio e infraestrutura são **estimativas** com premissas explícitas. Preços por modelo (US$ por milhão de tokens) em `backend/evals/precos.py`.

## Custo medido por conversa (agente)

| Modelo | Relatório | Cenários | Aprovados | Média | p50 | Máximo |
|---|---|---|---|---|---|---|
| `claude-haiku-5-5` | `2026-11-21-real-claude-haiku-5-5.json` | 15 | 14/15 | US$ 0,004009 | US$ 0,004005 | US$ 0,008821 |
| `claude-sonnet-5-5` | `2026-11-21-real-claude-sonnet-5-5.json` | 3 | 1/3 | US$ 0,078774 | US$ 0,063425 | US$ 0,117206 |

Só o agente: o cliente simulado do eval (Haiku, ~US$ 0,0004 por conversa) não existe em
produção. Tokens médios do agente por conversa:

| Modelo | Entrada (sem cache) | Saída | Cache lido | Cache escrito |
|---|---|---|---|---|
| `claude-haiku-5-5` | 2.726 | 2.635 | 144.943 | 7.755 |
| `claude-sonnet-5-5` | 3.703 | 2.631 | 180.834 | 10.791 |

## Efeito do cache de prompt

O prefixo da chamada (ferramentas, system e a conversa até ali) se repete a cada chamada ao
LLM; por isso quase toda a entrada é lida do cache (5% do preço da entrada no Sonnet, 10% no
Haiku). Custo medido contra o mesmo usage cobrado como entrada comum:

| Modelo | Com cache (medido) | Se não houvesse cache | Economia |
|---|---|---|---|
| `claude-haiku-5-5` | US$ 0,004009 | US$ 0,016860 | 76% |
| `claude-sonnet-5-5` | US$ 0,078774 | US$ 0,416963 | 81% |

Antes e depois do cache incremental da conversa (commit `5a1145c`), Sonnet 5.5: cerca de
US$ 0,177000 por conversa antes (~70 mil tokens de entrada sem cache) e US$ 0,078774
depois, ~55% menos. O valor de antes é a medição histórica do
eval daquele dia; o relatório correspondente não está versionado.

## Projeção mensal (1 lead = 1 conversa)

LLM = custo medido por conversa x leads. Áudio e infra são estimativas (ver Premissas);
o total é uma faixa por causa da infra.

| Volume | Modelo | LLM | Áudio (STT+TTS) | Infra | Total | Por lead |
|---|---|---|---|---|---|---|
| 1 mil leads/mês | Haiku 5.5 | US$ 4,01 | US$ 5,04 | US$ 20,00 a US$ 50,00 | **US$ 29,05 a US$ 59,05** | US$ 0,029 a US$ 0,059 |
| 1 mil leads/mês | Sonnet 5.5 | US$ 78,77 | US$ 5,04 | US$ 20,00 a US$ 50,00 | **US$ 103,81 a US$ 133,81** | US$ 0,104 a US$ 0,134 |
| 10 mil leads/mês | Haiku 5.5 | US$ 40,09 | US$ 50,40 | US$ 40,00 a US$ 100,00 | **US$ 130,49 a US$ 190,49** | US$ 0,013 a US$ 0,019 |
| 10 mil leads/mês | Sonnet 5.5 | US$ 787,74 | US$ 50,40 | US$ 40,00 a US$ 100,00 | **US$ 878,14 a US$ 938,14** | US$ 0,088 a US$ 0,094 |

## Leitura e recomendação

- **Haiku 5.5 como modelo principal.** Passou 14 de 15 cenários do eval a US$ 0,004009 por conversa, cerca de 1/20 do custo do Sonnet 5.5. Reprovações: `mente_tela_perfeita` (checagem `tamanho_maximo`). As travas de negócio (valor só de ferramenta, desconto no teto) passaram em todos os cenários.
- **Sonnet 5.5 como reserva ou opção de qualidade.** O eval real dele cobriu só 3 cenários (1/3 aprovados; as duas reprovações, `preco_logo_de_cara` e `prompt_injection`, foram só da checagem `handoff`: o cliente simulado aceitou a proposta e o agente chamou o vendedor, o que é o certo; essa expectativa saiu do eval no commit `fe84d15`, depois desta rodada): amostra pequena demais para dizer que é melhor ou pior. Para comparar de igual para igual, rodar os mesmos 15 cenários custaria cerca de US$ 1,18 (eval real é pago: só com autorização).
- **Com Haiku, o áudio pesa mais que o LLM.** Nas premissas abaixo o STT+TTS custa US$ 0,005040 por conversa, contra US$ 0,004009 do modelo; desligar o TTS (opcional por loja) é a principal alavanca de custo.

## Premissas (estimativas, a validar com a operação real)

- **Áudio:** 30% das conversas têm áudio; nelas, 0,6 min de áudio do cliente (STT) e 1 min de resposta falada (TTS).
- **Preço do áudio** (referência, conferir em <https://openai.com/api/pricing>): STT US$ 0,003/min (`gpt-4o-mini-transcribe`), TTS US$ 0,015/min (`gpt-4o-mini-tts`); média de US$ 0,005040 por conversa. O TTS é opcional por loja.
- **Infra com 1 mil leads/mês:** US$ 20,00 a US$ 50,00 por mês (VPS, disco e backup; `context.md` §6: 2 vCPU/4 GB atendem até ~10 mil leads/mês).
- **Infra com 10 mil leads/mês:** US$ 40,00 a US$ 100,00 por mês (VPS, disco e backup; `context.md` §6: 2 vCPU/4 GB atendem até ~10 mil leads/mês).
- **Black Friday:** 4 vCPU/8 GB, Postgres gerenciado e 2+ workers custam mais e não estão nessas faixas.
- **Fora da conta:** WhatsApp (a Evolution self-hosted não cobra por mensagem; o custo da API oficial da Meta, por mensagem entregue, e o plano para sair da Evolution estão em [whatsapp-oficial.md](whatsapp-oficial.md)), domínio, monitoramento e mão de obra.
- **Amostra:** a média vem do eval (conversas roteirizadas); conversas reais mais curtas ou mais longas mudam o custo na mesma proporção. Use `--banco` para recalcular com conversas reais.

## Como regenerar

```bash
cd backend
uv run python scripts/custos.py \
  --relatorios evals/relatorios/2026-11-21-real-claude-haiku-5-5.json \
  --relatorios evals/relatorios/2026-11-21-real-claude-sonnet-5-5.json \
  --saida ../docs/custos.md
```

Para números novos, rode o eval real (pago, só com autorização) e aponte o script para o relatório gerado; ou use `--banco` para somar os eventos `llm_uso` das conversas reais (a seção "Conversas reais" entra no documento).
