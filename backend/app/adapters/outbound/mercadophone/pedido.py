"""Pedido do handoff no Mercado Phone: cliente (`list_customers`/`create_customer`) e orcamento
(`create_estimate`) sobre o cliente MCP.

O adaptador so TRADUZ: acha ou cria o cliente, mapeia as formas de pagamento pelo nome no
cadastro da unidade e envia os valores exatamente como chegaram (preco, troca, parcela e
desconto vem da proposta calculada pelo dominio; nada e recalculado aqui).

Formato do ERP (conferido no `tools/list`; as RESPOSTAS de escrita nao foram testadas no servidor
real, por isso o id criado e lido de forma tolerante: `id` no topo ou dentro de `data`/`item`):
- `list_customers(telefone, system_unit_id, page, limit)` -> `{"total", "items": [{"id", "nome",
  "telefone", ...}]}`; o telefone no ERP pode estar formatado ("(11) 91234-5678").
- `create_customer(nome, telefone?, system_unit_id)`.
- `create_estimate(clienteId, vendedorId, itens [{produtoId, quantidade, valorUnitario,
  desconto}], pagamentos [{formaPagamentoId, valor, parcelas}], previsaoOrcamento? (aaaa-mm-dd),
  observacao?, id? para editar, system_unit_id)`.
- `list_payment_methods(system_unit_id)` -> `{"items": [{"id", "name", "snAtivo", ...}]}`.

Cada falha do ERP vira `FalhaPedidoErp` (com o cliente que ja chegou a existir, se houver).
Valores monetarios vao como numero JSON com 2 casas: `float` so na borda do protocolo.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone, ErroMercadoPhone
from app.application.estoque import EstoqueIndisponivel
from app.application.pedido_erp import (
    DadosHandoff,
    DadosOrcamento,
    FalhaPedidoErp,
    FormaPedido,
    PagamentoPedido,
    RegistroErp,
)
from app.domain.conexao_erp import ConexaoErp

ARGUMENTO_UNIDADE = "system_unit_id"
DIGITOS_DA_BUSCA = 8
_LIMITE_BUSCA = 50
_DDI_BRASIL = "55"
_CENTAVOS = Decimal("0.01")


def normalizar_nome(nome: str) -> str:
    """Sem acento, em CAIXA ALTA e espacos simples ("Cartão de Crédito" -> "CARTAO DE CREDITO")."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.upper().split())


def _digitos(texto: Any) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _sem_ddi(digitos: str) -> str:
    return digitos[2:] if digitos.startswith(_DDI_BRASIL) and len(digitos) >= 12 else digitos


def mesmo_telefone(a: Any, b: Any) -> bool:
    """O fim dos numeros (sem DDI) e igual: um pode estar sem DDD, o outro com DDI e DDD."""
    x, y = _sem_ddi(_digitos(a)), _sem_ddi(_digitos(b))
    if min(len(x), len(y)) < DIGITOS_DA_BUSCA:
        return False
    return x.endswith(y) or y.endswith(x)


def _numero(valor: Decimal) -> float:
    return float(valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP))


def _id_criado(payload: dict[str, Any], ferramenta: str) -> int:
    for lugar in (payload, payload.get("data"), payload.get("item")):
        if not isinstance(lugar, dict):
            continue
        bruto = lugar.get("id")
        if isinstance(bruto, bool):
            continue
        if isinstance(bruto, int):
            return bruto
        if isinstance(bruto, str) and bruto.strip().isdigit():
            return int(bruto)
    raise ErroMercadoPhone(f"{ferramenta}: resposta sem o id do registro criado")


def _forma_casa(forma: FormaPedido, nome: str) -> bool:
    palavras = set(nome.split())
    match forma:
        case FormaPedido.PIX:
            return "PIX" in palavras
        case FormaPedido.DEBITO:
            return "DEBITO" in palavras
        case FormaPedido.CREDITO:
            return "CREDITO" in palavras or ("CARTAO" in palavras and "DEBITO" not in palavras)
        case FormaPedido.APARELHO:
            return "APARELHO" in palavras


def escolher_forma(formas: list[dict[str, Any]], forma: FormaPedido) -> int | None:
    """Id da forma ativa do ERP cujo nome casa; empate fica com o menor id."""
    ids = [
        f["id"]
        for f in formas
        if isinstance(f, dict)
        and f.get("snAtivo") == 1
        and isinstance(f.get("id"), int)
        and _forma_casa(forma, normalizar_nome(str(f.get("name", ""))))
    ]
    return min(ids) if ids else None


