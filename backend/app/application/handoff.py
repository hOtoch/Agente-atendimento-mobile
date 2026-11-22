"""Handoff entre a IA e o vendedor: quem e o dono da conversa e o que o vendedor recebe.

- `assumir`: o vendedor toma a conversa (a IA fica em silencio: o orquestrador le `dono`).
- `devolver`: a IA volta a atender. O contexto dela ganha, por acrescimo, o que foi dito
  durante o atendimento humano e a instrucao de continuar dali sem repetir perguntas.
- `chamar_vendedor`: a IA (ferramenta `chamar_vendedor` ou falha do LLM) passa a conversa
  para "aguardando vendedor" (`dono = vendedor`, sem vendedor atribuido), gera o resumo e
  avisa o gancho `AoSolicitarHandoff` (distribuicao/notificacao ficam por conta de quem o
  implementa).

O resumo tem uma parte ESTRUTURADA, calculada so do estado (nunca depende do LLM), e
`observacoes`: 2 a 3 frases do LLM (objecoes, clima, proximo passo) que viram `None` se o LLM
falhar. Nenhum valor monetario e decidido pelo LLM.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Self
from uuid import UUID

from app.application.agente.estado import EstadoAtendimento, aparelho_desejado
from app.application.agente.prompt import ROTULOS_PENDENCIA, descrever_pagamento
from app.application.agente.repositorio import RepositorioAtendimento
from app.application.agente.transcricao import RepositorioTranscricao
from app.application.llm import BlocoTexto, LLMPort, MensagemLLM
from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.portas import (
    AUTOR_CLIENTE,
    AUTOR_IA,
    AUTOR_VENDEDOR,
    DONO_IA,
    DONO_VENDEDOR,
    LeadRegistro,
    MensagemRegistro,
    RepositorioPainel,
)
from app.application.painel.publicador import PublicadorPainel, publicar_sem_falhar
from app.domain.ficha import pendencias

log = logging.getLogger(__name__)

EVENTO_RESUMO = "handoff_resumo"
MOTIVOS_DO_SISTEMA: dict[str, str] = {
    "falha_llm": "A IA ficou indisponível e passou a conversa para o vendedor",
}
_MENSAGENS_PARA_RESUMO = 20
_OBSERVACOES_MAX = 600
_ROTULO_MIDIA = {"audio": "[áudio]", "imagem": "[imagem]"}

_SISTEMA_RESUMO = (
    "Você escreve o resumo de um atendimento de uma loja de iPhones para o vendedor que vai "
    "assumir a conversa. Escreva de 2 a 3 frases curtas em português, em texto corrido (sem "
    "listas e sem títulos), cobrindo: as objeções ou dúvidas do cliente, o clima da conversa "
    "e o próximo passo recomendado. Use somente o que está na conversa. Não cite valores em "
    "reais, não invente informações e não dê preços."
)

_INSTRUCAO_DEVOLUCAO = (
    "O vendedor da loja atendeu o cliente diretamente e devolveu a conversa para você. "
    "Leia o que foi dito abaixo e continue dali: NÃO repita perguntas que o cliente já "
    "respondeu ao vendedor e não contradiga o que o vendedor combinou. Se o cliente passou "
    "algum dado novo ao vendedor, registre-o com a ferramenta certa antes da próxima pergunta."
)


class LeadNaoEncontrado(Exception):
    def __init__(self, lead_id: object) -> None:
        super().__init__(f"lead nao encontrado: {lead_id}")
        self.lead_id = lead_id


class VendedorNaoEncontrado(Exception):
    def __init__(self, vendedor_id: object) -> None:
        super().__init__(f"vendedor nao encontrado: {vendedor_id}")
        self.vendedor_id = vendedor_id


class ConflitoDono(Exception):
    """A operacao nao cabe no dono atual da conversa (ex.: devolver o que ja e da IA)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True, slots=True)
