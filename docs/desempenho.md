# Dados de demonstração do painel de desempenho

O banco de desenvolvimento tem poucas conversas. Para apresentar a tela de desempenho da IA
(`/lojas/{id}/metricas`) existe um script que cria um histórico **inventado e realista**, sem
chamar LLM, STT, TTS nem ERP. Nomes, telefones, modelos e valores são fictícios.

## Comandos

```bash
cd backend
# popular a loja demo (30 dias até hoje; use --dias 60 para o painel mostrar também a comparação
# com o período anterior)
uv run python scripts/popular_metricas_demo.py --loja 00000000-0000-4000-8000-00000000de30 --dias 30
# mesmos dados sempre, trocando a semente
uv run python scripts/popular_metricas_demo.py --loja <uuid> --dias 30 --seed 7
# apagar só o que o script criou
uv run python scripts/popular_metricas_demo.py --loja <uuid> --remover
```

O script imprime um resumo (leads, conversas, mensagens e eventos por tipo, criados ou removidos).

## O que é gerado

Por dia: um volume com variação diária e de horário (picos no fim da manhã e à noite; domingo
fraco) de leads/conversas distribuídos no funil do kanban; mensagens do cliente, da IA e do
vendedor com horário; eventos `llm_uso` (tokens, cache e as três latências, plausíveis para o
modelo configurado em `LLM_MODEL`), `ferramenta` (alguns com `erro: true`), poucos `erro_llm`,
`limite_iteracoes` e `resposta_descartada`; handoffs por motivo (pedido do cliente, acordo
fechado, falha técnica e outros) com `etapa_mudou`, `dono_mudou` e `handoff_resumo` (o acordo
só existe nos handoffs de acordo fechado). Nada fica no futuro.

## Como é marcado e removido

Sem mudar o schema:

- todo lead criado tem o telefone `demo:NNNNNN` (prefixo que nunca é um telefone real);
- todo evento criado tem `payload.demo = true`;
- conversas e mensagens nascem presas a esses leads (o `CASCADE` do banco as leva junto).

`--remover` apaga os eventos marcados e os leads `demo:`; leads, mensagens, eventos, vendedores e
configuração reais da loja ficam intactos. Rodar de novo (sem `--remover`) apaga o que o script
criou e recria, na mesma transação: não duplica e, com o mesmo `--seed`, gera os mesmos dados.

## Segurança

- `--loja` é obrigatório.
- Usa `DATABASE_URL` (`.env`) ou `--database-url`.
- Recusa qualquer banco com cara de teste (porta 5433 ou nome `teste*`). A flag
  `--permitir-banco-de-teste` existe só para a suíte de testes.
- Loja inexistente: recusa sem criar nada (exit 2).
