# ERP simulado

API HTTP que imita um ERP real para provar que o sistema aguenta: autenticacao, paginacao, nomes de produto "sujos", latencia e falhas. O adaptador `ErpSimuladoAdapter` (backend) consome este contrato.

## Rodar

```bash
cd services/erp-mock
uv sync
uv run uvicorn app.main:app --port 8090      # local
uv run pytest && uv run ruff check . && uv run mypy app tests
```

No compose: `bash infra/dev.sh up` sobe o servico `erp-mock` na porta **8090** (`ERP_MOCK_URL=http://localhost:8090`).

## Configuracao (env)

| Variavel | Default | Efeito |
|---|---|---|
| `ERP_MOCK_TOKEN` | `token-dev` | Token esperado em `Authorization: Bearer <token>` |
| `ERP_MOCK_LATENCIA_MS` | `0` | Espera (ms) antes de responder em `/produtos*` |
| `ERP_MOCK_ERRO_PCT` | `0` | 0 a 100: probabilidade de responder `500` em `/produtos*` |
| `ERP_MOCK_SEED` | vazio | Seed do sorteio dos erros (execucao deterministica) |

Ordem em `/produtos*`: autenticacao (401) -> latencia -> sorteio de erro (500) -> resposta. `/health` ignora auth, latencia e erro.

## Contrato HTTP

Autenticacao: todos os endpoints, exceto `/health`, exigem `Authorization: Bearer <token>`. Ausente, esquema diferente de Bearer ou token errado: `401` com `WWW-Authenticate: Bearer` e corpo `{"detail": "token ausente ou invalido"}`.

### `GET /health`

Sem auth.

```
200 {"status": "ok"}
```

### `GET /produtos?pagina=1&tamanho=50`

| Parametro | Default | Regra |
|---|---|---|
| `pagina` | 1 | inteiro >= 1 |
| `tamanho` | 50 | inteiro de 1 a 100 |

Valores fora da regra retornam `422` (nao ha ajuste silencioso). Ordem estavel (a do arquivo). Pagina alem do fim retorna `200` com `itens: []`.

```
GET /produtos?pagina=2&tamanho=2
Authorization: Bearer token-dev

200
{
  "itens": [
    {
      "sku": "APL-000003",
      "descricao": "APPLE IPHONE 12 64GB AZUL SEMINOVO BAT 84",
      "preco": "2499.00",
      "estoque": 3,
      "atualizado_em": "2026-11-04T11:21:00-03:00"
    },
    {
      "sku": "APL-000004",
      "descricao": "IPH 12 128GB PRETO SN BAT 80",
      "preco": "2699.00",
      "estoque": 0,
      "atualizado_em": "2026-11-05T12:28:00-03:00"
    }
  ],
  "pagina": 2,
  "tamanho": 2,
  "total": 42,
  "total_paginas": 21
}
```

`total_paginas = ceil(total / tamanho)`. A ultima pagina pode vir parcial.

### `GET /produtos/{sku}`

```
GET /produtos/APL-000014        -> 200 {"sku": "APL-000014", "descricao": "IPH 15 PRO 256 TIT NAT", "preco": "7499.00", "estoque": 4, "atualizado_em": "..."}
GET /produtos/NAO-EXISTE        -> 404 {"detail": "produto nao encontrado"}
```

### Erros simulados

Com `ERP_MOCK_ERRO_PCT` > 0, `/produtos*` pode responder `500 {"detail": "erro interno simulado"}` (sempre com 100, nunca com 0). O cliente deve tratar com retry/timeout/fallback.

## Modelo do produto

| Campo | Tipo | Observacao |
|---|---|---|
| `sku` | string | `APL-000001`... unico |
| `descricao` | string | nome "sujo" estilo ERP (abaixo); nao ha campos de modelo/memoria/cor |
| `preco` | string | decimal com 2 casas, ponto como separador (nunca float) |
| `estoque` | int | pode ser 0 |
| `atualizado_em` | string | ISO 8601 com fuso |

## Nomes "sujos" (para o adaptador normalizar)

Dados em `app/dados/produtos.json` (42 itens: iPhone 11 ao 17 Pro Max, novos e seminovos, 3 itens que nao sao celular).

- **Prefixo**: `IPHONE`, `IPH`, `IP`, `APPLE IPHONE`.
- **Variante abreviada**: `PM` = Pro Max (`IP 14 PM 512`, `IPH 15 PM`), `PRO MAX`, `PLUS`, `AIR`; `16E` sem espaco; `IPHONE AIR` sem o numero 17.
- **Memoria**: numero solto (`128`, `256`, `512`) ou com sufixo (`128GB`, `256GB`, `1TB`).
- **Cor**: abreviada (`TIT NAT`, `TIT AZUL`, `TIT DESERTO`, `AZUL PROF`), por extenso, com ou sem acento (`LARANJA CÓSMICO` / `LARANJA COSMICO`), cor oficial da Apple (`ESTELAR`, `MEIA-NOITE`, `ULTRAMARINO`, `LAVANDA`).
- **Condicao**: `SEMINOVO`, `SN`, `NOVO`, `LACRADO`; ausencia de marcador indica novo.
- **Bateria** (seminovos): `BAT 87` (percentual de saude).
- **Nao celular** (devem ser ignorados): `CAPA SILICONE P/ IPHONE 15 PRO ...`, `CARREGADOR TURBO 20W ...`, `CABO USB-C ...`. Atencao: a capa cita "IPHONE" no meio do texto.
- Caixa alta, sem padrao fixo de ordem e sem separadores consistentes.
