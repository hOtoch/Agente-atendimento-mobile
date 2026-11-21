"""Leitura de imagem: o LLM le a foto/print, o CODIGO decide se grava na ficha ou confirma."""

from __future__ import annotations

import base64
import json
from datetime import date
from typing import Any

import pytest

from app.adapters.outbound.llm.fake import RespostaRoteirizada
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.imagem import (
    LIMIAR_CONFIANCA,
    LeituraImagem,
    TipoImagem,
    decidir_leitura,
    nome_da_midia,
)
from app.application.agente.prompt import mensagem_estado
from app.application.llm import BlocoImagem, BlocoTexto
from app.application.midia import ConteudoMidia
from app.domain.ficha import Ficha
from app.domain.valores import Capacidade, ModeloAparelho

from .apoio_ferramentas import criar_ambiente
from .apoio_processar import chamada, criar_cenario, resultados_json, texto

FICHA_TROCA = Ficha.vazia().com(tem_troca=True)
ESTADO_TROCA = EstadoAtendimento(ficha=FICHA_TROCA)
PNG = b"\x89PNG\r\n\x1a\nfake"


def _leitura(**campos: Any) -> LeituraImagem:
    base: dict[str, Any] = {
        "tipo": TipoImagem.PRINT_BATERIA,
        "bateria_pct": 82,
        "tela_danificada": None,
        "traseira_danificada": None,
        "carcaca_marcada": None,
        "modelo": None,
        "confianca": 0.95,
    }
    base.update(campos)
    return LeituraImagem(**base)


def _entrada(**campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tipo": "print_bateria",
        "bateria_pct": 82,
        "tela_danificada": None,
        "traseira_danificada": None,
        "carcaca_marcada": None,
        "modelo_provavel": None,
        "confianca": 0.95,
    }
    base.update(campos)
    return base


class MidiaEmMemoria:
    def __init__(self, itens: dict[str, ConteudoMidia] | None = None) -> None:
        self.itens = itens or {}

    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        nome = f"m{len(self.itens)}"
        self.itens[nome] = ConteudoMidia(dados, tipo_mime)
        return nome

    async def ler(self, nome: str) -> ConteudoMidia | None:
        return self.itens.get(nome)


# --- decisao (funcao pura do dominio da aplicacao) ------------------------------------------


def test_print_de_bateria_com_confianca_alta_grava_na_ficha() -> None:
    d = decidir_leitura(FICHA_TROCA, _leitura())
    assert d.gravado and d.pergunta is None
    assert d.ficha.usado.bateria_pct == 82
    assert d.campos == ("bateria_pct",)


def test_confianca_no_limiar_ainda_grava_e_abaixo_confirma() -> None:
    assert decidir_leitura(FICHA_TROCA, _leitura(confianca=LIMIAR_CONFIANCA)).gravado
    d = decidir_leitura(FICHA_TROCA, _leitura(confianca=LIMIAR_CONFIANCA - 0.01))
    assert not d.gravado
    assert d.ficha == FICHA_TROCA
    assert d.pergunta is not None and "82%" in d.pergunta


def test_foto_grava_so_os_danos_vistos_e_o_modelo() -> None:
    leitura = _leitura(
        tipo=TipoImagem.FOTO_APARELHO,
        bateria_pct=None,
        tela_danificada=True,
        traseira_danificada=None,
        carcaca_marcada=False,
        modelo=ModeloAparelho.de("iPhone 13"),
    )
    d = decidir_leitura(FICHA_TROCA, leitura)
    assert d.gravado
    u = d.ficha.usado
    assert u.tela_danificada is True and u.carcaca_marcada is False
    assert u.traseira_danificada is None  # nao apareceu na foto: continua pendente
    assert u.modelo == ModeloAparelho.de("iPhone 13")
    assert set(d.campos) == {"tela_danificada", "carcaca_marcada", "modelo"}


def test_foto_nao_sobrescreve_modelo_ja_informado() -> None:
    ficha = FICHA_TROCA.com_usado(modelo=ModeloAparelho.de("iPhone 12"))
    leitura = _leitura(
        tipo=TipoImagem.FOTO_APARELHO,
        bateria_pct=None,
        tela_danificada=False,
        modelo=ModeloAparelho.de("iPhone 13"),
    )
    d = decidir_leitura(ficha, leitura)
    assert d.ficha.usado.modelo == ModeloAparelho.de("iPhone 12")
    assert "modelo" not in d.campos


def test_sem_troca_confirmada_pergunta_antes_de_gravar() -> None:
    for ficha in (Ficha.vazia(), Ficha.vazia().com(tem_troca=False)):
        d = decidir_leitura(ficha, _leitura())
        assert not d.gravado and d.ficha == ficha
        assert d.pergunta is not None and "troca" in d.pergunta


