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
    "registrar_leitura_imagem",
    "calcular_proposta",
    "liberar_desconto",
    "fechar_acordo",
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


def test_todos_os_objetos_no_formato_strict() -> None:
    for d in CatalogoFerramentas().definicoes():
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
    assert por_nome["fechar_acordo"] == {}


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
    assert props["registrar_leitura_imagem"] == {
        "tipo",
        "bateria_pct",
        "tela_danificada",
        "traseira_danificada",
        "carcaca_marcada",
        "modelo_provavel",
        "confianca",
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


# Limites da API para esquemas strict, somados em todas as ferramentas strict da requisicao
# (docs "Structured outputs" > "Schema complexity limits"). Acima deles toda chamada da 400.
_MAX_FERRAMENTAS_STRICT = 20
_MAX_OPCIONAIS = 24
_MAX_COM_UNIAO = 16


def _propriedades(esquema: Any) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    """(objeto, nome, propriedade) de todos os objetos aninhados do esquema."""
    return [
        (obj, nome, prop)
        for obj in _objetos(esquema)
        for nome, prop in obj.get("properties", {}).items()
    ]


def _tem_uniao(prop: dict[str, Any]) -> bool:
    return "anyOf" in prop or isinstance(prop.get("type"), list)


def test_ferramentas_strict_dentro_dos_limites_da_api() -> None:
    estritas = [d for d in CatalogoFerramentas().definicoes() if d.estrita]
    props = [p for d in estritas for p in _propriedades(d.esquema_json)]
    opcionais = [nome for obj, nome, _ in props if nome not in obj.get("required", [])]
    com_uniao = [nome for _, nome, prop in props if _tem_uniao(prop)]
    assert len(estritas) <= _MAX_FERRAMENTAS_STRICT
    assert len(opcionais) <= _MAX_OPCIONAIS, opcionais
    assert len(com_uniao) <= _MAX_COM_UNIAO, com_uniao


def test_strict_fica_onde_o_tipo_errado_quebra_a_ficha() -> None:
    estrita = {d.nome: d.estrita for d in CatalogoFerramentas().definicoes()}
    assert estrita["registrar_usado"] and estrita["registrar_compra"]
    # So texto, ja validado no handler: sem strict para caber no limite de unioes.
    assert not estrita["registrar_interesse"] and not estrita["consultar_estoque"]
    # Campos anulaveis lidos de imagem, validados no handler: tambem fora do strict.
    assert not estrita["registrar_leitura_imagem"]