class PedidoMercadoPhone:
    """Implementa `PedidoPort` sobre o cliente MCP."""

    def __init__(self, cliente: ClienteMercadoPhone) -> None:
        self._cliente = cliente

    async def registrar_handoff(self, conexao: ConexaoErp, dados: DadosHandoff) -> RegistroErp:
        unidade = conexao.system_unit_id
        cliente_id = dados.cliente_id
        try:
            if cliente_id is None:
                cliente_id = await self._cliente_do_erp(unidade, dados)
            if dados.orcamento is None:
                return RegistroErp(cliente_id, None)
            avisos: list[str] = []
            orcamento_id = await self._orcamento(
                unidade, cliente_id, dados.orcamento, dados.orcamento_id, avisos
            )
        except EstoqueIndisponivel as exc:  # `ErroMercadoPhone` herda daqui
            raise FalhaPedidoErp(str(exc), cliente_id=cliente_id) from exc
        return RegistroErp(cliente_id, orcamento_id, tuple(avisos))

    # -- cliente --

    async def _cliente_do_erp(self, unidade: int, dados: DadosHandoff) -> int:
        if dados.telefone:
            existente = await self._buscar_por_telefone(unidade, dados.telefone)
            if existente is not None:
                return existente
        argumentos: dict[str, Any] = {"nome": dados.nome_cliente, ARGUMENTO_UNIDADE: unidade}
        if dados.telefone:
            argumentos["telefone"] = dados.telefone
        criado = await self._cliente.chamar("create_customer", argumentos)
        return _id_criado(criado, "create_customer")

    async def _buscar_por_telefone(self, unidade: int, telefone: str) -> int | None:
        resposta = await self._cliente.chamar(
            "list_customers",
            {
                "telefone": _digitos(telefone)[-DIGITOS_DA_BUSCA:],
                "page": 1,
                "limit": _LIMITE_BUSCA,
                ARGUMENTO_UNIDADE: unidade,
            },
        )
        itens = resposta.get("items")
        if not isinstance(itens, list):
            return None
        for item in itens:
            if (
                isinstance(item, dict)
                and isinstance(item.get("id"), int)
                and mesmo_telefone(telefone, item.get("telefone"))
            ):
                return int(item["id"])
        return None

    # -- orcamento --

    async def _orcamento(
        self,
        unidade: int,
        cliente_id: int,
        o: DadosOrcamento,
        orcamento_id: int | None,
        avisos: list[str],
    ) -> int:
        resposta = await self._cliente.chamar("list_payment_methods", {ARGUMENTO_UNIDADE: unidade})
        formas = resposta.get("items")
        pagamentos = self._pagamentos(
            formas if isinstance(formas, list) else [], o.pagamentos, avisos
        )
        argumentos: dict[str, Any] = {
            "clienteId": cliente_id,
            "vendedorId": o.vendedor_id_erp,
            "itens": [
                {
                    "produtoId": i.produto_id,
                    "quantidade": i.quantidade,
                    "valorUnitario": _numero(i.valor_unitario),
                    "desconto": _numero(i.desconto),
                }
                for i in o.itens
            ],
            "pagamentos": pagamentos,
            "observacao": o.observacao,
            ARGUMENTO_UNIDADE: unidade,
        }
        if o.previsao is not None:
            argumentos["previsaoOrcamento"] = o.previsao.isoformat()
        if orcamento_id is not None:
            argumentos["id"] = orcamento_id
        criado = await self._cliente.chamar("create_estimate", argumentos)
        return _id_criado(criado, "create_estimate")

    @staticmethod
    def _pagamentos(
        formas: list[dict[str, Any]], pagamentos: tuple[PagamentoPedido, ...], avisos: list[str]
    ) -> list[dict[str, Any]]:
        enviados: list[dict[str, Any]] = []
        for p in pagamentos:
            forma_id = escolher_forma(formas, p.forma)
            if forma_id is None:
                avisos.append(
                    f"forma de pagamento '{p.forma.value}' não encontrada no ERP: "
                    f"pagamento de {_numero(p.valor):.2f} ficou fora do orçamento"
                )
                continue
            enviados.append(
                {"formaPagamentoId": forma_id, "valor": _numero(p.valor), "parcelas": p.parcelas}
            )
        return enviados
