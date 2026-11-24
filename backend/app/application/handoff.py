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
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Self
from uuid import UUID

from app.application.agente.acordo import MOTIVO_ACORDO_FECHADO
from app.application.agente.estado import (
    EstadoAtendimento,
    aparelho_desejado,
    descrever_troca,
    fatos_do_lead,
)
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
from app.domain.kanban import Etapa, calcular_etapa

log = logging.getLogger(__name__)

EVENTO_RESUMO = "handoff_resumo"
MOTIVO_FALHA_LLM = "falha_llm"
_PENDENCIAS_NO_MOTIVO = 3
_FALAS_DO_CLIENTE = 3
_FALA_MAX = 140
_MENSAGENS_PARA_RESUMO = 20
_OBSERVACOES_MAX = 600
_ROTULO_MIDIA = {"audio": "[áudio]", "imagem": "[imagem]"}

_SISTEMA_RESUMO = (
    "Você escreve o resumo de um atendimento de uma loja de celulares para o vendedor que vai "
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
class AcordoFechado:
    """O acordo que a IA fechou com o cliente (do `estado.acordo`; deterministico)."""

    fechado_em: datetime
    forma: str | None
    """Forma escolhida na proposta (rotulo), ex.: "Cartão de crédito em 12x Mastercard"."""
    valor_total: Decimal | None
    data_prevista: date | None
    endereco: str | None
    """O que a IA informou ao cliente (endereco, horarios e chave Pix da loja)."""
    horarios: str | None
    pix_chave: str | None
    pix_favorecido: str | None

    def para_dict(self) -> dict[str, Any]:
        return {
            "fechado_em": self.fechado_em.isoformat(),
            "forma": self.forma,
            "valor_total": None if self.valor_total is None else str(self.valor_total),
            "data_prevista": None if self.data_prevista is None else self.data_prevista.isoformat(),
            "endereco": self.endereco,
            "horarios": self.horarios,
            "pix_chave": self.pix_chave,
            "pix_favorecido": self.pix_favorecido,
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> Self:
        data = dados.get("data_prevista")
        return cls(
            fechado_em=datetime.fromisoformat(dados["fechado_em"]),
            forma=dados.get("forma"),
            valor_total=_decimal(dados.get("valor_total")),
            data_prevista=None if data is None else date.fromisoformat(data),
            endereco=dados.get("endereco"),
            horarios=dados.get("horarios"),
            pix_chave=dados.get("pix_chave"),
            pix_favorecido=dados.get("pix_favorecido"),
        )


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
    # Detalhes deterministicos (todos opcionais: resumos gravados antes deles nao os tem).
    cor: str | None = None
    sku: str | None = None
    troca_condicao: str | None = None
    troca_status: str | None = None
    """`avaliada`, `avaliacao_na_loja` ou `sem_troca` (da ultima proposta); None sem proposta."""
    valor_aparelho: Decimal | None = None
    desconto: Decimal | None = None
    parcelas: int | None = None
    valor_parcela: Decimal | None = None
    ultimas_mensagens_cliente: list[str] = field(default_factory=list)
    acordo: AcordoFechado | None = None
    """Acordo fechado pela IA antes do handoff (None quando nao houve)."""

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
            "cor": self.cor,
            "sku": self.sku,
            "troca_condicao": self.troca_condicao,
            "troca_status": self.troca_status,
            "valor_aparelho": None if self.valor_aparelho is None else str(self.valor_aparelho),
            "desconto": None if self.desconto is None else str(self.desconto),
            "parcelas": self.parcelas,
            "valor_parcela": None if self.valor_parcela is None else str(self.valor_parcela),
            "ultimas_mensagens_cliente": list(self.ultimas_mensagens_cliente),
            "acordo": None if self.acordo is None else self.acordo.para_dict(),
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
            cor=dados.get("cor"),
            sku=dados.get("sku"),
            troca_condicao=dados.get("troca_condicao"),
            troca_status=dados.get("troca_status"),
            valor_aparelho=_decimal(dados.get("valor_aparelho")),
            desconto=_decimal(dados.get("desconto")),
            parcelas=dados.get("parcelas"),
            valor_parcela=_decimal(dados.get("valor_parcela")),
            ultimas_mensagens_cliente=list(dados.get("ultimas_mensagens_cliente") or []),
            acordo=None if not dados.get("acordo") else AcordoFechado.de_dict(dados["acordo"]),
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
    """Decimal puro ("3900.00") ou texto pt-BR da proposta ("R$ 3.900,00"); None se ilegivel."""
    if valor is None:
        return None
    texto = str(valor).replace("R$", "").replace(" ", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _aparelho_com_aviso_de_bateria(texto: str | None, aparelho: dict[str, Any]) -> str | None:
    """Seminovo confirmado sem bateria cadastrada: o vendedor confirma a saude na loja."""
    if texto is None:
        return None
    sem_dado = "bateria_pct" in aparelho and aparelho["bateria_pct"] is None
    if aparelho.get("condicao") == "seminovo" and sem_dado:
        return f"{texto} (bateria não cadastrada — confirmar na loja)"
    return texto


def _condicao_do_usado(estado: EstadoAtendimento) -> str | None:
    """Estado do usado em poucas palavras ("tela danificada, bateria 82%"); None sem dados."""
    u = estado.ficha.usado
    if estado.ficha.tem_troca is not True:
        return None
    defeitos = [
        texto
        for texto, ativo in (
            ("tela danificada", u.tela_danificada),
            ("traseira danificada", u.traseira_danificada),
            ("carcaça marcada", u.carcaca_marcada),
            ("câmera com defeito", u.camera_ok is False),
            ("peça já trocada", u.peca_trocada),
        )
        if ativo
    ]
    defeitos.extend(u.outros_defeitos or ())
    if u.bateria_pct is not None:
        defeitos.append(f"bateria {u.bateria_pct}%")
    if defeitos:
        return ", ".join(defeitos)
    conhecido = any(
        v is not None
        for v in (u.tela_danificada, u.traseira_danificada, u.carcaca_marcada, u.camera_ok)
    )
    return "sem avarias informadas" if conhecido else None


def _etapa_antes_do_handoff(estado: EstadoAtendimento) -> Etapa:
    fatos = replace(fatos_do_lead(estado), handoff_realizado=False)
    return calcular_etapa(Etapa.NOVO_CONTATO, fatos)


def _o_que_falta(faltas: list[str]) -> str:
    if not faltas:
        return "a ficha estava completa"
    mostradas = faltas[:_PENDENCIAS_NO_MOTIVO]
    resto = len(faltas) - len(mostradas)
    texto = ", ".join(mostradas)
    return f"falta: {texto} e mais {resto}" if resto else f"falta: {texto}"


def _acordo_do_estado(estado: EstadoAtendimento) -> AcordoFechado | None:
    dados = estado.acordo
    if not dados:
        return None
    forma = dados.get("forma_escolhida") or {}
    valor = None
    for chave in ("total_pago", "valor_a_vista"):
        valor = _decimal(forma.get(chave))
        if valor is not None:
            break
    informado = dados.get("informado") or {}
    pix = informado.get("chave_pix") or {}
    data = dados.get("data_prevista")
    return AcordoFechado(
        fechado_em=datetime.fromisoformat(dados["fechado_em"]),
        forma=forma.get("rotulo"),
        valor_total=valor,
        data_prevista=None if data is None else date.fromisoformat(data),
        endereco=informado.get("endereco"),
        horarios=informado.get("horarios"),
        pix_chave=pix.get("chave"),
        pix_favorecido=pix.get("favorecido"),
    )


def _motivo_acordo_fechado(acordo: AcordoFechado) -> str:
    quando = f" em {acordo.data_prevista:%d/%m/%Y}" if acordo.data_prevista else ""
    return (
        f"Acordo fechado pela IA: cliente vai à loja{quando} para concluir; "
        "confira os detalhes abaixo."
    )


def _motivo_legivel(
    motivo: str, estado: EstadoAtendimento, faltas: list[str], acordo: AcordoFechado | None
) -> str:
    """Traduz motivos do sistema em texto acionavel; motivo da IA (texto livre) passa direto."""
    if motivo == MOTIVO_ACORDO_FECHADO and acordo is not None:
        return _motivo_acordo_fechado(acordo)
    if motivo != MOTIVO_FALHA_LLM:
        return motivo
    etapa = _etapa_antes_do_handoff(estado).nome_exibicao
    return (
        "A IA teve uma falha técnica e passou o atendimento para você. "
        f"O cliente estava em {etapa}; {_o_que_falta(faltas)}."
    )


def _falas_do_cliente(mensagens: Sequence[MensagemRegistro]) -> list[str]:
    falas: list[str] = []
    for m in mensagens:
        if m.autor != AUTOR_CLIENTE:
            continue
        texto = " ".join(_texto_da_mensagem(m).split())
        if not texto:
            continue
        falas.append(texto if len(texto) <= _FALA_MAX else texto[: _FALA_MAX - 1].rstrip() + "…")
    return falas[-_FALAS_DO_CLIENTE:]


def montar_resumo_estruturado(
    estado: EstadoAtendimento,
    *,
    motivo: str,
    agora: datetime,
    mensagens: Sequence[MensagemRegistro] = (),
) -> ResumoHandoff:
    """Parte deterministica do resumo: so le a ficha, a ultima proposta e as mensagens.

    Nenhum valor e calculado aqui: tudo vem da `ultima_proposta` ja calculada pelo dominio.
    """
    proposta = estado.ultima_proposta or {}
    forma = proposta.get("forma_escolhida") or {}
    troca = proposta.get("troca") or {}
    aparelho = proposta.get("aparelho") or {}
    desconto = proposta.get("desconto") or {}
    valor_troca = _decimal(troca.get("valor")) if troca.get("status") == "avaliada" else None
    valor_proposta = None
    for chave in ("total_pago", "valor_a_vista"):
        valor_proposta = _decimal(forma.get(chave))
        if valor_proposta is not None:
            break
    ficha = estado.ficha
    faltas = [ROTULOS_PENDENCIA[p] for p in pendencias(ficha)]
    acordo = _acordo_do_estado(estado)
    return ResumoHandoff(
        motivo=_motivo_legivel(motivo, estado, faltas, acordo),
        aparelho_desejado=_aparelho_com_aviso_de_bateria(aparelho_desejado(estado), aparelho),
        troca=descrever_troca(estado),
        valor_troca=valor_troca,
        proposta=forma.get("rotulo"),
        valor_proposta=valor_proposta,
        forma_pagamento=(descrever_pagamento(ficha) if ficha.pagamento.tipo is not None else None),
        data_prevista=ficha.data_prevista_compra,
        pendencias=faltas,
        observacoes=None,
        gerado_em=agora,
        cor=ficha.interesse.cor or aparelho.get("cor"),
        sku=ficha.interesse.sku_estoque_confirmado or aparelho.get("sku"),
        troca_condicao=_condicao_do_usado(estado),
        troca_status=troca.get("status"),
        valor_aparelho=_decimal(proposta.get("preco_aparelho")),
        desconto=_decimal(desconto.get("total")),
        parcelas=forma.get("parcelas"),
        valor_parcela=_decimal(forma.get("valor_parcela")),
        ultimas_mensagens_cliente=_falas_do_cliente(mensagens),
        acordo=acordo,
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
        todas = await self._repo.listar_mensagens(loja_id, lead_id)
        estruturado = montar_resumo_estruturado(
            estado, motivo=motivo, agora=self._agora(), mensagens=todas
        )
        observacoes = await self._observacoes(estruturado, todas[-_MENSAGENS_PARA_RESUMO:])
        resumo = replace(estruturado, observacoes=observacoes)
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
