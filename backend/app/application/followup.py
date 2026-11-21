"""Follow-up automatico: acha os leads parados, decide (dominio) e manda UMA mensagem.

O CODIGO decide quem recebe e quando (`domain.followup.decidir_followup`); o LLM so redige o
texto, a partir da ficha e das ultimas mensagens. Cada tentativa vira um evento `followup`
(gravado ANTES do envio: na duvida, prefere nao repetir a mensagem ao cliente).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Protocol
from uuid import UUID

from app.application.agendamento import TravaConversa
from app.application.agente.conversa_portas import DONO_IA
from app.application.agente.prompt import montar_sistema, resumo_do_que_sabemos
from app.application.agente.repositorio import RepositorioAtendimento
from app.application.agente.transcricao import RepositorioTranscricao
from app.application.canal import Canal, CanalPort, MensagemSaida, TipoMensagem
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.modelos import (
    ErroCampo,
    ErrosDeValidacao,
    LojaNaoEncontrada,
    PerfilLoja,
)
from app.application.config.portas import RepositorioLojas
from app.application.llm import BlocoImagem, BlocoTexto, ErroLLM, LLMPort, MensagemLLM
from app.application.painel.eventos import EventoMensagemNova
from app.application.painel.publicador import (
    PublicadorPainel,
    PublicadorPainelNulo,
    publicar_sem_falhar,
)
from app.domain.followup import (
    ETAPAS_COM_FOLLOWUP,
    ConfigFollowup,
    ConfigFollowupInvalida,
    FatosFollowup,
    decidir_followup,
)
from app.domain.kanban import Etapa

log = logging.getLogger(__name__)

TIPO_EVENTO_FOLLOWUP = "followup"
_PERFIL_PADRAO = PerfilLoja("nossa loja", "simpático e objetivo", "", {}, "")
_ULTIMAS_MENSAGENS = 6
_TRAVA_TTL_S = 120.0


@dataclass(frozen=True, slots=True)
class CandidatoFollowup:
    """Lead da IA com a conversa parada (o repositorio ja resume o historico dele)."""

    loja_id: UUID
    lead_id: UUID
    conversa_id: UUID
    canal: Canal
    contato: str
    etapa: Etapa
    dono: str
    ultima_mensagem_em: datetime
    ultima_mensagem_do_cliente: bool
    tentativas: int
    """Follow-ups enviados depois da ultima mensagem do cliente."""
    ultimo_followup_em: datetime | None

    def fatos(self) -> FatosFollowup:
        return FatosFollowup(
            etapa=self.etapa,
            dono_e_ia=self.dono == DONO_IA,
            ultima_mensagem_em=self.ultima_mensagem_em,
            ultima_mensagem_do_cliente=self.ultima_mensagem_do_cliente,
            tentativas=self.tentativas,
            ultimo_followup_em=self.ultimo_followup_em,
        )


# --- portas -----------------------------------------------------------------------------------


class RepositorioConfigFollowup(Protocol):
    async def obter(self, loja_id: UUID) -> ConfigFollowup:
        """Ultima gravacao; `ConfigFollowup.padrao()` (desligada) se a loja nunca configurou."""
        ...

    async def salvar(self, loja_id: UUID, config: ConfigFollowup) -> None: ...

    async def lojas_com_followup_ligado(self) -> list[UUID]: ...


class RepositorioFollowup(Protocol):
    async def listar_candidatos(
        self, loja_id: UUID, etapas: list[Etapa], parado_antes_de: datetime
    ) -> list[CandidatoFollowup]:
        """Leads (de qualquer dono) nas `etapas` com conversa cuja ultima mensagem e anterior a
        `parado_antes_de` (corte grosseiro; a decisao fina e do dominio)."""
        ...


class RegistroTentativas(Protocol):
    async def registrar(
        self, loja_id: UUID, lead_id: UUID, *, tentativa: int, etapa: Etapa, em: datetime
    ) -> None:
        """Grava o evento `followup` com o instante `em`."""
        ...


class RegistroSaida(Protocol):
    async def registrar_saida(self, conversa_id: UUID, msg: MensagemSaida) -> None: ...


class RedatorFollowup(Protocol):
    async def redigir(
        self, candidato: CandidatoFollowup, *, tentativa: int, max_tentativas: int
    ) -> str | None:
        """Texto da mensagem, ou None se nao for possivel redigir agora."""
        ...


# --- configuracao (painel) --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntradaFollowup:
    ligado: bool
    horas_por_etapa: Mapping[str, int]
    max_tentativas: int
    intervalo_horas: int
    hora_inicio: time
    hora_fim: time
    max_dias_parado: int


class ConfigurarFollowup:
    def __init__(self, lojas: RepositorioLojas, repo: RepositorioConfigFollowup) -> None:
        self._lojas = lojas
        self._repo = repo

    async def obter(self, loja_id: UUID) -> ConfigFollowup:
        await self._loja(loja_id)
        return await self._repo.obter(loja_id)

    async def atualizar(self, loja_id: UUID, entrada: EntradaFollowup) -> ConfigFollowup:
        await self._loja(loja_id)
        config = _montar_config(entrada)
        await self._repo.salvar(loja_id, config)
        return config

    async def _loja(self, loja_id: UUID) -> None:
        if not await self._lojas.existe(loja_id):
            raise LojaNaoEncontrada(loja_id)


def _montar_config(entrada: EntradaFollowup) -> ConfigFollowup:
    etapas: dict[Etapa, int] = {}
    erros: list[ErroCampo] = []
    validas = {e.value: e for e in ETAPAS_COM_FOLLOWUP}
    for nome, horas in entrada.horas_por_etapa.items():
        etapa = validas.get(nome)
        if etapa is None:
            erros.append(ErroCampo(f"horas_por_etapa.{nome}", "Etapa sem follow-up da IA."))
        else:
            etapas[etapa] = horas
    if erros:
        raise ErrosDeValidacao(erros)
    try:
        return ConfigFollowup(
            ligado=entrada.ligado,
            horas_por_etapa=etapas,
            max_tentativas=entrada.max_tentativas,
            intervalo_horas=entrada.intervalo_horas,
            hora_inicio=entrada.hora_inicio,
            hora_fim=entrada.hora_fim,
            max_dias_parado=entrada.max_dias_parado,
        )
    except ConfigFollowupInvalida as exc:
        raise ErrosDeValidacao([ErroCampo(exc.campo, exc.mensagem)]) from exc


# --- redacao pelo LLM -------------------------------------------------------------------------


def _instrucao(tentativa: int, max_tentativas: int, horas_parado: int) -> str:
    ultima = (
        " Esta é a ÚLTIMA tentativa: deixe a porta aberta, sem insistir."
        if tentativa >= max_tentativas
        else ""
    )
    return (
        f"O cliente parou de responder há cerca de {horas_parado} h. Escreva UMA mensagem curta "
        f"(no máximo 2 frases) para retomar a conversa de onde parou, no tom da loja, usando o "
        f"que já sabemos dele. Não invente nem cite preços, valores, parcelas, descontos, prazos "
        f"ou disponibilidade. Não pressione e não repita o que já foi dito. Termine com uma "
        f"pergunta simples ou um convite para continuar. Esta é a tentativa {tentativa} de "
        f"{max_tentativas}.{ultima} Responda SOMENTE com o texto da mensagem para o cliente."
    )


def _texto_das_mensagens(historico: list[MensagemLLM]) -> list[str]:
    linhas: list[str] = []
    for m in historico:
        if m.papel not in ("user", "assistant"):
            continue
        partes = [
            b.texto if isinstance(b, BlocoTexto) else "[imagem]"
            for b in m.blocos
            if isinstance(b, BlocoTexto | BlocoImagem)
        ]
        if partes:
            quem = "Cliente" if m.papel == "user" else "Você"
            linhas.append(f"{quem}: {' '.join(partes)}")
    return linhas[-_ULTIMAS_MENSAGENS:]


class RedatorFollowupLLM:
    """Redige o follow-up com o `LLMPort` (sem ferramentas: so texto)."""

    def __init__(
        self,
        *,
        llm: LLMPort,
        config: CasosDeUsoConfig,
        atendimento: RepositorioAtendimento,
        transcricao: RepositorioTranscricao,
        agora: Callable[[], datetime],
    ) -> None:
        self._llm = llm
        self._config = config
        self._atendimento = atendimento
        self._transcricao = transcricao
        self._agora = agora

    async def redigir(
        self, candidato: CandidatoFollowup, *, tentativa: int, max_tentativas: int
    ) -> str | None:
        perfil = await self._config.obter_perfil(candidato.loja_id) or _PERFIL_PADRAO
        preco = await self._config.obter_preco(candidato.loja_id)
        estado = await self._atendimento.obter(candidato.loja_id, candidato.lead_id)
        historico = await self._transcricao.listar(candidato.conversa_id)
        parado = self._agora() - candidato.ultima_mensagem_em
        horas = max(1, round(parado.total_seconds() / 3600))
        partes = [
            "O QUE JÁ SABEMOS DO CLIENTE (só para você, não repita em lista):",
            *(f"- {i}" for i in resumo_do_que_sabemos(estado.ficha)),
            "",
            "ÚLTIMAS MENSAGENS:",
            *(_texto_das_mensagens(historico) or ["(sem histórico)"]),
            "",
            _instrucao(tentativa, max_tentativas, horas),
        ]
        try:
            resposta = await self._llm.responder(
                montar_sistema(perfil, preco),
                [MensagemLLM("user", [BlocoTexto("\n".join(partes))])],
                [],
                max_tokens=300,
            )
        except ErroLLM:
            log.exception("LLM indisponivel ao redigir follow-up (lead %s)", candidato.lead_id)
            return None
        return resposta.texto.strip() or None


# --- caso de uso ------------------------------------------------------------------------------


class EnviarFollowups:
    """Uma rodada do agendador: todas as lojas com follow-up ligado. Devolve quantos enviou."""

    def __init__(
        self,
        *,
        configs: RepositorioConfigFollowup,
        leads: RepositorioFollowup,
        redator: RedatorFollowup,
        tentativas: RegistroTentativas,
        saidas: RegistroSaida,
        transcricao: RepositorioTranscricao,
        canais: Mapping[Canal, CanalPort],
        agora: Callable[[], datetime],
        painel: PublicadorPainel | None = None,
        trava: TravaConversa | None = None,
    ) -> None:
        self._configs = configs
        self._leads = leads
        self._redator = redator
        self._tentativas = tentativas
        self._saidas = saidas
        self._transcricao = transcricao
        self._canais = canais
        self._agora = agora
        self._painel = painel or PublicadorPainelNulo()
        self._trava = trava

    async def __call__(self) -> int:
        enviados = 0
        for loja_id in await self._configs.lojas_com_followup_ligado():
            try:
                enviados += await self._loja(loja_id)
            except Exception:
                log.exception("falha no follow-up da loja %s", loja_id)
        return enviados

    async def _loja(self, loja_id: UUID) -> int:
        config = await self._configs.obter(loja_id)
        if not config.ligado or not config.horas_por_etapa:
            return 0
        agora = self._agora().astimezone(UTC)
        corte = agora - timedelta(hours=min(config.horas_por_etapa.values()))
        etapas = list(config.horas_por_etapa)
        enviados = 0
        for candidato in await self._leads.listar_candidatos(loja_id, etapas, corte):
            decisao = decidir_followup(config, candidato.fatos(), agora)
            if not decisao.enviar:
                continue
            try:
                if await self._enviar(candidato, decisao.tentativa, config, agora):
                    enviados += 1
            except Exception:
                log.exception("falha ao enviar follow-up ao lead %s", candidato.lead_id)
        return enviados

    async def _enviar(
        self, c: CandidatoFollowup, tentativa: int, config: ConfigFollowup, agora: datetime
    ) -> bool:
        canal = self._canais.get(c.canal)
        if canal is None:
            return False
        if self._trava is not None and not await self._trava.adquirir(c.conversa_id, _TRAVA_TTL_S):
            return False  # conversa em atendimento agora; tenta na proxima rodada
        try:
            texto = await self._redator.redigir(
                c, tentativa=tentativa, max_tentativas=config.max_tentativas
            )
            if not texto:
                return False
            await self._tentativas.registrar(
                c.loja_id, c.lead_id, tentativa=tentativa, etapa=c.etapa, em=agora
            )
            saida = MensagemSaida(
                loja_id=c.loja_id,
                canal=c.canal,
                destinatario=c.contato,
                tipo=TipoMensagem.TEXTO,
                texto=texto,
                midia_url=None,
            )
            await canal.enviar(saida)
            await self._saidas.registrar_saida(c.conversa_id, saida)
            await self._transcricao.acrescentar(
                c.conversa_id, [MensagemLLM("assistant", [BlocoTexto(texto)])]
            )
            await publicar_sem_falhar(
                self._painel,
                c.loja_id,
                EventoMensagemNova(
                    lead_id=c.lead_id,
                    conversa_id=c.conversa_id,
                    autor="ia",
                    direcao="saida",
                    tipo=saida.tipo.value,
                    texto=texto,
                    midia_url=None,
                    em=agora,
                ),
            )
            return True
        finally:
            if self._trava is not None:
                await self._trava.liberar(c.conversa_id)
