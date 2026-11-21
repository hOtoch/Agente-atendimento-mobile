"""Checagem pos-teste de carga: o que o k6 enviou x o que esta no banco."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CAMINHO = Path(__file__).resolve().parents[3] / "scripts" / "checar_contagem.py"


def _carregar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("checar_contagem", _CAMINHO)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


cc = _carregar()


def envio(id_wa: str, status: int = 200, resultado: str = "processada") -> object:
    return cc.Envio(id_wa=id_wa, status=status, resultado=resultado)


def ponto(id_wa: str, status: str = "200", resultado: str = "processada") -> str:
    return json.dumps(
        {
            "type": "Point",
            "metric": "msg_enviada",
            "data": {
                "time": "2026-11-21T10:00:00Z",
                "value": 1,
                "tags": {"id_wa": id_wa, "status": status, "resultado": resultado},
            },
        }
    )


def test_tudo_certo_quando_o_banco_tem_exatamente_o_que_foi_aceito() -> None:
    envios = [envio("a"), envio("b"), envio("c")]
    r = cc.comparar(envios, ["a", "b", "c"])
    assert r.ok
    assert (r.enviados_unicos, r.aceitos, r.no_banco) == (3, 3, 3)
    assert r.perdidas == r.duplicadas == r.inesperadas == []


def test_mensagem_aceita_que_nao_esta_no_banco_e_perdida() -> None:
    r = cc.comparar([envio("a"), envio("b")], ["a"])
    assert not r.ok
    assert r.perdidas == ["b"]


def test_id_repetido_no_banco_e_duplicata() -> None:
    r = cc.comparar([envio("a")], ["a", "a"])
    assert not r.ok
    assert r.duplicadas == ["a"]


def test_id_no_banco_que_o_k6_nunca_enviou_e_inesperado() -> None:
    r = cc.comparar([envio("a")], ["a", "z"])
    assert not r.ok
    assert r.inesperadas == ["z"]


def test_reentrega_do_mesmo_id_conta_uma_so_vez() -> None:
    envios = [envio("a"), envio("a", resultado="duplicada"), envio("b")]
    r = cc.comparar(envios, ["a", "b"])
    assert r.ok
    assert r.requisicoes == 3
    assert r.enviados_unicos == 2
    assert r.reentregas == 1


def test_reentrega_que_gravou_de_novo_e_detectada_como_duplicata() -> None:
    envios = [envio("a"), envio("a", resultado="duplicada")]
    r = cc.comparar(envios, ["a", "a"])
    assert not r.ok
    assert r.duplicadas == ["a"]


def test_requisicao_rejeitada_fora_do_banco_nao_e_perda() -> None:
    """5xx/timeout: a Evolution reenviaria; so e perda o que foi aceito (2xx) e sumiu."""
    envios = [envio("a"), envio("b", status=503, resultado="")]
    r = cc.comparar(envios, ["a"])
    assert r.ok
    assert r.rejeitadas == ["b"]


def test_requisicao_rejeitada_que_mesmo_assim_gravou_nao_e_inesperada() -> None:
    envios = [envio("a", status=0, resultado="")]
    r = cc.comparar(envios, ["a"])
    assert r.ok
    assert r.inesperadas == []


def test_id_rejeitado_e_depois_aceito_na_reentrega_conta_como_aceito() -> None:
    envios = [envio("a", status=503, resultado=""), envio("a")]
    r = cc.comparar(envios, ["a"])
    assert r.ok
    assert r.aceitos == 1
    assert r.rejeitadas == []


def test_sem_nenhum_envio_e_sem_banco_e_ok_mas_vazio() -> None:
    r = cc.comparar([], [])
    assert r.ok
    assert r.enviados_unicos == 0


def test_ler_eventos_k6_le_so_os_pontos_da_metrica() -> None:
    linhas = [
        json.dumps({"type": "Metric", "data": {"name": "msg_enviada"}, "metric": "msg_enviada"}),
        ponto("a"),
        json.dumps({"type": "Point", "metric": "http_reqs", "data": {"value": 1, "tags": {}}}),
        "",
        ponto("b", status="503", resultado=""),
        "isto nao e json",
    ]
    envios = cc.ler_eventos_k6(linhas)
    assert [(e.id_wa, e.status, e.resultado) for e in envios] == [
        ("a", 200, "processada"),
        ("b", 503, ""),
    ]


def test_status_nao_numerico_vira_zero() -> None:
    (e,) = cc.ler_eventos_k6([ponto("a", status="", resultado="")])
    assert e.status == 0


def test_formatar_relatorio_traz_os_totais_e_o_veredito() -> None:
    bom = cc.formatar(cc.comparar([envio("a")], ["a"]))
    assert "OK" in bom
    ruim = cc.formatar(cc.comparar([envio("a"), envio("b")], ["a"]))
    assert "FALHOU" in ruim
    assert "b" in ruim


def test_main_devolve_codigo_de_saida_pelo_veredito(tmp_path: Path) -> None:
    arquivo = tmp_path / "k6.json"
    arquivo.write_text("\n".join([ponto("a"), ponto("b")]))
    assert cc.executar(arquivo, ["a", "b"]) == 0
    assert cc.executar(arquivo, ["a"]) == 1
    with pytest.raises(FileNotFoundError):
        cc.executar(tmp_path / "nao-existe.json", [])
