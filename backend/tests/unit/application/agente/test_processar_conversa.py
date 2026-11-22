"""Orquestrador da conversa: E2E com FakeLLM roteirizado, ferramentas reais, tudo em memoria."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.adapters.outbound.llm.fake import RespostaRoteirizada
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import (
    MENSAGEM_ESPERA,
    MENSAGEM_LIMITE,
)
from app.application.llm import (
    BlocoTexto,
    LLMIndisponivel,
    LLMRecusou,
    MensagemLLM,
    ResultadoFerramenta,
    UsoTokens,
)
from app.domain.kanban import Etapa

from .apoio_processar import (
    COMPRA_HOJE_12X,
    INTERESSE_16,
    USADO_EXEMPLO,
    LLMComBruto,
    chamada,
    criar_cenario,
    resultados_json,
    texto,
)


def _roteiro_completo() -> list[Any]:
    return [
        # turno 1
        RespostaRoteirizada(
            chamadas=[
                chamada("t1", "registrar_interesse", INTERESSE_16),
                chamada("t2", "consultar_estoque", INTERESSE_16),
            ]
        ),
        texto("Temos o iPhone 16 128GB. Você tem aparelho para dar na troca?"),
        # turno 2
        RespostaRoteirizada(chamadas=[chamada("t3", "registrar_usado", USADO_EXEMPLO)]),
        texto("Anotado! Quando pretende comprar e como vai pagar?"),
        # turno 3
        RespostaRoteirizada(chamadas=[chamada("t4", "registrar_compra", COMPRA_HOJE_12X)]),
        texto("Perfeito, já tenho tudo para montar sua proposta."),
        # turno 4
        RespostaRoteirizada(chamadas=[chamada("t5", "calcular_proposta")]),
        texto("Aqui está a proposta para você."),
    ]


def _estado_msg(msgs: list[MensagemLLM]) -> list[MensagemLLM]:
    return [m for m in msgs if m.papel == "system"]


async def test_fluxo_completo_etapas_canal_e_transcricao_por_acrescimo() -> None:
    c = await criar_cenario(_roteiro_completo(), llm_cls=LLMComBruto)
    assert c.etapa() is Etapa.NOVO_CONTATO

    await c.turno("oi, quero um iphone 16 128")
    assert c.etapa() is Etapa.INTERESSE_IDENTIFICADO
    assert c.canal.textos == ["Temos o iPhone 16 128GB. Você tem aparelho para dar na troca?"]
    assert c.canal.enviadas[0].destinatario == "sessao-1"
    assert c.canal.enviadas[0].loja_id == c.loja_id

    await c.turno("tenho um iphone 16 128 com a tela trincada, bateria 79")
    assert c.etapa() is Etapa.INTERESSE_IDENTIFICADO

    await c.turno("compro hoje, 12x no mastercard")
    assert c.etapa() is Etapa.INTERESSE_QUALIFICADO

    await c.turno("e quanto fica?")
    assert c.etapa() is Etapa.INTERESSE_QUALIFICADO
    assert len(c.canal.enviadas) == 4

    # cada request e a reproducao exata do anterior mais mensagens novas (so acrescimo)
    anteriores: list[MensagemLLM] = []
    for chamada_recebida in c.llm.chamadas:
        msgs = chamada_recebida.mensagens
        assert msgs[: len(anteriores)] == anteriores
        anteriores = msgs
    # os `bruto` (thinking + assinatura) reaparecem intactos nos requests seguintes
    ultimo = c.llm.chamadas[-1].mensagens
    brutos = [m.bruto for m in ultimo if m.papel == "assistant"]
    assert brutos and all(b is not None and b[0]["type"] == "thinking" for b in brutos)
    assert brutos[0] == [
        {"type": "thinking", "thinking": "pensando 1", "signature": "assinatura-1"},
        {
            "type": "tool_use",
            "id": "t1",
            "name": "registrar_interesse",
            "input": INTERESSE_16,
        },
        {"type": "tool_use", "id": "t2", "name": "consultar_estoque", "input": INTERESSE_16},
    ]
    # transcricao final == o que o ultimo request viu + a resposta final do assistente
    final = await c.transcricao.listar(c.conversa_id)
    assert final[: len(ultimo)] == ultimo
    assert final[-1].papel == "assistant"

    # uma mensagem de estado por turno, gravada e nunca removida
    estados = _estado_msg(final)
    assert len(estados) == 4
    assert all("ESTADO DO ATENDIMENTO" in e.blocos[0].texto for e in estados)  # type: ignore[union-attr]
    assert "ESTADO DO ATENDIMENTO" in c.llm.chamadas[0].mensagens[-1].blocos[0].texto  # type: ignore[union-attr]
    assert c.llm.chamadas[0].mensagens[-1].papel == "system"
    # a ficha foi gravada
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.estoque_consultado and estado.ficha.interesse.capacidade is not None

    tipos = c.tipos_de_evento()
    assert tipos.count("etapa_mudou") == 2
    assert tipos.count("ferramenta") == 5
    assert tipos.count("llm_uso") == 4
    # o ultimo turno chamou calcular_proposta com ficha completa: trava liberada
    r = resultados_json(c.llm.chamadas[-1].mensagens[-1])[0]
    assert r["bloqueado"] is False


async def test_ferramentas_da_mesma_resposta_voltam_numa_unica_mensagem_user() -> None:
    c = await criar_cenario(_roteiro_completo()[:2])
    await c.turno("oi, quero um iphone 16 128")
    segunda = c.llm.chamadas[1].mensagens
    ultimo = segunda[-1]
    assert ultimo.papel == "user"
    assert [b.id_chamada for b in ultimo.blocos if isinstance(b, ResultadoFerramenta)] == [
        "t1",
        "t2",
    ]
    assert segunda[-2].papel == "assistant"


async def test_preco_antecipado_e_bloqueado_e_nenhum_valor_sai_pelo_canal() -> None:
    c = await criar_cenario(
        [
            RespostaRoteirizada(chamadas=[chamada("t1", "calcular_proposta")]),
            texto("Antes preciso saber qual iPhone você procura. Qual modelo?"),
        ]
    )
    await c.turno("quanto custa o iphone 16?")
    resultado = resultados_json(c.llm.chamadas[1].mensagens[-1])[0]
    assert resultado["bloqueado"] is True
    assert c.etapa() is Etapa.NOVO_CONTATO
    assert all("R$" not in t for t in c.canal.textos)
    assert len(c.canal.enviadas) == 1


async def test_dono_vendedor_ia_nao_responde_e_marca_como_consumidas() -> None:
    c = await criar_cenario([texto("nao deveria")], dono="vendedor")
    await c.turno("oi")
    assert c.llm.chamadas == []
    assert c.canal.enviadas == []
    assert await c.transcricao.listar(c.conversa_id) == []
    # devolvido a IA: o que o vendedor ja atendeu nao volta a ser respondido
    c.conversas.definir_dono(c.lead_id, "ia")
    await c.caso(c.conversa_id)
    assert c.llm.chamadas == []
    await c.turno("e agora?")
    assert len(c.llm.chamadas) == 1
    user = c.llm.chamadas[0].mensagens[0]
    assert [b.texto for b in user.blocos if isinstance(b, BlocoTexto)] == ["e agora?"]


async def test_sem_entradas_novas_e_idempotente() -> None:
    c = await criar_cenario([texto("Oi! Qual iPhone você procura?")])
    await c.turno("oi")
    await c.caso(c.conversa_id)
    await c.caso(c.conversa_id)
    assert len(c.llm.chamadas) == 1
    assert len(c.canal.enviadas) == 1


@pytest.mark.parametrize("erro", [LLMIndisponivel("fora"), LLMRecusou("cyber")])
async def test_falha_total_do_llm_faz_handoff(erro: Exception) -> None:
    c = await criar_cenario([RespostaRoteirizada(erro=erro)])  # type: ignore[arg-type]
    await c.turno("oi, quero um iphone")
    assert c.canal.textos == [MENSAGEM_ESPERA]
    assert c.etapa() is Etapa.COM_O_VENDEDOR
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.handoff_solicitado and estado.motivo_handoff == "falha_llm"
    tipos = c.tipos_de_evento()
    assert "etapa_mudou" in tipos and "handoff" in tipos
    assert len(c.conversas.saidas) == 1


async def test_limite_de_iteracoes_responde_com_seguranca() -> None:
    laco = [RespostaRoteirizada(chamadas=[chamada(f"t{i}", "calcular_proposta")]) for i in range(6)]
    c = await criar_cenario(laco, max_iteracoes=6)
    await c.turno("preco?")
    assert len(c.llm.chamadas) == 6
    assert c.canal.textos == [MENSAGEM_LIMITE]
    assert "limite_iteracoes" in c.tipos_de_evento()
    # a resposta segura tambem entra na transcricao, para o modelo saber o que o cliente viu
    final = await c.transcricao.listar(c.conversa_id)
    assert final[-1].papel == "assistant"


async def test_duas_mensagens_antes_do_processamento_viram_um_turno() -> None:
    c = await criar_cenario([texto("Oi! Qual iPhone você procura?")])
    c.cliente_diz("oi")
    c.cliente_diz("quero um iphone 16")
    await c.caso(c.conversa_id)
    msgs = c.llm.chamadas[0].mensagens
    assert [m.papel for m in msgs] == ["user", "system"]
    assert [b.texto for b in msgs[0].blocos if isinstance(b, BlocoTexto)] == [
        "oi",
        "quero um iphone 16",
    ]
    assert len(c.canal.enviadas) == 1


async def test_erro_inesperado_de_ferramenta_vira_tool_result_de_erro_e_segue() -> None:
    class Quebrado(CatalogoFerramentas):
        async def executar(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom secreto")

    c = await criar_cenario(
        [
            RespostaRoteirizada(chamadas=[chamada("t1", "registrar_interesse", INTERESSE_16)]),
            texto("Tive um probleminha, pode repetir?"),
        ],
        catalogo=Quebrado(),
    )
    await c.turno("quero iphone 16")
    bloco = c.llm.chamadas[1].mensagens[-1].blocos[0]
    assert isinstance(bloco, ResultadoFerramenta) and bloco.erro
    assert "boom" not in bloco.conteudo
    assert c.canal.textos == ["Tive um probleminha, pode repetir?"]
    erros = [e for e in c.eventos.registrados if e.tipo == "ferramenta_erro"]
    assert len(erros) == 1 and "boom secreto" in json.dumps(erros[0].payload)


async def test_midia_vira_texto_provisorio() -> None:
    c = await criar_cenario([texto("Recebi! Pode escrever o que precisa?")])
    c.conversas.adicionar_entrada(c.conversa_id, None, tipo="audio")
    c.conversas.adicionar_entrada(c.conversa_id, "e essa foto", tipo="imagem")
    await c.caso(c.conversa_id)
    textos = [b.texto for b in c.llm.chamadas[0].mensagens[0].blocos if isinstance(b, BlocoTexto)]
    assert textos[0] == "[cliente enviou um áudio]"
    assert textos[1].startswith("[cliente enviou uma imagem]") and "e essa foto" in textos[1]


async def test_uso_de_tokens_e_registrado() -> None:
    uso = UsoTokens("fake", 10, 5, 100, 20)
    c = await criar_cenario([RespostaRoteirizada(texto="Oi!", uso=uso)])
    await c.turno("oi")
    ev = [e for e in c.eventos.registrados if e.tipo == "llm_uso"]
    assert len(ev) == 1
    assert ev[0].payload["entrada"] == 10 and ev[0].payload["cache_leitura"] == 100
    assert ev[0].payload["modelo"] == "fake"


async def test_publica_no_painel_a_etapa_do_agente_e_a_mensagem_da_ia() -> None:
    c = await criar_cenario(_roteiro_completo()[:2])
    await c.turno("oi, quero um iphone 16 128")

    publicados = [(loja, ev) for loja, ev in c.painel.publicados]
    assert all(loja == c.loja_id for loja, _ in publicados)
    nomes = [ev.nome for _, ev in publicados]
    assert nomes == ["EtapaMudou", "MensagemNova"]

    etapa = publicados[0][1]
    assert (etapa.de, etapa.para, etapa.ator) == (  # type: ignore[union-attr]
        Etapa.NOVO_CONTATO,
        Etapa.INTERESSE_IDENTIFICADO,
        "ia",
    )
    assert etapa.lead_id == c.lead_id  # type: ignore[union-attr]
    msg = publicados[1][1]
    assert (msg.autor, msg.direcao, msg.tipo) == ("ia", "saida", "texto")  # type: ignore[union-attr]
    assert msg.texto == c.canal.textos[0]  # type: ignore[union-attr]
    assert msg.conversa_id == c.conversa_id  # type: ignore[union-attr]


async def test_dono_vendedor_nao_publica_nada_nem_responde() -> None:
    c = await criar_cenario([], dono="vendedor")
    await c.turno("alguem ai?")
    assert c.painel.publicados == []
    assert c.canal.enviadas == []


async def test_falha_no_painel_nao_derruba_o_turno() -> None:
    c = await criar_cenario(_roteiro_completo()[:2])
    c.painel.falhar = True
    await c.turno("oi, quero um iphone 16 128")
    assert len(c.canal.enviadas) == 1
    assert c.etapa() is Etapa.INTERESSE_IDENTIFICADO


# --- handoff: a IA chama o vendedor e depois recebe a conversa de volta -------------------------


async def test_chamar_vendedor_passa_a_conversa_para_aguardando_vendedor() -> None:
    c = await criar_cenario(
        [
            RespostaRoteirizada(
                chamadas=[chamada("t1", "chamar_vendedor", {"motivo": "quer fechar"})]
            ),
            texto("Vou chamar um vendedor para você 🙂"),
            texto("Cliente quer fechar. Sem objeções. Passar ao vendedor."),  # resumo do handoff
        ]
    )
    await c.turno("quero fechar a compra")

    assert c.canal.textos == ["Vou chamar um vendedor para você 🙂"]
    lead = c.painel_repo.leads[c.lead_id]
    assert lead.dono == "vendedor" and lead.vendedor_id is None
    donos = [e for _, e in c.painel.publicados if e.nome == "DonoMudou"]
    assert len(donos) == 1 and donos[0].dono == "vendedor"  # type: ignore[union-attr]
    resumo = await c.handoff.resumo_do_lead(c.loja_id, c.lead_id)
    assert resumo is not None and resumo.motivo == "quer fechar"
    assert resumo.observacoes == "Cliente quer fechar. Sem objeções. Passar ao vendedor."
    # a IA fica em silencio dali em diante
    chamadas_antes = len(c.llm.chamadas)
    await c.turno("alguem ai?")
    assert len(c.llm.chamadas) == chamadas_antes
    assert len(c.canal.enviadas) == 1


async def test_falha_do_llm_tambem_passa_para_aguardando_vendedor_com_resumo() -> None:
    c = await criar_cenario([RespostaRoteirizada(erro=LLMIndisponivel("fora"))])
    await c.turno("oi, quero um iphone")

    assert c.canal.textos == [MENSAGEM_ESPERA]
    assert c.painel_repo.leads[c.lead_id].dono == "vendedor"
    resumo = await c.handoff.resumo_do_lead(c.loja_id, c.lead_id)
    assert resumo is not None
    assert resumo.motivo == "A IA ficou indisponível e passou a conversa para o vendedor"
    assert resumo.observacoes is None  # o LLM tambem estava fora (roteiro esgotado)
    assert resumo.pendencias  # estrutura sempre presente


async def test_devolver_a_ia_nao_repete_pergunta_ja_respondida_ao_vendedor() -> None:
    vistos: dict[str, Any] = {}

    def segundo_turno(msgs: list[MensagemLLM]) -> RespostaRoteirizada:
        vistos["contexto_1"] = list(msgs)
        return RespostaRoteirizada(
            chamadas=[
                chamada("t2", "registrar_interesse", INTERESSE_16),
            ]
        )

    def depois_de_registrar(msgs: list[MensagemLLM]) -> RespostaRoteirizada:
        return texto("Combinado, seguimos daqui! Quer ver as opções no estoque?")

    def terceiro_turno(msgs: list[MensagemLLM]) -> RespostaRoteirizada:
        vistos["contexto_3"] = list(msgs)
        return texto("Certo!")

    c = await criar_cenario(
        [
            RespostaRoteirizada(
                chamadas=[chamada("t1", "chamar_vendedor", {"motivo": "quer ajuda"})]
            ),
            texto("Vou chamar um vendedor 🙂"),
            texto("Cliente pediu ajuda."),  # resumo do handoff
            segundo_turno,
            depois_de_registrar,
            terceiro_turno,
        ]
    )
    await c.turno("oi, preciso de ajuda")
    assert c.painel_repo.leads[c.lead_id].dono == "vendedor"

    # o vendedor assume, conversa e o cliente responde o que a ficha pede (qual iPhone)
    await c.handoff.assumir(c.loja_id, c.lead_id, _vendedor(c))
    c.vendedor_diz("Oi! Qual iPhone você procura?")
    c.cliente_diz_ao_vendedor("Quero o iPhone 16 de 128GB")
    await c.caso(c.conversa_id)  # IA em silencio: so marca como consumida
    assert len(c.llm.chamadas) == 3  # tool, resposta e resumo

    await c.handoff.devolver(c.loja_id, c.lead_id)
    assert c.painel_repo.leads[c.lead_id].dono == "ia"
    estado = await c.atendimento.obter(c.loja_id, c.lead_id)
    assert estado.handoff_solicitado is False

    await c.turno("e aí?")

    contexto = vistos["contexto_1"]
    sistemas = [
        "".join(b.texto for b in m.blocos if isinstance(b, BlocoTexto))
        for m in contexto
        if m.papel == "system"
    ]
    devolucao = next(t for t in sistemas if "devolveu a conversa" in t)
    assert "Vendedor: Oi! Qual iPhone você procura?" in devolucao
    assert "Cliente: Quero o iPhone 16 de 128GB" in devolucao
    assert "não repita" in devolucao.lower()
    # a instrucao vem antes da mensagem do cliente e do estado do turno
    papeis = [m.papel for m in contexto]
    assert papeis.index("system") < len(papeis) - 2
    ultimo_user = contexto[-2]
    assert ultimo_user.papel == "user"
    assert [b.texto for b in ultimo_user.blocos if isinstance(b, BlocoTexto)] == ["e aí?"]
    # o estado do turno nao manda mais perguntar o que ja foi respondido nem diz "vendedor chamado"
    estado_msg = sistemas[-1]
    assert "Um vendedor já foi chamado" not in estado_msg

    # no turno seguinte a ficha ja tem o iPhone que o cliente disse ao vendedor: a PROXIMA
    # PERGUNTA nao e mais o modelo/capacidade
    await c.turno("sim")
    ultimo_estado = [
        "".join(b.texto for b in m.blocos if isinstance(b, BlocoTexto))
        for m in vistos["contexto_3"]
        if m.papel == "system"
    ][-1]
    proxima = ultimo_estado.split("PRÓXIMA PERGUNTA:")[1].split("\n")[0]
    assert "Pergunte qual modelo" not in proxima
    assert "consultar_estoque" in proxima  # avancou para o passo seguinte da ficha


def _vendedor(c: Any) -> Any:
    from uuid import uuid4

    vendedor = uuid4()
    c.painel_repo.adicionar_vendedor(c.loja_id, vendedor, "Carla")
    return vendedor


async def test_marcas_do_estoque_da_loja_chegam_ao_bloco_da_loja() -> None:
    from app.application.config.modelos import LinhaEstoqueLocal
    from app.domain.estoque import Condicao
    from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

    c = await criar_cenario([texto("Oi! Qual aparelho você procura?")])
    linhas = [
        LinhaEstoqueLocal(
            "SS-1",
            ModeloAparelho.de("Galaxy S23", "Samsung"),
            Capacidade(256),
            "Preto",
            Condicao.NOVO,
            Dinheiro.de(1000),
            1,
            None,
        ),
        LinhaEstoqueLocal(
            "IP-1",
            ModeloAparelho.de("iPhone 15"),
            Capacidade(128),
            "Preto",
            Condicao.NOVO,
            Dinheiro.de(3000),
            1,
            None,
        ),
    ]
    await c.amb.casos.estoque.substituir(c.loja_id, linhas)
    await c.turno("oi")
    bloco_da_loja = c.llm.chamadas[0].sistema[1]
    assert "Samsung" in bloco_da_loja and "iPhone" in bloco_da_loja
