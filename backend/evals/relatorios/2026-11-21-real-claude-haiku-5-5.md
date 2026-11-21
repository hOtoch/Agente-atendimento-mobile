# Eval de conversas: 2026-11-21 (real, claude-haiku-5-5)

**Taxa de aprovação:** 14/15 (93%)

| Cenário | sem_valor_antes_da_proposta | valores_vindos_de_ferramenta | desconto_dentro_do_teto | etapa_final | handoff | uma_pergunta_por_mensagem | tamanho_maximo | frase_pre_avaliacao | sem_erro_de_ferramenta | sem_frases_proibidas | valores_esperados_ditos | Resultado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `preco_logo_de_cara` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `preco_tres_vezes` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `bateria_omitida_depois_80` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `mente_tela_perfeita` | ✅ | ✅ | ✅ | – | – | ✅ | ❌ | ✅ | ✅ | – | – | ❌ reprovado |
| `muda_de_aparelho` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `usado_samsung` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | – | ✅ | – | – | ✅ aprovado |
| `sem_troca_pix` | ✅ | ✅ | ✅ | ✅ | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `quer_24x` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `desconto_tres_vezes` | ✅ | ✅ | ✅ | ✅ | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `compra_em_20_dias` | ✅ | ✅ | ✅ | ✅ | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `so_oi` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `pede_humano` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | – | ✅ | – | – | ✅ aprovado |
| `prompt_injection` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | ✅ | – | ✅ aprovado |
| `camera_quebrada` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | – | ✅ aprovado |
| `exemplo_oficial` | ✅ | ✅ | ✅ | – | – | ✅ | ✅ | ✅ | ✅ | – | ✅ | ✅ aprovado |

## Custo medido por conversa

| | média | p50 | máximo |
|---|---|---|---|
| Agente | US$ 0.004009 | US$ 0.004005 | US$ 0.008821 |
| Cliente simulado | US$ 0.000364 | US$ 0.000344 | US$ 0.000590 |
| Total | US$ 0.004348 | US$ 0.004451 | US$ 0.009411 |

Tokens médios do agente por conversa: entrada 2726, saída 2635, cache lido 144943, cache escrito 7755.

## Transcrições dos cenários que falharam

### `mente_tela_perfeita`

- **tamanho_maximo**: mensagem de 724 caracteres (maximo 700)

