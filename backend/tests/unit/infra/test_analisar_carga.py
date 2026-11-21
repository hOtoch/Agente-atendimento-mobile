"""Metricas do teste de carga: fila, throughput do worker e latencia ate a resposta."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CAMINHO = Path(__file__).resolve().parents[3] / "scripts" / "analisar_carga.py"


def _carregar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analisar_carga", _CAMINHO)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


ac = _carregar()


def amostra(t: float, zcard: int = 0, prontos: int = 0, exec_: int = 0) -> object:
    return ac.Amostra(t=t, zcard=zcard, prontos=prontos, em_execucao=exec_, entradas=0, saidas=0)


def test_percentis_pelo_metodo_do_posto_mais_proximo() -> None:
    valores = [float(v) for v in range(1, 101)]
    p = ac.percentis(valores)
    assert (p[50], p[95], p[99]) == (50.0, 95.0, 99.0)


def test_percentis_de_lista_vazia_sao_none() -> None:
    assert ac.percentis([]) == {50: None, 95: None, 99: None}


def test_resumo_da_fila_pega_os_picos_e_o_tempo_para_esvaziar() -> None:
    amostras = [
        amostra(0, zcard=2, prontos=0, exec_=1),
        amostra(10, zcard=40, prontos=12, exec_=10),
        amostra(20, zcard=30, prontos=5, exec_=10),  # fim da carga
        amostra(25, zcard=8, prontos=0, exec_=6),
        amostra(31, zcard=0, prontos=0, exec_=0),
        amostra(32, zcard=0, prontos=0, exec_=0),
    ]
    r = ac.resumir_fila(amostras, fim_carga=20)
    assert (r.max_zcard, r.max_prontos, r.max_em_execucao) == (40, 12, 10)
    assert r.esvaziou_em_s == pytest.approx(11)


def test_fila_que_nunca_esvazia_devolve_none() -> None:
    r = ac.resumir_fila([amostra(0, zcard=3), amostra(5, zcard=1)], fim_carga=0)
    assert r.esvaziou_em_s is None


def test_fila_ja_vazia_no_fim_da_carga_esvaziou_em_zero() -> None:
    r = ac.resumir_fila([amostra(0, zcard=3), amostra(10), amostra(11)], fim_carga=10)
    assert r.esvaziou_em_s == 0


def test_throughput_media_e_pico_por_minuto() -> None:
    # 30 envios no 1o minuto, 90 no 2o
    envios = [i * 2.0 for i in range(30)] + [60 + i * (60 / 90) for i in range(90)]
    t = ac.throughput(envios)
    assert t.total == 120
    assert t.pico_por_min == 90
    assert t.media_por_min == pytest.approx(120 / (max(envios) - min(envios)) * 60)


def test_throughput_sem_envios() -> None:
    t = ac.throughput([])
    assert (t.total, t.pico_por_min, t.media_por_min) == (0, 0, 0.0)


def test_latencia_ate_a_resposta_conta_desde_a_ultima_mensagem_do_cliente() -> None:
    msgs = [(10.0, "A"), (11.0, "A"), (12.0, "B")]
    respostas = [(18.5, "A"), (20.0, "B")]
    assert ac.latencias_resposta(msgs, respostas) == [7.5, 8.0]


def test_resposta_sem_mensagem_anterior_do_cliente_e_ignorada() -> None:
    assert ac.latencias_resposta([(10.0, "A")], [(5.0, "A"), (9.0, "Z")]) == []


def test_ler_amostras_do_csv(tmp_path: Path) -> None:
    arq = tmp_path / "fila.csv"
    arq.write_text("t,zcard,prontos,em_execucao,entradas,saidas\n100.5,3,1,2,10,4\n")
    (a,) = ac.ler_amostras(arq)
    assert (a.t, a.zcard, a.prontos, a.em_execucao, a.entradas, a.saidas) == (100.5, 3, 1, 2, 10, 4)


def test_ler_log_do_stub_so_traz_os_envios_de_texto(tmp_path: Path) -> None:
    arq = tmp_path / "stub.jsonl"
    linhas = [
        {"t": 1.0, "rota": "/message/sendText/loja-x", "numero": "551"},
        {"t": 2.0, "rota": "/chat/sendPresence/loja-x", "numero": "551"},
        {"t": 3.0, "rota": "/message/sendText/loja-x", "numero": "552"},
    ]
    arq.write_text("\n".join(json.dumps(x) for x in linhas) + "\nlixo\n")
    assert ac.ler_envios_stub(arq) == [(1.0, "551"), (3.0, "552")]


def test_ler_mensagens_k6_traz_tempo_e_numero_dos_ids_unicos() -> None:
    def ponto(t: str, id_wa: str, numero: str, reentrega: str = "0") -> str:
        tags = {"id_wa": id_wa, "numero": numero, "status": "200", "reentrega": reentrega}
        evento = {"type": "Point", "metric": "msg_enviada", "data": {"time": t, "tags": tags}}
        return json.dumps(evento)

    linhas = [
        ponto("2026-11-21T10:00:00Z", "a", "551"),
        ponto("2026-11-21T10:00:00Z", "a", "551", reentrega="1"),
        ponto("2026-11-21T10:00:05.500+00:00", "b", "552"),
    ]
    msgs = ac.ler_mensagens_k6(linhas)
    assert [n for _, n in msgs] == ["551", "552"]
    assert msgs[1][0] - msgs[0][0] == pytest.approx(5.5)
