"""FakeLLM: roteiro de respostas para testes de todo o projeto (sem rede)."""

from __future__ import annotations

import pytest

from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada, RoteiroEsgotado
from app.application.llm import (
    BlocoTexto,
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ErroLLM,
    LLMIndisponivel,
    LLMPort,
    MensagemLLM,
    ResultadoFerramenta,
    UsoTokens,
)

FERRAMENTA = DefinicaoFerramenta("buscar_estoque", "Busca", {"type": "object"})


def usuario(texto: str) -> MensagemLLM:
    return MensagemLLM("user", [BlocoTexto(texto)])


async def test_cobre_o_loop_de_ferramentas_com_duas_respostas() -> None:
    chamada = ChamadaFerramenta("toolu_1", "buscar_estoque", {"modelo": "iPhone 16"})
    llm = FakeLLM(
        [
            RespostaRoteirizada(chamadas=[chamada]),
            RespostaRoteirizada(texto="Tenho o iPhone 16 por R$ 4.830."),
        ]
    )
    historico = [usuario("tem iphone 16?")]

    r1 = await llm.responder(["sys"], historico, [FERRAMENTA])
    assert r1.motivo_parada == "tool_use"
    assert r1.chamadas == [chamada]
    assert r1.mensagem_assistente.papel == "assistant"
    assert chamada in r1.mensagem_assistente.blocos

    historico += [
        r1.mensagem_assistente,
        MensagemLLM("user", [ResultadoFerramenta("toolu_1", "1 em estoque")]),
    ]
    r2 = await llm.responder(["sys"], historico, [FERRAMENTA])
    assert r2.motivo_parada == "end_turn"
    assert r2.chamadas == []
    assert r2.texto == "Tenho o iPhone 16 por R$ 4.830."
    assert r2.mensagem_assistente.blocos == [BlocoTexto(r2.texto)]


async def test_registra_as_chamadas_recebidas() -> None:
    llm = FakeLLM([RespostaRoteirizada(texto="oi")])
    msgs = [usuario("ola")]
    await llm.responder(["estavel", "volatil"], msgs, [FERRAMENTA], max_tokens=256)

    assert len(llm.chamadas) == 1
    c = llm.chamadas[0]
    assert c.sistema == ["estavel", "volatil"]
    assert c.mensagens == msgs
    assert c.ferramentas == [FERRAMENTA]
    assert c.max_tokens == 256


async def test_registro_nao_muda_quando_o_chamador_altera_a_lista() -> None:
    llm = FakeLLM([RespostaRoteirizada(texto="a"), RespostaRoteirizada(texto="b")])
    msgs = [usuario("1")]
    await llm.responder([], msgs, [])
    msgs.append(usuario("2"))
    await llm.responder([], msgs, [])
    assert len(llm.chamadas[0].mensagens) == 1
    assert len(llm.chamadas[1].mensagens) == 2


async def test_roteiro_aceita_funcao_que_ve_as_mensagens() -> None:
    def ecoar(mensagens: list[MensagemLLM]) -> RespostaRoteirizada:
        bloco = mensagens[-1].blocos[0]
        assert isinstance(bloco, BlocoTexto)
        return RespostaRoteirizada(texto=f"voce disse: {bloco.texto}")

    llm = FakeLLM([ecoar])
    r = await llm.responder([], [usuario("bom dia")], [])
    assert r.texto == "voce disse: bom dia"


async def test_roteiro_esgotado_falha_com_mensagem_clara() -> None:
    llm = FakeLLM([RespostaRoteirizada(texto="so uma")])
    await llm.responder([], [usuario("a")], [])
    with pytest.raises(RoteiroEsgotado, match="2"):
        await llm.responder([], [usuario("b")], [])


async def test_resposta_pode_levantar_erro_de_llm() -> None:
    llm = FakeLLM([RespostaRoteirizada(erro=LLMIndisponivel("fora do ar"))])
    with pytest.raises(LLMIndisponivel):
        await llm.responder([], [usuario("a")], [])
    assert len(llm.chamadas) == 1  # a chamada que falha tambem fica registrada


async def test_uso_e_acumulado_por_conversa() -> None:
    uso = UsoTokens("fake", entrada=10, saida=4, cache_leitura=90, cache_escrita=0)
    llm = FakeLLM([RespostaRoteirizada(texto="a", uso=uso), RespostaRoteirizada(texto="b")])
    r1 = await llm.responder([], [usuario("1")], [])
    r2 = await llm.responder([], [usuario("2")], [])
    assert r1.uso == uso
    assert r2.uso.modelo == "fake"  # padrao zerado
    assert llm.uso_total == r1.uso + r2.uso


async def test_motivo_e_modelo_podem_ser_forcados() -> None:
    llm = FakeLLM(
        [RespostaRoteirizada(texto="corta", motivo_parada="max_tokens", modelo="reserva")]
    )
    r = await llm.responder([], [usuario("a")], [])
    assert (r.motivo_parada, r.modelo_usado) == ("max_tokens", "reserva")


def test_implementa_llm_port_e_erro_base() -> None:
    llm: LLMPort = FakeLLM([])
    assert llm is not None
    assert issubclass(RoteiroEsgotado, ErroLLM)