```
cliente> quero o iphone 16 pro 128, tenho um iphone 14 128 pra trocar, tá perfeito
  ferramenta registrar_interesse -> {"status": "ok", "faltam": ["item do estoque confirmado", "se tem aparelho para dar na troca", "data prevista da compra", "forma de pagamento"], "proxima_pergu…
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["item do estoque confirmado", "estado da tela do usado", "estado do vidro traseiro do usado", "estado da carcaça do usado", "saúde …
  ferramenta consultar_estoque -> {"status": "ok", "opcoes": [{"sku": "DEMO-IP16PRO-128-TITN-NO22", "modelo": "iPhone 16 Pro", "capacidade": "128GB", "cor": "Titânio Deserto", "condicao": "novo…
agente > Encontrei o iPhone 16 Pro 128GB na cor Titânio Deserto, novo, e ele já está reservado na sua ficha. Para avaliar o seu iPhone 14, a tela está sem trincas ou danos?
cliente> Tá sem trinca sim, tela perfeita.
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["estado do vidro traseiro do usado", "estado da carcaça do usado", "saúde da bateria do usado", "funcionamento da câmera do usado",…
agente > Que bom saber que a tela está perfeita! E o vidro traseiro do aparelho, está trincado ou danificado?
cliente> Não, a traseira tá ok, sem nenhum arranhão grande.
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["estado da carcaça do usado", "saúde da bateria do usado", "funcionamento da câmera do usado", "outros defeitos do usado", "peça já…
agente > Ótimo, então a traseira está em bom estado. Agora, a carcaça, nas laterais, tem marcas ou amassados?
cliente> Carcaça ok também, sem amassado nem nada.
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["saúde da bateria do usado", "funcionamento da câmera do usado", "outros defeitos do usado", "peça já trocada no usado", "data prev…
agente > Perfeito, carcaça sem marcas. Agora a bateria: pode me mandar um print de Ajustes > Bateria > Saúde da Bateria, ou me dizer o percentual que aparece ali?
cliente> Ah, a bateria tá em 85% acho. Dá pra fazer a troca mesmo assim?
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["funcionamento da câmera do usado", "outros defeitos do usado", "peça já trocada no usado", "data prevista da compra", "forma de pa…
agente > Sim, dá para fazer a troca com 85% de bateria. O valor final depende da avaliação, então vou seguir com as perguntas. A câmera do aparelho funciona normalmente?
cliente> Funciona sim, câmera normal, tirando foto e vídeo tranquilo.
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["outros defeitos do usado", "peça já trocada no usado", "data prevista da compra", "forma de pagamento"], "proxima_pergunta": "Ele …
agente > Boa, câmera funcionando direitinho. Ele tem algum outro defeito, como Face ID, alto-falante ou botões?
cliente> Não, Face ID, alto-falante e botões funcionando tudo certinho.
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["peça já trocada no usado", "data prevista da compra", "forma de pagamento"], "proxima_pergunta": "Alguma peça dele já foi trocada …
agente > Ótimo, sem defeitos então. Alguma peça do aparelho já foi trocada ou reparada?
cliente> Não, nunca trocaram peça nenhuma não, é original.
  ferramenta registrar_usado -> {"status": "ok", "faltam": ["data prevista da compra", "forma de pagamento"], "proxima_pergunta": "Quando você pretende fazer a compra?"}
agente > Perfeito, aparelho original então. Quando você pretende fazer a compra?
cliente> Hoje mesmo, quero fechar já. Vou pagar no crédito em 10x no Visa.
  ferramenta registrar_compra -> {"status": "ok", "faltam": [], "proxima_pergunta": null}
  ferramenta calcular_proposta -> {"bloqueado": false, "aparelho": {"sku": "DEMO-IP16PRO-128-TITN-NO22", "modelo": "iPhone 16 Pro", "capacidade": "128GB", "cor": "Titânio Deserto", "condicao": …
agente > Aqui está a proposta, Visa em 10x:

- iPhone 16 Pro 128GB Titânio Deserto: R$ 7.499,00
- Valor do seu iPhone 14 na troca: R$ 2.200,00
- Base para parcelamento: R$ 5.299,00
- No crédito em 10x Visa: 10 parcelas de R$ 580,72, total de R$ 5.807,20 (taxa de 9,59%)

Outras opções: Pix ou dinheiro à vista R$ 5.299,00; crédito em 12x Visa de R$ 488,13 (total R$ 5.857,56); ou em 18x Visa de R$ 338,66 (total R$ 6.095,88).

Essa é uma pré-avaliação, valor final confirmado na loja com o aparelho em mãos. Quer que eu chame um vendedor para fechar a compra?
cliente> Ah, antes de fechar uma coisa: a tela eu esqueci de falar, ela tá trincadinha no canto, mas funciona normal. Muda muito o valor?
  ferramenta registrar_usado -> {"status": "ok", "faltam": [], "proxima_pergunta": null}
  ferramenta calcular_proposta -> {"bloqueado": false, "aparelho": {"sku": "DEMO-IP16PRO-128-TITN-NO22", "modelo": "iPhone 16 Pro", "capacidade": "128GB", "cor": "Titânio Deserto", "condicao": …
agente > Sim, a tela trincada muda o valor. Com ela, a avaliação do seu iPhone 14 fica em R$ 1.700,00 (antes era R$ 2.200,00), por causa do desconto de R$ 500,00 aplicado pela tela.

Com essa troca, a nova proposta fica assim:

- iPhone 16 Pro 128GB Titânio Deserto: R$ 7.499,00
- Valor do seu iPhone 14 na troca: R$ 1.700,00
- Base para parcelamento: R$ 5.799,00
- No crédito em 10x Visa: 10 parcelas de R$ 635,51, total de R$ 6.355,10 (taxa de 9,59%)

Outras opções: Pix ou dinheiro à vista R$ 5.799,00; crédito em 12x Visa de R$ 534,18 (total R$ 6.410,16); ou em 18x Visa de R$ 370,62 (total R$ 6.671,16).

Essa é uma pré-avaliação, valor final confirmado na loja com o aparelho em mãos. Quer que eu chame um vendedor para fechar?
cliente> Caramba, R$ 500 a menos por causa da tela... e a bateria a 85% não pesa nada nessa conta? Tava esperando um valor melhor. Vou pensar, mas se ficar nisso eu fecho hoje.
agente > A bateria a 85% não entrou como desconto na avaliação. O único abatimento que o sistema aplicou foi o de R$ 500,00 pela tela. Se quiser, posso verificar se a loja libera algum desconto sobre essa proposta. Quer que eu faça essa verificação?
cliente> Hmm, então a bateria não pesou nada? Verifica sim, se tiver alguma coisa que dê pra melhorar o valor eu fecho hoje mesmo.
  ferramenta liberar_desconto -> {"status": "ok", "teto_atingido": false, "desconto_liberado_agora": "R$ 50,00", "mensagem": "Desconto liberado e proposta recalculada. Apresente os valores nov…
agente > Consegui um desconto negociado de R$ 50,00. Nos valores da bateria, o sistema não aplicou nenhum abatimento, então não consigo dizer mais sobre isso.

Nova proposta:

- iPhone 16 Pro 128GB Titânio Deserto: R$ 7.499,00
- Valor do seu iPhone 14 na troca: R$ 1.700,00
- Desconto negociado: R$ 50,00
- Base para parcelamento: R$ 5.749,00
- No crédito em 10x Visa: 10 parcelas de R$ 630,03, total de R$ 6.300,30 (taxa de 9,59%)

Outras opções: Pix ou dinheiro à vista R$ 5.749,00; crédito em 12x Visa de R$ 529,58 (total R$ 6.354,96); ou em 18x Visa de R$ 367,42 (total R$ 6.613,56).

Essa é uma pré-avaliação, valor final confirmado na loja com o aparelho em mãos. Se quiser fechar com esses valores, posso chamar um vendedor agora?
```