def test_imagem_sem_nada_aproveitavel_nao_grava() -> None:
    for leitura in (
        _leitura(tipo=TipoImagem.OUTRO),
        _leitura(bateria_pct=None),
        _leitura(tipo=TipoImagem.OUTRO, confianca=0.2),
    ):
        d = decidir_leitura(FICHA_TROCA, leitura)
        assert not d.gravado and d.ficha == FICHA_TROCA
        assert d.campos == ()


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("http://localhost:8000/midias/" + "a" * 32 + ".jpg", "a" * 32 + ".jpg"),
        ("/midias/abc.png?x=1", "abc.png"),
        ("http://x/midias/", None),
        (None, None),
        ("", None),
    ],
)
def test_nome_da_midia(url: str | None, esperado: str | None) -> None:
    assert nome_da_midia(url) == esperado


# --- ferramenta registrar_leitura_imagem ---------------------------------------------------


async def test_ferramenta_alta_confianca_atualiza_a_ficha() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_leitura_imagem", _entrada(), ESTADO_TROCA)
    assert not r.erro
    assert r.conteudo["status"] == "ok"
    assert r.estado.ficha.usado.bateria_pct == 82
    assert r.conteudo["registrado"] == ["bateria_pct"]
    assert "faltam" in r.conteudo  # devolve o que ainda falta, como as outras ferramentas


async def test_ferramenta_baixa_confianca_devolve_confirmar_sem_gravar() -> None:
    amb = await criar_ambiente()
    r = await amb.rodar("registrar_leitura_imagem", _entrada(confianca=0.4), ESTADO_TROCA)
    assert not r.erro
    assert r.conteudo["status"] == "confirmar"
    assert "82%" in r.conteudo["pergunta"]
    assert r.estado == ESTADO_TROCA


async def test_ferramenta_valida_a_entrada() -> None:
    amb = await criar_ambiente()
    for ruim in (
        _entrada(tipo="selfie"),
        _entrada(bateria_pct=150),
        _entrada(confianca=1.5),
        _entrada(confianca="alta"),
        _entrada(tela_danificada="sim"),
    ):
        r = await amb.rodar("registrar_leitura_imagem", ruim, ESTADO_TROCA)
        assert r.erro and r.estado == ESTADO_TROCA, ruim


async def test_ferramenta_modelo_provavel_de_outra_marca_nao_quebra() -> None:
    amb = await criar_ambiente()
    entrada = _entrada(tipo="foto_aparelho", bateria_pct=None, modelo_provavel="Samsung S23")
    r = await amb.rodar("registrar_leitura_imagem", entrada, ESTADO_TROCA)
    assert not r.erro
    assert r.estado.ficha.usado.modelo is not None


# --- orquestrador: a imagem chega ao LLM e a ferramenta fecha o ciclo ------------------------


async def test_imagem_do_cliente_vai_para_o_llm_como_bloco_de_imagem() -> None:
    midia = MidiaEmMemoria({"abc.png": ConteudoMidia(PNG, "image/png")})
    c = await criar_cenario([texto("Recebi!")], midia=midia)
    c.conversas.adicionar_entrada(
        c.conversa_id, "olha a bateria", tipo="imagem", midia_url="http://x/midias/abc.png"
    )
    await c.caso(c.conversa_id)
    blocos = c.llm.chamadas[0].mensagens[0].blocos
    imagens = [b for b in blocos if isinstance(b, BlocoImagem)]
    assert imagens == [BlocoImagem("image/png", base64.b64encode(PNG).decode())]
    assert any(isinstance(b, BlocoTexto) and "olha a bateria" in b.texto for b in blocos)


async def test_imagem_ilegivel_cai_no_texto_provisorio() -> None:
    midia = MidiaEmMemoria()  # o arquivo sumiu
    c = await criar_cenario(
        [texto("Não consegui abrir a imagem, pode mandar de novo?")], midia=midia
    )
    c.conversas.adicionar_entrada(
        c.conversa_id, None, tipo="imagem", midia_url="http://x/midias/sumiu.png"
    )
    await c.caso(c.conversa_id)
    blocos = c.llm.chamadas[0].mensagens[0].blocos
    assert not any(isinstance(b, BlocoImagem) for b in blocos)
    assert [b.texto for b in blocos if isinstance(b, BlocoTexto)] == ["[cliente enviou uma imagem]"]