class ResumoHandoff:
    """O que o vendedor precisa saber ao assumir. Os campos estruturados sao deterministicos."""

    motivo: str
    aparelho_desejado: str | None
    troca: str | None
    valor_troca: Decimal | None
    proposta: str | None
    valor_proposta: Decimal | None
    forma_pagamento: str | None
    data_prevista: date | None
    pendencias: list[str]
    observacoes: str | None
    gerado_em: datetime

    def para_dict(self) -> dict[str, Any]:
        return {
            "motivo": self.motivo,
            "aparelho_desejado": self.aparelho_desejado,
            "troca": self.troca,
            "valor_troca": None if self.valor_troca is None else str(self.valor_troca),
            "proposta": self.proposta,
            "valor_proposta": None if self.valor_proposta is None else str(self.valor_proposta),
            "forma_pagamento": self.forma_pagamento,
            "data_prevista": None if self.data_prevista is None else self.data_prevista.isoformat(),
            "pendencias": list(self.pendencias),
            "observacoes": self.observacoes,
            "gerado_em": self.gerado_em.isoformat(),
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> Self:
        data = dados.get("data_prevista")
        return cls(
            motivo=dados["motivo"],
            aparelho_desejado=dados.get("aparelho_desejado"),
            troca=dados.get("troca"),
            valor_troca=_decimal(dados.get("valor_troca")),
            proposta=dados.get("proposta"),
            valor_proposta=_decimal(dados.get("valor_proposta")),
            forma_pagamento=dados.get("forma_pagamento"),
            data_prevista=None if data is None else date.fromisoformat(data),
            pendencias=list(dados.get("pendencias") or []),
            observacoes=dados.get("observacoes"),
            gerado_em=datetime.fromisoformat(dados["gerado_em"]),
        )


class AoSolicitarHandoff(Protocol):
    """Gancho chamado depois que a conversa ficou aguardando vendedor (ex.: distribuir o lead
    e avisar o vendedor no WhatsApp). Falhas aqui nao desfazem o handoff."""

    async def handoff_solicitado(
        self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff
    ) -> None: ...


class GanchosHandoff:
    """Varios ganchos em sequencia (ex.: avisar o vendedor e DEPOIS exportar para o ERP).

    A ordem importa: um gancho posterior ve o que o anterior fez (a atribuicao do vendedor).
    A falha de um nunca impede os seguintes nem desfaz o handoff.
    """

    def __init__(self, ganchos: Sequence[AoSolicitarHandoff]) -> None:
        self.ganchos: tuple[AoSolicitarHandoff, ...] = tuple(ganchos)

    async def handoff_solicitado(self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff) -> None:
        for gancho in self.ganchos:
            try:
                await gancho.handoff_solicitado(loja_id, lead_id, resumo)
            except Exception:
                log.exception(
                    "gancho %s do handoff do lead %s falhou", type(gancho).__name__, lead_id
                )


class AoSolicitarHandoffNulo:
    async def handoff_solicitado(self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff) -> None:
        return None


def _decimal(valor: object) -> Decimal | None:
    try:
        return Decimal(str(valor)) if valor is not None else None
    except InvalidOperation:
        return None


def _descrever_troca(estado: EstadoAtendimento) -> str | None:
    ficha = estado.ficha
    if ficha.tem_troca is None:
        return None
    if ficha.tem_troca is False:
        return "Sem aparelho na troca"
    u = ficha.usado
    if u.modelo is None:
        return "Aparelho usado (modelo ainda não informado)"
    return f"{u.modelo.nome} {u.capacidade}" if u.capacidade is not None else u.modelo.nome


def montar_resumo_estruturado(
    estado: EstadoAtendimento, *, motivo: str, agora: datetime
) -> ResumoHandoff:
    """Parte deterministica do resumo: so le a ficha e a ultima proposta."""
    proposta = estado.ultima_proposta or {}
    forma = proposta.get("forma_escolhida") or {}
    troca = proposta.get("troca") or {}
    valor_troca = _decimal(troca.get("valor")) if troca.get("status") == "avaliada" else None
    valor_proposta = None
    for chave in ("total_pago", "valor_a_vista"):
        valor_proposta = _decimal(forma.get(chave))
        if valor_proposta is not None:
            break
    ficha = estado.ficha
    return ResumoHandoff(
        motivo=MOTIVOS_DO_SISTEMA.get(motivo, motivo),
        aparelho_desejado=aparelho_desejado(estado),
        troca=_descrever_troca(estado),
        valor_troca=valor_troca,
        proposta=forma.get("rotulo"),
        valor_proposta=valor_proposta,
        forma_pagamento=(descrever_pagamento(ficha) if ficha.pagamento.tipo is not None else None),
        data_prevista=ficha.data_prevista_compra,
        pendencias=[ROTULOS_PENDENCIA[p] for p in pendencias(ficha)],
        observacoes=None,
        gerado_em=agora,
    )


def _texto_da_mensagem(m: MensagemRegistro) -> str:
    if m.texto:
        return m.texto
    return _ROTULO_MIDIA.get(m.tipo.value, "")


_AUTORES = {AUTOR_CLIENTE: "Cliente", AUTOR_IA: "IA", AUTOR_VENDEDOR: "Vendedor"}


def _linhas(mensagens: list[MensagemRegistro]) -> list[str]:
    return [f"{_AUTORES.get(m.autor, m.autor)}: {_texto_da_mensagem(m)}" for m in mensagens]


def _agora() -> datetime:
    return datetime.now(UTC)


class CasosHandoff:
    def __init__(
        self,
        *,
        repo: RepositorioPainel,
        publicador: PublicadorPainel,
        transcricao: RepositorioTranscricao,
        atendimento: RepositorioAtendimento,
        llm: LLMPort | None = None,
        aviso: AoSolicitarHandoff | None = None,
        agora: Callable[[], datetime] = _agora,
    ) -> None:
        self._repo = repo
        self._publicador = publicador
        self._transcricao = transcricao
        self._atendimento = atendimento
        self._llm = llm
        self._aviso: AoSolicitarHandoff = aviso or AoSolicitarHandoffNulo()
        self._agora = agora

    async def _lead(self, loja_id: UUID, lead_id: UUID) -> LeadRegistro:
        lead = await self._repo.obter_lead(loja_id, lead_id)
        if lead is None:
            raise LeadNaoEncontrado(lead_id)
        return lead

    async def _publicar_dono(
        self, loja_id: UUID, lead_id: UUID, dono: str, vendedor_id: UUID | None
    ) -> None:
        await publicar_sem_falhar(
            self._publicador,
            loja_id,
            EventoDonoMudou(lead_id=lead_id, dono=dono, vendedor_id=vendedor_id, em=self._agora()),
        )

    # --- assumir / devolver ---------------------------------------------------------------

    async def assumir(self, loja_id: UUID, lead_id: UUID, vendedor_id: UUID) -> LeadRegistro:
        """O vendedor assume. Aceita a conversa "aguardando vendedor" (dono vendedor sem id);
        so recusa quando OUTRO vendedor ja e o dono."""
        lead = await self._lead(loja_id, lead_id)
        if not await self._repo.vendedor_existe(loja_id, vendedor_id):
            raise VendedorNaoEncontrado(vendedor_id)
        if lead.dono == DONO_VENDEDOR and lead.vendedor_id is not None:
            if lead.vendedor_id == vendedor_id:
                return lead
            raise ConflitoDono("A conversa ja esta com outro vendedor.")
        dono = f"{DONO_VENDEDOR}:{vendedor_id}"
        await self._repo.definir_dono(
            loja_id,
            lead_id,
            DONO_VENDEDOR,
            vendedor_id,
            {"dono": dono, "vendedor_id": str(vendedor_id)},
        )
        await self._publicar_dono(loja_id, lead_id, dono, vendedor_id)
        return await self._lead(loja_id, lead_id)

    async def devolver(self, loja_id: UUID, lead_id: UUID) -> LeadRegistro:
        lead = await self._lead(loja_id, lead_id)
        if lead.dono != DONO_VENDEDOR:
            raise ConflitoDono("A conversa ja esta com a IA.")
        # contexto da IA primeiro (por acrescimo); so depois o dono muda
        await self._acrescentar_contexto_da_devolucao(lead)
        estado = await self._atendimento.obter(loja_id, lead_id)
        if estado.handoff_solicitado or estado.motivo_handoff is not None:
            await self._atendimento.salvar(
                loja_id, lead_id, replace(estado, handoff_solicitado=False, motivo_handoff=None)
            )
        await self._repo.definir_dono(loja_id, lead_id, DONO_IA, None, {"dono": DONO_IA})
        await self._publicar_dono(loja_id, lead_id, DONO_IA, None)
        return await self._lead(loja_id, lead_id)

    async def _acrescentar_contexto_da_devolucao(self, lead: LeadRegistro) -> None:
        if lead.conversa_id is None:
            return
        mensagens = await self._repo.listar_mensagens(lead.loja_id, lead.id)
        cursor = await self._transcricao.consumido_ate(lead.conversa_id)
        # a fala da IA e tudo o que veio antes ja esta na transcricao; o que veio depois e do
        # atendimento humano. Entradas do cliente ainda nao consumidas viram a mensagem `user`
        # do proximo turno, entao ficam de fora (nada duplicado).
        ultima_ia = max((i for i, m in enumerate(mensagens) if m.autor == AUTOR_IA), default=-1)
        humano = [
            m
            for m in mensagens[ultima_ia + 1 :]
            if m.autor == AUTOR_VENDEDOR
            or (
                m.autor == AUTOR_CLIENTE
                and cursor is not None
                and (m.criada_em, m.id) <= (cursor.criado_em, cursor.id)
            )
        ]
        partes = [_INSTRUCAO_DEVOLUCAO, ""]
        if humano:
            partes.append("Conversa durante o atendimento do vendedor:")
            partes.extend(_linhas(humano))
        else:
            partes.append("O vendedor não trocou mensagens com o cliente nesse período.")
        await self._transcricao.acrescentar(
            lead.conversa_id, [MensagemLLM("system", [BlocoTexto("\n".join(partes))])]
        )

    # --- chamar o vendedor (pela IA) --------------------------------------------------------

    async def chamar_vendedor(self, loja_id: UUID, lead_id: UUID, motivo: str) -> ResumoHandoff:
        lead = await self._lead(loja_id, lead_id)
        estado = await self._atendimento.obter(loja_id, lead_id)
        if lead.dono != DONO_VENDEDOR:
            await self._repo.definir_dono(
                loja_id,
                lead_id,
                DONO_VENDEDOR,
                None,
                {"dono": DONO_VENDEDOR, "vendedor_id": None, "motivo": motivo},
                limpar_vendedor=True,
            )
            await self._publicar_dono(loja_id, lead_id, DONO_VENDEDOR, None)
        estruturado = montar_resumo_estruturado(estado, motivo=motivo, agora=self._agora())
        mensagens = (await self._repo.listar_mensagens(loja_id, lead_id))[-_MENSAGENS_PARA_RESUMO:]
        resumo = replace(estruturado, observacoes=await self._observacoes(estruturado, mensagens))
        await self._repo.registrar_evento(loja_id, lead_id, EVENTO_RESUMO, resumo.para_dict())
        try:
            await self._aviso.handoff_solicitado(loja_id, lead_id, resumo)
        except Exception:
            log.exception("falha no gancho de handoff do lead %s", lead_id)
        return resumo

    async def _observacoes(
        self, resumo: ResumoHandoff, mensagens: list[MensagemRegistro]
    ) -> str | None:
        """2 a 3 frases do LLM; qualquer falha ou resposta vazia vira None."""
        if self._llm is None:
            return None
        conteudo = "\n".join(
            [
                f"Motivo do handoff: {resumo.motivo}",
                f"Aparelho desejado: {resumo.aparelho_desejado or 'não definido'}",
                f"Troca: {resumo.troca or 'não informada'}",
                f"Pagamento: {resumo.forma_pagamento or 'não informado'}",
                "",
                "Conversa (mais antigas primeiro):",
                *(_linhas(mensagens) or ["(sem mensagens)"]),
            ]
        )
        try:
            resposta = await self._llm.responder(
                [_SISTEMA_RESUMO], [MensagemLLM("user", [BlocoTexto(conteudo)])], [], 300
            )
        except Exception:
            log.warning("resumo do handoff sem observacoes do LLM", exc_info=True)
            return None
        texto = " ".join(resposta.texto.split())
        if not texto or resposta.chamadas:
            return None
        return texto[:_OBSERVACOES_MAX]

    async def resumo_do_lead(self, loja_id: UUID, lead_id: UUID) -> ResumoHandoff | None:
        """Ultimo resumo gravado (None se o lead nunca passou por `chamar_vendedor`)."""
        evento = await self._repo.ultimo_evento(loja_id, lead_id, EVENTO_RESUMO)
        if evento is None:
            return None
        try:
            return ResumoHandoff.de_dict(evento.payload)
        except (KeyError, ValueError):
            log.warning("resumo de handoff ilegivel no lead %s", lead_id)
            return None
