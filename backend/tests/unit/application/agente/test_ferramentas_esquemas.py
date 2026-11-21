"""Esquemas das ferramentas: validos como strict e com os nomes combinados com a #23."""

from __future__ import annotations

from typing import Any

from app.application.agente.ferramentas import CatalogoFerramentas

NOMES = {
    "registrar_interesse",
    "consultar_estoque",
    "confirmar_item",
    "registrar_usado",
    "registrar_compra",
    "calcular_proposta",
    "liberar_desconto",
    "chamar_vendedor",
}


def _objetos(esquema: Any) -> list[dict[str, Any]]:
    achados: list[dict[str, Any]] = []
    if isinstance(esquema, dict):
        if esquema.get("type") == "object" or "properties" in esquema:
            achados.append(esquema)
        for v in esquema.values():
            achados += _objetos(v)
    elif isinstance(esquema, list):
        for v in esquema:
            achados += _objetos(v)
    return achados


def _aceita_null(prop: dict[str, Any]) -> bool:
    if "anyOf" in prop:
        return any(_aceita_null(alt) for alt in prop["anyOf"])
    tipo = prop["type"]
    return tipo == "null" or (isinstance(tipo, list) and "null" in tipo)


def _com_enum(esquema: Any) -> list[dict[str, Any]]:
    achados: list[dict[str, Any]] = []
    if isinstance(esquema, dict):
        if "enum" in esquema:
            achados.append(esquema)
        for v in esquema.values():
            achados += _com_enum(v)
    elif isinstance(esquema, list):
        for v in esquema:
            achados += _com_enum(v)
    return achados


def test_nomes_exatos() -> None:
    assert {d.nome for d in CatalogoFerramentas().definicoes()} == NOMES
    assert len(CatalogoFerramentas().definicoes()) == len(NOMES)


def test_todos_os_objetos_sao_strict() -> None:
    for d in CatalogoFerramentas().definicoes():
        assert d.estrita
        assert d.descricao.strip()
        objetos = _objetos(d.esquema_json)
        assert objetos, d.nome
        assert d.esquema_json["type"] == "object"
        for obj in objetos:
            assert obj.get("additionalProperties") is False, d.nome
            assert set(obj.get("required", [])) == set(obj.get("properties", {})), d.nome


def test_opcionais_aceitam_null() -> None:
    por_nome = {d.nome: d.esquema_json["properties"] for d in CatalogoFerramentas().definicoes()}
    for campo in ("capacidade", "cor"):
        assert "null" in por_nome["registrar_interesse"][campo]["type"]
        assert "null" in por_nome["consultar_estoque"][campo]["type"]
    usado = por_nome["registrar_usado"]
    assert usado["tem_troca"]["type"] == "boolean"
    for campo, prop in usado.items():
        if campo != "tem_troca":
            assert "null" in prop["type"], campo
    for campo, prop in por_nome["registrar_compra"].items():
        assert _aceita_null(prop), campo
    assert por_nome["calcular_proposta"] == {}


def test_assinaturas_combinadas() -> None:
    props = {d.nome: set(d.esquema_json["properties"]) for d in CatalogoFerramentas().definicoes()}
    assert props["registrar_interesse"] == {"modelo", "capacidade", "cor"}
    assert props["consultar_estoque"] == {"modelo", "capacidade", "cor"}
    assert props["confirmar_item"] == {"sku"}
    assert props["registrar_usado"] == {
        "tem_troca",
        "modelo",
        "capacidade",
        "tela_danificada",
        "traseira_danificada",
        "carcaca_marcada",
        "bateria_pct",
        "camera_ok",
        "outros_defeitos",
        "peca_trocada",
    }
    assert props["registrar_compra"] == {
        "data_prevista",
        "tipo_pagamento",
        "parcelas",
        "bandeira",
        "entrada",
    }
    assert props["liberar_desconto"] == {"motivo"}
    assert props["chamar_vendedor"] == {"motivo"}


def test_enum_so_com_tipo_unico() -> None:
    """A API recusa `enum` com `type` em lista (["string", "null"]): enum anulavel vai em anyOf.

    Com o esquema recusado toda chamada ao LLM da 400 e a conversa cai no handoff por falha_llm.
    """
    for d in CatalogoFerramentas().definicoes():
        for esquema in _com_enum(d.esquema_json):
            assert isinstance(esquema.get("type"), str), d.nome
            assert None not in esquema["enum"], d.nome


def test_tipo_pagamento_aceita_os_tipos_e_null() -> None:
    from app.domain.ficha import TipoPagamento

    props = {d.nome: d.esquema_json["properties"] for d in CatalogoFerramentas().definicoes()}
    tipo = props["registrar_compra"]["tipo_pagamento"]
    (com_enum,) = _com_enum(tipo)
    assert set(com_enum["enum"]) == {t.value for t in TipoPagamento}
    assert _aceita_null(tipo)
