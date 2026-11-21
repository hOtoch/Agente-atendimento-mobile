"""Cenario do orquestrador: tudo em memoria, ferramentas REAIS e FakeLLM roteirizado."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada, Roteiro
from app.application.agente.conversa_portas import (
    ConversasEmMemoria,
    EntradaConversa,
    EventosEmMemoria,
)
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import ProcessarConversa
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria
from app.application.agente.transcricao import RepositorioTranscricaoEmMemoria
from app.application.audio_entrada import TranscreverAudio
from app.application.canal import Canal, MensagemSaida, TipoMensagem
from app.application.handoff import CasosHandoff
from app.application.llm import (
    BlocoTexto,
    ChamadaFerramenta,
    MensagemLLM,
    RespostaLLM,
    ResultadoFerramenta,
)
from app.application.midia import ArmazenamentoMidia
from app.application.painel.memoria import PublicadorEmMemoria, RepositorioPainelEmMemoria
from app.application.painel.portas import LeadRegistro, MensagemRegistro
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


class PainelSincronizado(RepositorioPainelEmMemoria):
    """Painel em memoria cujo dono tambem vale para o `ConversasEmMemoria` do orquestrador."""

    def __init__(self, conversas: ConversasEmMemoria) -> None:
        super().__init__()
        self._conversas = conversas

    def adicionar_mensagem_como(self, lead_id: UUID, entrada: EntradaConversa, texto: str) -> None:
        self._mensagens.setdefault(lead_id, []).append(
            MensagemRegistro(
                entrada.id,
                self.leads[lead_id].conversa_id,  # type: ignore[arg-type]
                "entrada",
                "cliente",
                TipoMensagem.TEXTO,
                texto,
                None,
                entrada.criado_em,
            )
        )

    async def definir_dono(  # type: ignore[override]
        self, loja_id: UUID, lead_id: UUID, dono: str, *args: Any, **kwargs: Any
    ) -> None:
        await super().definir_dono(loja_id, lead_id, dono, *args, **kwargs)
        self._conversas.definir_dono(lead_id, dono)


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
    painel: PublicadorEmMemoria
    painel_repo: PainelSincronizado
    handoff: CasosHandoff

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

    def vendedor_diz(self, conteudo: str) -> None:
        self.painel_repo.adicionar_mensagem(self.lead_id, autor="vendedor", texto=conteudo)

    def cliente_diz_ao_vendedor(self, conteudo: str) -> None:
        """A mesma mensagem (id e horario) na entrada do orquestrador e no historico do painel."""
        entrada = self.conversas.adicionar_entrada(self.conversa_id, conteudo)
        self.painel_repo.adicionar_mensagem_como(self.lead_id, entrada, conteudo)

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
    midia: ArmazenamentoMidia | None = None,
    transcrever: TranscreverAudio | None = None,
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
    painel = PublicadorEmMemoria()
    painel_repo = PainelSincronizado(conversas)
    painel_repo.leads[amb.lead_id] = LeadRegistro(
        id=amb.lead_id,
        loja_id=amb.loja_id,
        conversa_id=conversa_id,
        nome=None,
        telefone="sessao-1",
        canal=Canal.WEBCHAT,
        etapa=Etapa.NOVO_CONTATO,
        etapa_desde=conversas._relogio,
        dono=dono,
        vendedor_id=None,
        vendedor_nome=None,
        criado_em=conversas._relogio,
        estado=EstadoAtendimento(),
    )
    handoff = CasosHandoff(
        repo=painel_repo,
        publicador=painel,
        transcricao=transcricao,
        atendimento=atendimento,
        llm=llm,
    )
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
        painel=painel,
        handoff=handoff,
        transcrever_audio=transcrever,
        max_iteracoes=max_iteracoes,
        midia=midia,
    )
    return Cenario(
        amb, llm, canal, conversas, transcricao, atendimento, eventos, caso, conversa_id, painel,
        painel_repo, handoff,
    )  # fmt: skip