async def test_imagem_gigante_nao_vai_para_o_llm() -> None:
    grande = b"x" * (5 * 1024 * 1024 + 1)
    midia = MidiaEmMemoria({"g.png": ConteudoMidia(grande, "image/png")})
    c = await criar_cenario([texto("ok")], midia=midia)
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="imagem", midia_url="/midias/g.png")
    await c.caso(c.conversa_id)
    assert not any(isinstance(b, BlocoImagem) for b in c.llm.chamadas[0].mensagens[0].blocos)


async def _cenario_com_troca(roteiro: list[Any], midia: MidiaEmMemoria) -> Any:
    c = await criar_cenario(roteiro, midia=midia)
    await c.atendimento.salvar(c.loja_id, c.lead_id, ESTADO_TROCA)
    c.conversas.adicionar_entrada(
        c.conversa_id, None, tipo="imagem", midia_url="http://x/midias/abc.png"
    )
    return c


async def test_fake_le_print_82_e_a_ficha_e_atualizada() -> None:
    midia = MidiaEmMemoria({"abc.png": ConteudoMidia(PNG, "image/png")})
    c = await _cenario_com_troca(
        [
            RespostaRoteirizada(
                chamadas=[chamada("t1", "registrar_leitura_imagem", _entrada(bateria_pct=82))]
            ),
            texto("Anotei: bateria com 82%."),
        ],
        midia,
    )
    await c.caso(c.conversa_id)
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.ficha.usado.bateria_pct == 82
    (res,) = resultados_json(c.llm.chamadas[1].mensagens[-1])
    assert res["status"] == "ok"
    assert c.canal.textos == ["Anotei: bateria com 82%."]


async def test_fake_baixa_confianca_gera_confirmacao_e_nao_grava() -> None:
    midia = MidiaEmMemoria({"abc.png": ConteudoMidia(PNG, "image/png")})
    c = await _cenario_com_troca(
        [
            RespostaRoteirizada(
                chamadas=[
                    chamada(
                        "t1",
                        "registrar_leitura_imagem",
                        _entrada(bateria_pct=82, confianca=0.35),
                    )
                ]
            ),
            texto("O print está meio borrado. A saúde da bateria é 82%, certo?"),
        ],
        midia,
    )
    await c.caso(c.conversa_id)
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.ficha.usado.bateria_pct is None
    (res,) = resultados_json(c.llm.chamadas[1].mensagens[-1])
    assert res["status"] == "confirmar" and "82%" in res["pergunta"]
    # a confirmacao do cliente grava pela ferramenta que ja existia
    c.cliente_diz("isso, 82%")
    c.llm._roteiro.extend(
        [
            RespostaRoteirizada(
                chamadas=[chamada("t2", "registrar_usado", {"tem_troca": True, "bateria_pct": 82})]
            ),
            texto("Perfeito, anotado."),
        ]
    )
    await c.caso(c.conversa_id)
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.ficha.usado.bateria_pct == 82


async def test_leitura_registrada_nos_eventos_sem_dados_da_imagem() -> None:
    midia = MidiaEmMemoria({"abc.png": ConteudoMidia(PNG, "image/png")})
    c = await _cenario_com_troca(
        [
            RespostaRoteirizada(chamadas=[chamada("t1", "registrar_leitura_imagem", _entrada())]),
            texto("ok"),
        ],
        midia,
    )
    await c.caso(c.conversa_id)
    eventos = [e for e in c.eventos.registrados if e.tipo == "ferramenta"]
    assert eventos and eventos[0].payload["nome"] == "registrar_leitura_imagem"
    assert "base64" not in json.dumps(eventos[0].payload)


# --- prompt -------------------------------------------------------------------------------


def test_prompt_pede_print_de_bateria_e_menciona_a_leitura_de_imagem() -> None:
    from app.application.agente.prompt import carregar_prefixo

    base = carregar_prefixo()
    assert "registrar_leitura_imagem" in base
    assert "Ajustes > Bateria" in base
    estado = mensagem_estado(
        FICHA_TROCA.com_interesse(
            modelo=ModeloAparelho.de("iPhone 16"),
            capacidade=Capacidade(128),
            sku_estoque_confirmado="IP16-128-PRETO",
        ).com_usado(
            modelo=ModeloAparelho.de("iPhone 13"),
            capacidade=Capacidade(128),
            tela_danificada=False,
            traseira_danificada=False,
            carcaca_marcada=False,
        ),
        hoje=date(2026, 11, 20),
        estoque_consultado=True,
        proposta_apresentada=False,
        desconto_liberado=None,
        handoff_solicitado=False,
    )
    assert "PRÓXIMA PERGUNTA" in estado and "Ajustes > Bateria" in estado
    assert "registrar_leitura_imagem" in estado
