"""Cenario do orquestrador: tudo em memoria, ferramentas REAIS e FakeLLM roteirizado."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada, Roteiro
from app.application.agente.conversa_portas import ConversasEmMemoria, EventosEmMemoria
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import ProcessarConversa
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria
from app.application.agente.transcricao import RepositorioTranscricaoEmMemoria
from app.application.canal import Canal, MensagemSaida
from app.application.llm import (
    BlocoTexto,
    ChamadaFerramenta,
    MensagemLLM,
    RespostaLLM,
    ResultadoFerramenta,
)
from app.domain.kanban import Etapa

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    HOJE,
    INTERESSE_16,
    USADO_EXEMPLO,
    Ambiente,
    criar_ambiente,
)

__all__ = [
    "COMPRA_HOJE_12X",
    "INTERESSE_16",
    "USADO_EXEMPLO",
    "Cenario",
    "LLMComBruto",
    "chamada",
    "criar_cenario",
    "resultados_json",
    "texto",
]


class CanalEmMemoria:
    def __init__(self) -> None:
        self.enviadas: list[MensagemSaida] = []

    async def enviar(self, msg: MensagemSaida) -> None:
        self.enviadas.append(msg)

    @property
    def textos(self) -> list[str]:
        return [m.texto or "" for m in self.enviadas]


class LLMComBruto(FakeLLM):
    """FakeLLM que devolve o `content` original (com thinking) como o adaptador real faz."""

    async def responder(self, *args: Any, **kwargs: Any) -> RespostaLLM:
        resposta = await super().responder(*args, **kwargs)
        n = len(self.chamadas)
        bruto: list[dict[str, Any]] = [
            {"type": "thinking", "thinking": f"pensando {n}", "signature": f"assinatura-{n}"}
        ]
        for bloco in resposta.mensagem_assistente.blocos:
            if isinstance(bloco, BlocoTexto):
                bruto.append({"type": "text", "text": bloco.texto})
            elif isinstance(bloco, ChamadaFerramenta):
                bruto.append(
                    {"type": "tool_use", "id": bloco.id, "name": bloco.nome, "input": bloco.entrada}
                )
        msg = MensagemLLM("assistant", resposta.mensagem_assistente.blocos, bruto=bruto)
        return replace(resposta, mensagem_assistente=msg)


def chamada(id_: str, nome: str, entrada: dict[str, Any] | None = None) -> ChamadaFerramenta:
    return ChamadaFerramenta(id_, nome, entrada or {})


def texto(conteudo: str) -> RespostaRoteirizada:
    return RespostaRoteirizada(texto=conteudo)


def resultados_json(msg: MensagemLLM) -> list[dict[str, Any]]:
    """Conteudo JSON dos `ResultadoFerramenta` de uma mensagem user."""
    return [json.loads(b.conteudo) for b in msg.blocos if isinstance(b, ResultadoFerramenta)]


@dataclass
class Cenario:
    amb: Ambiente
    llm: FakeLLM
    canal: CanalEmMemoria
    conversas: ConversasEmMemoria
    transcricao: RepositorioTranscricaoEmMemoria
    atendimento: RepositorioAtendimentoEmMemoria
    eventos: EventosEmMemoria
    caso: ProcessarConversa
    conversa_id: UUID

    @property
    def lead_id(self) -> UUID:
        return self.amb.lead_id

    @property
    def loja_id(self) -> UUID:
        return self.amb.loja_id

    def cliente_diz(self, conteudo: str) -> None:
        self.conversas.adicionar_entrada(self.conversa_id, conteudo)

    async def turno(self, conteudo: str) -> None:
        self.cliente_diz(conteudo)
        await self.caso(self.conversa_id)

    def etapa(self) -> Etapa:
        return self.conversas.etapa(self.lead_id)

    def tipos_de_evento(self) -> list[str]:
        return [e.tipo for e in self.eventos.registrados]


async def criar_cenario(
    roteiro: list[Roteiro],
    *,
    llm_cls: type[FakeLLM] = FakeLLM,
    dono: str = "ia",
    max_iteracoes: int = 6,
    catalogo: CatalogoFerramentas | None = None,
) -> Cenario:
    amb = await criar_ambiente()
    conversas = ConversasEmMemoria()
    conversa_id = conversas.criar_conversa(
        loja_id=amb.loja_id,
        lead_id=amb.lead_id,
        canal=Canal.WEBCHAT,
        contato="sessao-1",
        dono=dono,
    )
    llm = llm_cls(roteiro)
    canal = CanalEmMemoria()
    transcricao = RepositorioTranscricaoEmMemoria()
    atendimento = RepositorioAtendimentoEmMemoria()
    eventos = EventosEmMemoria()
    caso = ProcessarConversa(
        conversas=conversas,
        transcricao=transcricao,
        atendimento=atendimento,
        eventos=eventos,
        llm=llm,
        catalogo=catalogo or amb.catalogo,
        canais={Canal.WEBCHAT: canal},
        config=amb.casos,
        estoque=amb.ctx.estoque,
        hoje=lambda: HOJE,
        max_iteracoes=max_iteracoes,
    )
    return Cenario(amb, llm, canal, conversas, transcricao, atendimento, eventos, caso, conversa_id)
