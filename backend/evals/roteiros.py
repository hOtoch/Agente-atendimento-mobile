"""Agente roteirizado do modo fake: respostas do FakeLLM, na ordem das chamadas.

As ferramentas, o estoque e a loja demo sao os REAIS; so o LLM e de mentira. Os textos com
valores sao montados a partir do resultado real da ferramenta (como um agente bem comportado),
exceto no controle negativo, que viola uma regra de proposito.
"""

from __future__ import annotations

import json
from itertools import count
from typing import Any

from app.adapters.outbound.llm.fake import RespostaRoteirizada, Roteiro
from app.application.llm import (
    ChamadaFerramenta,
    MensagemLLM,
    ResultadoFerramenta,
    UsoTokens,
)

MODELO_FAKE = "fake"
_USO = UsoTokens(MODELO_FAKE, entrada=800, saida=60, cache_leitura=1_500, cache_escrita=0)
_ids = count(1)
FRASE = "É uma pré-avaliação, valor final confirmado na loja com o aparelho em mãos."


def fala(texto: str) -> RespostaRoteirizada:
    return RespostaRoteirizada(texto=texto, uso=_USO, modelo=MODELO_FAKE)


def chama(nome: str, **entrada: Any) -> RespostaRoteirizada:
    chamada = ChamadaFerramenta(f"toolu_fake_{next(_ids)}", nome, entrada)
    return RespostaRoteirizada(chamadas=[chamada], uso=_USO, modelo=MODELO_FAKE)


def _resultados(mensagens: list[MensagemLLM]) -> list[dict[str, Any]]:
    achados: list[dict[str, Any]] = []
    for m in mensagens:
        for b in m.blocos:
            if isinstance(b, ResultadoFerramenta):
                dado = json.loads(b.conteudo)
                if isinstance(dado, dict):
                    achados.append(dado)
    return achados


def _ultima_proposta(mensagens: list[MensagemLLM]) -> dict[str, Any]:
    for dado in reversed(_resultados(mensagens)):
        if "forma_escolhida" in dado:
            return dict(dado)
        aninhada = dado.get("proposta")
        if isinstance(aninhada, dict):
            return dict(aninhada)
    raise AssertionError("roteiro fake: nenhuma proposta nos resultados de ferramenta")


def _forma(proposta: dict[str, Any]) -> str:
    forma = proposta["forma_escolhida"]
    if "valor_a_vista" in forma:
        return f"à vista no Pix por {forma['valor_a_vista']}"
    return f"em {forma['parcelas']}x de {forma['valor_parcela']}"


def apresenta_proposta(mensagens: list[MensagemLLM]) -> RespostaRoteirizada:
    p = _ultima_proposta(mensagens)
    ap = p["aparelho"]
    troca = p["troca"]
    partes = [f"{ap['modelo']} {ap['capacidade']}: {p['preco_aparelho']}."]
    if troca["status"] == "avaliada":
        partes.append(f"Seu aparelho entra na troca por {troca['valor']}.")
    partes.append(f"Fica {_forma(p)}.")
    partes.append(FRASE)
    partes.append("Posso te ajudar com mais alguma coisa?")
    return fala(" ".join(partes))


def repassa_acordo(mensagens: list[MensagemLLM]) -> RespostaRoteirizada:
    """Como um agente bem comportado: repassa o endereco, o horario e o Pix que a ferramenta deu."""
    acordo = next(d for d in reversed(_resultados(mensagens)) if d.get("acordo_fechado"))
    partes = [f"Fechado! Te esperamos em {acordo['endereco']}, horário: {acordo['horarios']}."]
    if "pix" in acordo:
        pix = acordo["pix"]
        partes.append(f"Chave Pix: {pix['chave']}, favorecido {pix['favorecido']}.")
    partes.append("Obrigado pela preferência! Um vendedor vai concluir com você na loja.")
    return fala(" ".join(partes))


def fecha_acordo() -> list[Roteiro]:
    """Cliente confirmou a ficha: confirmar_pedido, fechar_acordo, o vendedor com o acordo."""
    return [
        chama("confirmar_pedido"),
        chama("fechar_acordo"),
        chama("chamar_vendedor", motivo="acordo_fechado"),
        repassa_acordo,
    ]


def _pix_hoje() -> list[Roteiro]:
    return [
        chama("registrar_interesse", modelo="iPhone 15", capacidade="256GB", cor=None),
        chama("consultar_estoque", modelo="iPhone 15", capacidade="256GB", cor=None),
        fala("Tenho o iPhone 15 256GB Azul. Você vai dar um aparelho usado na troca?"),
        chama("registrar_usado", tem_troca=False),
        chama("registrar_compra", data_prevista="2026-11-20", tipo_pagamento="pix"),
        chama("calcular_proposta"),
        apresenta_proposta,
    ]


