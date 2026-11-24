"""Seminovo sem bateria cadastrada e bateria minima pedida: a conversa nunca trava (#92)."""

from __future__ import annotations

from typing import Any

from app.adapters.outbound.llm.fake import RespostaRoteirizada
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.ferramentas import ResultadoFerramenta
from app.domain.estoque import Condicao

from .apoio_ferramentas import Ambiente, criar_ambiente, item
from .apoio_processar import chamada, criar_cenario, resultados_json, texto

VAZIO = EstadoAtendimento()
SEM_BATERIA = "IP12-128-PRETO"

# iPhone 15 128GB Preto: um novo e quatro seminovos (bateria 85, 92, 96 e sem dado).
ITENS_15 = [
    item("N15", "iPhone 15", 128, "Preto", 4199),
    item("S15-85", "iPhone 15", 128, "Preto", 3500, condicao=Condicao.SEMINOVO, bateria=85),
    item("S15-92", "iPhone 15", 128, "Preto", 3600, condicao=Condicao.SEMINOVO, bateria=92),
    item("S15-96", "iPhone 15", 128, "Preto", 3700, condicao=Condicao.SEMINOVO, bateria=96),
    item("S15-XX", "iPhone 15", 128, "Preto", 3400, condicao=Condicao.SEMINOVO),
]
ITENS_BAIXOS = [
    item("S14-A", "iPhone 14", 128, "Preto", 3000, condicao=Condicao.SEMINOVO, bateria=82),
    item("S14-B", "iPhone 14", 128, "Preto", 3100, condicao=Condicao.SEMINOVO, bateria=88),
    item("S14-X", "iPhone 14", 128, "Preto", 2900, condicao=Condicao.SEMINOVO),
]


def _consulta(modelo: str, minima: Any) -> dict[str, Any]:
    return {"modelo": modelo, "capacidade": "128GB", "cor": "Preto", "bateria_minima": minima}


async def _consultar(amb: Ambiente, entrada: dict[str, Any]) -> ResultadoFerramenta:
    return await amb.rodar("consultar_estoque", entrada, VAZIO)


async def test_seminovo_sem_bateria_sai_com_null_e_instrucao() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("confirmar_item", {"sku": SEM_BATERIA}, VAZIO)
    it = r.conteudo["item"]
    assert it["bateria_pct"] is None
    assert it["bateria_informada"] is False
    assert "não invente" in r.conteudo["instrucao_bateria"]
    assert "vendedor confirma" in r.conteudo["instrucao_bateria"]


async def test_consultar_item_unico_seminovo_sem_bateria_traz_instrucao() -> None:
    amb = await criar_ambiente()
    r = await _consultar(amb, {"modelo": "iPhone 12", "capacidade": "128GB", "cor": "Preto"})
    assert r.conteudo["sku_confirmado"] == SEM_BATERIA
    assert "instrucao_bateria" in r.conteudo


async def test_opcoes_com_seminovo_sem_bateria_marcam_o_dado_ausente() -> None:
    amb = await criar_ambiente(ITENS_15)
    r = await _consultar(amb, _consulta("iPhone 15", None))
    opcoes = {o["sku"]: o for o in r.conteudo["opcoes"]}
    assert opcoes["S15-XX"]["bateria_pct"] is None
    assert opcoes["S15-XX"]["bateria_informada"] is False
    assert opcoes["S15-85"]["bateria_pct"] == 85
    assert opcoes["S15-85"]["bateria_informada"] is True
    assert "bateria_pct" not in opcoes["N15"] and "bateria_informada" not in opcoes["N15"]
    assert "instrucao_bateria" in r.conteudo


async def test_seminovos_todos_com_bateria_nao_trazem_instrucao() -> None:
    amb = await criar_ambiente(ITENS_BAIXOS[:2])
    r = await _consultar(amb, _consulta("iPhone 14", None))
    assert "instrucao_bateria" not in r.conteudo


