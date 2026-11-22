# Integração com o Mercado Phone (ERP)

O Mercado Phone é o ERP usado pelas lojas de celular. Esta integração faz três coisas:

1. **Lê o estoque e os preços** do ERP e mantém o estoque da loja no agente igual ao do balcão.
2. **Lê os vendedores** do ERP para o cadastro da loja.
3. **Escreve no ERP só no handoff** (cliente e orçamento), e só se a loja ligar essa opção.

O ERP é acessado por um servidor MCP (JSON-RPC sobre HTTP). Tudo abaixo vale para a loja demo e para
uma loja real; os números citados vieram de uma medição só de leitura no ERP da loja do hackathon.

## Por que o backend fala com o MCP e a IA não

O servidor MCP do Mercado Phone expõe 81 ferramentas, inclusive de exclusão. Entregar isso ao modelo
quebraria a regra do projeto ("o código decide, o LLM conversa"): preço, estoque e escrita no ERP são
decisões de negócio, não de conversa.

- O agente só enxerga a porta `EstoquePort` (`buscar`, `obter`) e as ferramentas de atendimento. Ele
  nunca recebe as ferramentas do MCP nem a chave.
- Quem fala com o MCP é o adaptador em `backend/app/adapters/outbound/mercadophone/`. Uma **allowlist**
  de 8 ferramentas passa (`list_my_stores`, `list_inventory`, `list_brands`, `list_salespeople`,
  `list_payment_methods`, `list_customers`, `create_customer`, `create_estimate`); qualquer outra,
  `delete_*` inclusive, é recusada antes de tocar a rede.
- A chave vai na query `key` da URL. O cliente a **mascara** em `repr`, logs (inclusive os do `httpx`)
  e mensagens de erro. O painel nunca pede nem mostra a chave.
- `429 rate_limited` é tratado com espera e repetição; falha persistente vira erro tipado e o
  estoque anterior é mantido.

## Como conectar, passo a passo

1. **Chave no `.env`** (raiz do repositório, nunca commitado):

   ```
   MERCADOPHONE_MCP_URL=https://platform.mercadophone.tech/mcp/platform/
   MERCADOPHONE_API_KEY=<a chave da loja>
   ```

   Sem `MERCADOPHONE_API_KEY` a integração fica desligada (o painel mostra "Integração com o ERP não
   configurada no servidor"). Reinicie a API e o worker depois de mudar o `.env`.
2. **Confira a chave pelo terminal** (só leitura, ver [Comandos](#comandos)):
   `cd backend && uv run python scripts/mercadophone_smoke.py`. Ele lista as unidades da chave.
3. **Unidade**: no painel, `/configuracoes`, seção **Conexão com o ERP**, campo **Unidade do ERP**
   (o `system_unit_id`). Uma chave pode cobrir várias unidades.
4. **Filtro da loja** (opcional): quando duas lojas nossas dividem a mesma unidade do ERP, o filtro
   separa o estoque pelo campo `obs` do item, usando o texto **antes de ` | `**. Exemplo: com o filtro
   `Loja A`, entram `Loja A` e `Loja A | vitrine`; `Loja B` fica de fora. Itens de outra loja não
   contam como descarte, aparecem à parte no relatório ("outra loja").
5. **Testar conexão**: confere se a unidade existe na chave. Não grava nada.
6. **Sincronizar agora**: lê o inventário inteiro e substitui o estoque da loja (ver
   [Sincronização](#sincronização)). O relatório mostra itens lidos, importados, de outra loja e
   descartados por motivo, e a duração.
7. **Ativar a sincronização automática**: com a conexão **ativa**, o worker sincroniza sozinho a cada
   `intervalo_min` minutos (padrão 15, de 5 a 1440).
8. **Importar vendedores** (opcional): botão **Importar do ERP** no passo de vendedores do onboarding.
9. **Exportar handoff para o ERP** (opcional, **desligado por padrão**): ver
   [O que é escrito no ERP](#o-que-é-escrito-no-erp-e-quando).

Rotas da API usadas pelo painel: `GET/PUT /lojas/{id}/config/erp`, `POST .../config/erp/testar`,
`POST .../config/erp/sincronizar` e `POST /lojas/{id}/vendedores/importar-erp` (botão **Importar do ERP**; exige a conexão da loja salva,
porque usa a unidade dela):

- vendedor ativo no ERP é identificado pelo código do ERP (o id dele): se não existe, é criado; se já
  existe, só o **nome** é atualizado;
- vendedor novo entra com **peso 0** e sem telefone: fica fora da distribuição de leads até alguém
  definir o telefone (WhatsApp) e a porcentagem no onboarding, e o checklist avisa. A importação nunca
  mexe em telefone nem em peso;
- vendedor que veio do ERP e sumiu dele (ou veio inativo) fica **inativo**, nunca é apagado;
- vendedor cadastrado à mão (sem código do ERP) **nunca é tocado**;
- **resposta vazia do ERP não desativa ninguém**: a importação falha com aviso e nada muda.

O código do ERP do vendedor é o que o handoff usa para criar o orçamento em nome dele.

## Limites conhecidos e premissas a validar

- **A escrita ainda não foi validada no ERP real.** A leitura foi conferida no servidor da loja; o
  handoff foi testado só contra um servidor falso. Premissas que precisam ser conferidas antes de ligar
  `exportar_handoff` numa loja de verdade:
  - o id criado volta em `id`, em `data.id` ou em `item.id` (o código lê os três; se o ERP responder de
    outro jeito, o orçamento é criado mas o id não é guardado, e o evento avisa);
  - o desconto do item é em **reais** (não em porcentagem);
  - o valor do pagamento em crédito é o **total pago** (com juros), não o valor à vista.

  Como validar: ligar a exportação numa loja de teste, fazer um handoff e conferir o orçamento no
  Mercado Phone (cliente, vendedor, itens, pagamentos). Desligar a opção volta ao estado anterior.
- A sincronização é por consulta (a cada `intervalo_min`, no mínimo 5 min); não há webhook do ERP.
  Entre duas rodadas só a confirmação ao vivo protege contra venda de aparelho que já saiu.
- A leitura completa leva de 16 a 21 s numa unidade de 2,6 mil itens; unidades muito maiores levam
  proporcionalmente mais (as páginas são de 300).
- Só celulares entram. Acessórios, áudio, TV e peças do ERP são descartados (`nao_e_celular`).
- O filtro da loja depende de o ERP preencher o campo `obs` com o nome da loja antes de ` | `.
- Uma chave por servidor (`MERCADOPHONE_API_KEY`); todas as lojas usam a mesma chave e diferem pela
  unidade.

## Comandos

Tudo em `backend/` (o `.env` da raiz é lido automaticamente).

| O quê | Comando |
|---|---|
| Smoke (só leitura): unidades, leitura e resumo de descartes | `uv run python scripts/mercadophone_smoke.py` |
| Smoke com unidade e filtros | `uv run python scripts/mercadophone_smoke.py --unidade <id> --filtro-loja "Loja A" --filtro-loja "Loja B"` |
| Smoke conferindo 3 itens ao vivo | `uv run python scripts/mercadophone_smoke.py --filtro-loja "Loja A" --conferir 3` |
| Testes da integração (sem rede, com servidor falso) | `uv run pytest -k mercadophone` |

O smoke **nunca escreve no ERP**: usa só ferramentas `list_*` (um teste garante isso) e não grava nada no
banco. Sem a chave, avisa e sai com código 2; ele não imprime a chave. Com falha do ERP, sai com 1.
Os testes usam um servidor MCP falso em memória com dados sintéticos e nunca a rede.