def _escada_de_desconto() -> list[Roteiro]:
    """Ficha, depois 3 pedidos de desconto: R$ 50, R$ 100 e, acima do teto, o vendedor."""
    pedido = {"pedido": "mais_desconto"}
    return [
        *_pix_hoje(),
        chama("liberar_desconto", motivo="cliente pediu desconto", **pedido),
        fala("Consegui um desconto para você, confere a ficha."),
        chama("liberar_desconto", motivo="cliente pediu mais desconto", **pedido),
        fala("Consegui mais um pouco, confere a ficha."),
        chama("liberar_desconto", motivo="cliente pediu desconto de novo", **pedido),
        fala("Vou chamar um vendedor para continuar a negociação com você."),
    ]


ROTEIROS_FAKE: dict[str, list[Roteiro]] = {
    "so_oi": [fala("Oi, tudo bem! Qual iPhone você está procurando?")],
    "pede_humano": [
        chama("chamar_vendedor", motivo="cliente pediu para falar com uma pessoa"),
        fala("Claro! Um vendedor da loja vai continuar o atendimento em instantes."),
    ],
    "preco_logo_de_cara": [
        chama("registrar_interesse", modelo="iPhone 16", capacidade="128GB", cor=None),
        chama("consultar_estoque", modelo="iPhone 16", capacidade="128GB", cor=None),
        chama("calcular_proposta"),
        fala("Temos o iPhone 16 128GB em Preto e Ultramarino. Qual cor você prefere?"),
    ],
    "seminovo_sem_bateria": [
        chama("registrar_interesse", modelo="iPhone 12", capacidade="128GB", cor="Preto"),
        chama("consultar_estoque", modelo="iPhone 12", capacidade="128GB", cor="Preto"),
        fala(
            "Tenho o iPhone 12 128GB Preto seminovo, mas a bateria dele não está cadastrada: "
            "o vendedor confirma a saúde da bateria na loja. Você tem um aparelho para dar "
            "na troca?"
        ),
    ],
    "sem_troca_pix": _pix_hoje(),
    "desconto_tres_vezes": _escada_de_desconto(),
    "desconto_escada": _escada_de_desconto(),
    "pede_brinde": [
        *_pix_hoje(),
        chama("liberar_desconto", pedido="brinde_ou_beneficio", motivo="quer uma capinha"),
        fala("Vou chamar um vendedor para ver esse brinde com você."),
    ],
    "pergunta_parcelas_nao_fecha": [
        chama("registrar_interesse", modelo="iPhone 15", capacidade="256GB", cor=None),
        chama("consultar_estoque", modelo="iPhone 15", capacidade="256GB", cor=None),
        chama("registrar_usado", tem_troca=False),
        chama(
            "registrar_compra",
            data_prevista="2026-11-20",
            tipo_pagamento="credito",
            bandeira="Mastercard",
        ),
        fala("Em quantas parcelas você quer pagar?"),
        chama("registrar_compra", parcelas=10),
        chama("calcular_proposta"),
        apresenta_proposta,
    ],
    "fecha_acordo_pix": [*_pix_hoje(), *fecha_acordo()],
    "exemplo_oficial": [
        chama("registrar_interesse", modelo="iPhone 17", capacidade="256GB", cor=None),
        chama("consultar_estoque", modelo="iPhone 17", capacidade="256GB", cor=None),
        chama("calcular_proposta"),
        fala("Tenho o iPhone 17 256GB Lavanda. Você vai dar um aparelho usado na troca?"),
        chama("registrar_usado", tem_troca=True, modelo="iPhone 16", capacidade="128GB"),
        fala("Ótimo! Como está a tela dele?"),
        chama(
            "registrar_usado",
            tem_troca=True,
            tela_danificada=True,
            traseira_danificada=False,
            carcaca_marcada=False,
            bateria_pct=79,
            camera_ok=True,
            outros_defeitos=[],
            peca_trocada=False,
        ),
        fala("Anotado! Quando você pretende fazer a compra?"),
        chama(
            "registrar_compra",
            data_prevista="2026-11-20",
            tipo_pagamento="credito",
            parcelas=12,
            bandeira="Mastercard",
        ),
        chama("calcular_proposta"),
        apresenta_proposta,
        *fecha_acordo(),
    ],
    "controle_preco_sem_ficha": [
        fala("O iPhone 16 128GB sai por R$ 4.830,00 à vista, uma ótima oferta!"),
    ],
    "controle_handoff_sem_acordo": [
        *_pix_hoje(),
        # pula a confirmacao da ficha: o codigo recusa o fechamento, e o agente chama o
        # vendedor mesmo assim, sem acordo
        chama("fechar_acordo"),
        chama("chamar_vendedor", motivo="cliente quer fechar"),
        fala("Perfeito! Um vendedor da loja vai continuar o atendimento em instantes."),
    ],
}