async def test_bateria_minima_filtra_pelos_conhecidos_e_avisa_dos_sem_dado() -> None:
    amb = await criar_ambiente(ITENS_15)
    r = await _consultar(amb, _consulta("iPhone 15", 90))
    skus = {o["sku"] for o in r.conteudo["opcoes"]}
    assert skus == {"N15", "S15-92", "S15-96"}  # novo fica; 85 e sem dado saem
    aviso = r.conteudo["aviso_bateria"]
    assert "1 seminovo sem bateria cadastrada" in aviso
    assert "vendedor confirma" in aviso


async def test_bateria_minima_sem_nenhum_que_atenda_devolve_o_melhor_e_avisa() -> None:
    amb = await criar_ambiente(ITENS_BAIXOS)
    r = await _consultar(amb, _consulta("iPhone 14", 95))
    assert [o["sku"] for o in r.conteudo["opcoes"]] == ["S14-B"]  # maior bateria conhecida
    aviso = r.conteudo["aviso_bateria"]
    assert "Não há seminovo com bateria" in aviso
    assert "88%" in aviso
    assert "alternativa" in aviso
    assert "1 seminovo sem bateria cadastrada" in aviso


async def test_bateria_minima_sem_nenhuma_bateria_cadastrada_nao_esvazia_a_resposta() -> None:
    amb = await criar_ambiente()
    entrada = {"modelo": "iPhone 12", "capacidade": "128GB", "cor": "Preto", "bateria_minima": 90}
    r = await _consultar(amb, entrada)
    assert r.conteudo["sku_confirmado"] == SEM_BATERIA
    assert "sem bateria cadastrada" in r.conteudo["aviso_bateria"]
    assert "instrucao_bateria" in r.conteudo


async def test_sem_bateria_minima_nao_ha_aviso_de_minima() -> None:
    amb = await criar_ambiente(ITENS_15)
    r = await _consultar(amb, _consulta("iPhone 15", None))
    assert "aviso_bateria" not in r.conteudo
    assert len(r.conteudo["opcoes"]) == 5


async def test_bateria_minima_aceita_inteiro_em_texto_e_recusa_fora_de_0_a_100() -> None:
    amb = await criar_ambiente(ITENS_15)
    ok = await _consultar(amb, _consulta("iPhone 15", "90"))
    assert "S15-85" not in {o["sku"] for o in ok.conteudo["opcoes"]}
    for ruim in (-1, 101):
        r = await _consultar(amb, _consulta("iPhone 15", ruim))
        assert r.erro is True
        assert "0 e 100" in r.conteudo["erro"]


async def test_resposta_nunca_traz_percentual_inventado() -> None:
    amb = await criar_ambiente(ITENS_BAIXOS)
    r = await _consultar(amb, _consulta("iPhone 14", 99))
    for o in r.conteudo["opcoes"]:
        if o["sku"] == "S14-X":
            assert o["bateria_pct"] is None
    # a ficha nao fica bloqueada por bateria do item de estoque
    assert r.estado.ficha.usado.bateria_pct is None


async def test_conversa_segue_quando_a_bateria_do_seminovo_nao_esta_cadastrada() -> None:
    entrada = {"modelo": "iPhone 12", "capacidade": "128GB", "cor": "Preto"}
    c = await criar_cenario(
        [
            RespostaRoteirizada(
                chamadas=[
                    chamada("t1", "registrar_interesse", entrada),
                    chamada("t2", "consultar_estoque", entrada),
                ]
            ),
            texto(
                "Esse seminovo não tem a bateria cadastrada: o vendedor confirma a saúde da "
                "bateria na loja. Você tem aparelho para dar na troca?"
            ),
        ]
    )
    await c.turno("qual a bateria do iphone 12 128 preto seminovo?")
    resultados = [r for m in c.llm.chamadas[-1].mensagens for r in resultados_json(m)]
    consulta = next(r for r in resultados if "sku_confirmado" in r)
    assert "instrucao_bateria" in consulta
    assert len(c.canal.textos) == 1
    assert "troca" in c.canal.textos[0]
    assert "%" not in c.canal.textos[0]
