"""Composicao em memoria do agente na loja demo (sem Postgres nem Redis).

Usada pelo eval e pelo `scripts/conversar.py`: mesmas ferramentas, estoque e config reais.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application.agente.conversa_portas import ConversasEmMemoria, EventosEmMemoria
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.processar_conversa import ProcessarConversa
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria
from app.application.agente.transcricao import RepositorioTranscricaoEmMemoria
from app.application.canal import Canal, CanalPort
from app.application.config.memoria import criar_casos_em_memoria
from app.application.llm import LLMPort
from app.infra.composicao import hoje_brasil
from app.infra.seed import aplicar_dados


@dataclass(slots=True)
class Ambiente:
    caso: ProcessarConversa
    conversas: ConversasEmMemoria
    transcricao: RepositorioTranscricaoEmMemoria
    atendimento: RepositorioAtendimentoEmMemoria
    eventos: EventosEmMemoria
    loja_id: UUID
    lead_id: UUID
    conversa_id: UUID

    async def cliente_fala(self, texto: str) -> None:
        """O cliente manda uma mensagem e o agente processa o turno."""
        self.conversas.adicionar_entrada(self.conversa_id, texto)
        await self.caso(self.conversa_id)


async def montar_ambiente(
    llm: LLMPort,
    canal: CanalPort,
    hoje: date | None = None,
    nome_loja: str = "Loja Demo (eval)",
) -> Ambiente:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja(nome_loja)
    await aplicar_dados(casos, loja_id)
    conversas = ConversasEmMemoria()
    lead_id = uuid4()
    conversa_id = conversas.criar_conversa(
        loja_id=loja_id, lead_id=lead_id, canal=Canal.WEBCHAT, contato="eval"
    )
    transcricao = RepositorioTranscricaoEmMemoria()
    atendimento = RepositorioAtendimentoEmMemoria()
    eventos = EventosEmMemoria()
    relogio: Callable[[], date] = (lambda: hoje) if hoje else hoje_brasil
    caso = ProcessarConversa(
        conversas=conversas,
        transcricao=transcricao,
        atendimento=atendimento,
        eventos=eventos,
        llm=llm,
        catalogo=CatalogoFerramentas(),
        canais={Canal.WEBCHAT: canal},
        config=casos,
        estoque=PlanilhaAdapter(FonteEstoqueLocalSql(casos.estoque)),
        hoje=relogio,
    )
    return Ambiente(
        caso, conversas, transcricao, atendimento, eventos, loja_id, lead_id, conversa_id
    )
