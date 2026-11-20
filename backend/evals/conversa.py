"""Roda UM cenario: cliente simulado <-> agente real (ProcessarConversa) em memoria."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.adapters.outbound.llm.fake import FakeLLM
from app.application.canal import MensagemSaida
from app.application.llm import (
    ChamadaFerramenta,
    LLMPort,
    ResultadoFerramenta,
    UsoTokens,
)
from app.infra.seed_data.preco import PRECO
from evals.ambiente import Ambiente, montar_ambiente
from evals.checagens import avaliar
from evals.cliente import Cliente, ClienteRoteirizado
from evals.modelos import (
    HOJE,
    Cenario,
    Checagem,
    Evento,
    ExecucaoFerramenta,
    MensagemAgente,
    MensagemCliente,
    Parametros,
    Transcricao,
)
from evals.roteiros import ROTEIROS_FAKE

PARAMETROS = Parametros(teto=PRECO.desconto_teto, oportunidade_max=PRECO.oportunidade_valor)
_MARCA_ERRO_INTERNO = "Erro interno ao executar a ferramenta"


@dataclass(slots=True)
class ResultadoCenario:
    cenario: Cenario
    transcricao: Transcricao
    checagens: list[Checagem]
    uso_agente: UsoTokens
    uso_cliente: UsoTokens
    turnos: int
    erro: str | None = None
    ferramentas_chamadas: list[str] = field(default_factory=list)

    @property
    def aprovado(self) -> bool:
        return self.erro is None and all(c.passou for c in self.checagens if c.aplicavel)


class _CanalColetor:
    def __init__(self) -> None:
        self.textos: list[str] = []

    async def enviar(self, msg: MensagemSaida) -> None:
        self.textos.append(msg.texto or "")


def _eventos_de_ferramenta(mensagens: list[Any]) -> list[ExecucaoFerramenta]:
    pendentes: dict[str, ChamadaFerramenta] = {}
    saida: list[ExecucaoFerramenta] = []
    for m in mensagens:
        for b in m.blocos:
            if isinstance(b, ChamadaFerramenta):
                pendentes[b.id] = b
            elif isinstance(b, ResultadoFerramenta):
                chamada = pendentes.get(b.id_chamada)
                try:
                    dado = json.loads(b.conteudo)
                except ValueError:
                    dado = {"bruto": b.conteudo}
                if not isinstance(dado, dict):
                    dado = {"bruto": dado}
                saida.append(
                    ExecucaoFerramenta(
                        nome=chamada.nome if chamada else "?",
                        entrada=chamada.entrada if chamada else {},
                        resultado=dado,
                        erro=b.erro,
                        erro_interno=b.erro and _MARCA_ERRO_INTERNO in b.conteudo,
                    )
                )
    return saida


def _uso_do_agente(amb: Ambiente) -> UsoTokens:
    total = UsoTokens.vazio()
    for e in amb.eventos.registrados:
        if e.tipo == "llm_uso":
            p = e.payload
            total = total + UsoTokens(
                p["modelo"], p["entrada"], p["saida"], p["cache_leitura"], p["cache_escrita"]
            )
    return total


async def rodar_cenario(
    cenario: Cenario, llm_agente: LLMPort, cliente: Cliente, parametros: Parametros = PARAMETROS
) -> ResultadoCenario:
    canal = _CanalColetor()
    amb = await montar_ambiente(llm_agente, canal, HOJE)
    eventos: list[Evento] = []
    vistas = 0
    enviadas = 0
    turnos = 0
    erro: str | None = None
    try:
        for _ in range(cenario.max_turnos):
            fala = await cliente.proxima_fala(eventos)
            if fala is None:
                break
            turnos += 1
            eventos.append(MensagemCliente(fala))
            await amb.cliente_fala(fala)
            transcricao_llm = await amb.transcricao.listar(amb.conversa_id)
            eventos.extend(_eventos_de_ferramenta(transcricao_llm[vistas:]))
            vistas = len(transcricao_llm)
            eventos.extend(MensagemAgente(t) for t in canal.textos[enviadas:])
            enviadas = len(canal.textos)
            if (await amb.atendimento.obter(amb.loja_id, amb.lead_id)).handoff_solicitado:
                break
    except Exception as exc:  # o relatorio mostra a falha do cenario em vez de abortar a rodada
        erro = f"{type(exc).__name__}: {exc}"
    estado = await amb.atendimento.obter(amb.loja_id, amb.lead_id)
    transcricao = Transcricao(
        tuple(eventos),
        etapa_final=amb.conversas.etapa(amb.lead_id).value,
        handoff=estado.handoff_solicitado,
    )
    return ResultadoCenario(
        cenario=cenario,
        transcricao=transcricao,
        checagens=avaliar(cenario, transcricao, parametros),
        uso_agente=_uso_do_agente(amb),
        uso_cliente=cliente.uso,
        turnos=turnos,
        erro=erro,
        ferramentas_chamadas=[f.nome for f in transcricao.ferramentas],
    )


async def rodar_cenario_fake(cenario: Cenario) -> ResultadoCenario:
    """Agente roteirizado (FakeLLM) + cliente roteirizado; ferramentas e loja demo reais."""
    llm = FakeLLM(list(ROTEIROS_FAKE[cenario.id]))
    return await rodar_cenario(cenario, llm, ClienteRoteirizado(cenario.roteiro))
