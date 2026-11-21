"""Orquestrador da conversa: o caso de uso que o worker roda depois do debounce.

Junta as entradas novas do cliente num unico turno, injeta o estado, roda o loop de
ferramentas e envia a resposta. O CODIGO decide (ferramentas, etapa, handoff); o LLM so conversa.
A transcricao do LLM e gravada por acrescimo (ver `transcricao.py`).
"""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.application.agente.contexto import ContextoFerramentas
from app.application.agente.conversa_portas import (
    DONO_VENDEDOR,
    ConversaLead,
    EntradaConversa,
    RegistroEventos,
    RepositorioProcessamento,
)
from app.application.agente.estado import EstadoAtendimento, fatos_do_lead
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.agente.imagem import anexar_imagens
from app.application.agente.prompt import mensagem_estado, montar_sistema
from app.application.agente.repositorio import RepositorioAtendimento
from app.application.agente.transcricao import CursorEntrada, RepositorioTranscricao
from app.application.audio_entrada import FalhaTranscricao, TranscreverAudio
from app.application.canal import Canal, CanalPort, MensagemSaida, TipoMensagem
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.modelos import PerfilLoja
from app.application.estoque import EstoquePort
from app.application.handoff import CasosHandoff
from app.application.llm import (
    BlocoTexto,
    ErroLLM,
    LLMPort,
    MensagemLLM,
    ResultadoFerramenta,
    UsoTokens,
)
from app.application.midia import ArmazenamentoMidia
from app.application.painel.eventos import EventoEtapaMudou, EventoMensagemNova
from app.application.painel.publicador import (
    PublicadorPainel,
    PublicadorPainelNulo,
    publicar_sem_falhar,
)
from app.domain.kanban import Ator, atualizar_etapa
from app.domain.valores import Dinheiro

log = logging.getLogger(__name__)

MENSAGEM_ESPERA = "Só um instante, vou chamar um especialista para te ajudar 🙂"
MENSAGEM_LIMITE = "Desculpe, não consegui concluir isso agora. Pode me mandar de novo, por favor?"
MENSAGEM_PEDIR_TEXTO = (
    "Não consegui ouvir esse áudio direito 😕 Pode digitar sua mensagem, por favor?"
)
PREFIXO_AUDIO_TRANSCRITO = "[áudio do cliente, transcrito]"
_AUDIO_SEM_TRANSCRICAO = (
    "[cliente enviou um áudio, mas não foi possível transcrever; peça que ele digite a mensagem]"
)
_ERRO_FERRAMENTA = (
    "Erro interno ao executar a ferramenta. Não invente valores: avise o cliente que vai "
    "confirmar e, se persistir, chame o vendedor."
)
_TRACEBACK_MAX = 1500
_PERFIL_PADRAO = PerfilLoja("nossa loja", "simpático e objetivo", "", {}, "")
_PROVISORIOS = {
    TipoMensagem.AUDIO: "[cliente enviou um áudio]",
    TipoMensagem.IMAGEM: "[cliente enviou uma imagem]",
}


class CanalNaoConfigurado(Exception):
    """O lead usa um canal sem `CanalPort` registrado."""


def _brl(valor: Dinheiro) -> str:
    inteiro = f"{valor.valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {inteiro}"


def _texto_da_entrada(entrada: EntradaConversa) -> str:
    provisorio = _PROVISORIOS.get(entrada.tipo)
    if provisorio is None:
        return entrada.texto or ""
    return f"{provisorio} {entrada.texto}" if entrada.texto else provisorio


class ProcessarConversa:
    def __init__(
        self,
        *,
        conversas: RepositorioProcessamento,
        transcricao: RepositorioTranscricao,
        atendimento: RepositorioAtendimento,
        eventos: RegistroEventos,
        llm: LLMPort,
        catalogo: CatalogoFerramentas,
        canais: Mapping[Canal, CanalPort],
        config: CasosDeUsoConfig,
        estoque: EstoquePort,
        hoje: Callable[[], date],
        painel: PublicadorPainel | None = None,
        handoff: CasosHandoff | None = None,
        transcrever_audio: TranscreverAudio | None = None,
        max_iteracoes: int = 6,
        midia: ArmazenamentoMidia | None = None,
    ) -> None:
        self._conversas = conversas
        self._transcricao = transcricao
        self._atendimento = atendimento
        self._eventos = eventos
        self._llm = llm
        self._catalogo = catalogo
        self._canais = canais
        self._config = config
        self._estoque = estoque
        self._hoje = hoje
        self._painel = painel or PublicadorPainelNulo()
        self._handoff = handoff
        self._transcrever_audio = transcrever_audio
        self._max_iteracoes = max_iteracoes
        self._midia = midia

    async def __call__(self, conversa_id: UUID) -> None:
        conversa = await self._conversas.obter_conversa(conversa_id)
        if conversa is None:
            log.warning("conversa %s nao encontrada", conversa_id)
            return
        cursor = await self._transcricao.consumido_ate(conversa_id)
        entradas = await self._conversas.entradas_novas(conversa_id, cursor)
        if not entradas:
            return
        ate = entradas[-1].cursor
        if conversa.dono == DONO_VENDEDOR:
            await self._transcricao.marcar_consumidas(conversa_id, ate)
            return
        await _Turno(self, conversa).rodar(entradas, ate)


class _Turno:
    """Um processamento da conversa (guarda o estado mutavel do turno)."""

    def __init__(self, caso: ProcessarConversa, conversa: ConversaLead) -> None:
        self._c = caso
        self._conversa = conversa
        self._etapa = conversa.etapa
        self._estado = EstadoAtendimento()
        self._uso = UsoTokens.vazio()
        self._chamadas_llm = 0
        self._historico: list[MensagemLLM] = []

    async def _evento(self, tipo: str, payload: dict[str, Any]) -> None:
        await self._c._eventos.registrar(
            self._conversa.loja_id, self._conversa.lead_id, tipo, payload
        )

    async def rodar(self, entradas: list[EntradaConversa], ate: CursorEntrada) -> None:
        await self._conversar(entradas, ate)
        await self._passar_ao_vendedor()

    async def _passar_ao_vendedor(self) -> None:
        """Depois de responder ao cliente: se a IA pediu o vendedor (ferramenta ou falha do
        LLM), a conversa passa a "aguardando vendedor" e a IA fica em silencio."""
        c = self._c
        if c._handoff is None or not self._estado.handoff_solicitado:
            return
        motivo = self._estado.motivo_handoff or "solicitado pela IA"
        try:
            await c._handoff.chamar_vendedor(self._conversa.loja_id, self._conversa.lead_id, motivo)
        except Exception:
            log.exception("falha ao passar a conversa %s ao vendedor", self._conversa.conversa_id)

    async def _conversar(self, entradas: list[EntradaConversa], ate: CursorEntrada) -> None:
        c, conversa = self._c, self._conversa
        loja_id, lead_id = conversa.loja_id, conversa.lead_id
        self._estado = await c._atendimento.obter(loja_id, lead_id)
        perfil = await c._config.obter_perfil(loja_id) or _PERFIL_PADRAO
        config_preco = await c._config.obter_preco(loja_id)
        sistema = montar_sistema(perfil, config_preco)

        textos, so_falhas_de_audio = await self._textos_das_entradas(entradas)
        blocos_texto = [BlocoTexto(t) for t in textos]
        usuario = MensagemLLM("user", await anexar_imagens(entradas, blocos_texto, c._midia))
        if so_falhas_de_audio:
            await self._pedir_texto(usuario, ate)
            return
        liberado = self._estado.desconto.liberado
        estado_msg = MensagemLLM(
            "system",
            [
                BlocoTexto(
                    mensagem_estado(
                        self._estado.ficha,
                        hoje=c._hoje(),
                        estoque_consultado=self._estado.estoque_consultado,
                        proposta_apresentada=self._estado.proposta_apresentada,
                        desconto_liberado=_brl(liberado) if liberado > Dinheiro.zero() else None,
                        handoff_solicitado=self._estado.handoff_solicitado,
                    )
                )
            ],
        )
        antigas = await c._transcricao.listar(conversa.conversa_id)
        novas = [usuario, estado_msg]
        await c._transcricao.acrescentar(conversa.conversa_id, novas, consumido_ate=ate)
        self._historico = [*antigas, *novas]

        ctx = ContextoFerramentas(
            loja_id=loja_id, lead_id=lead_id, estoque=c._estoque, config=c._config, hoje=c._hoje()
        )
        definicoes = c._catalogo.definicoes()

        for _ in range(c._max_iteracoes):
            try:
                resposta = await c._llm.responder(sistema, self._historico, definicoes)
            except ErroLLM as exc:
                await self._falha_llm(exc)
                return
            self._chamadas_llm += 1
            self._uso = self._uso + resposta.uso
            if not resposta.chamadas:
                await self._acrescentar([resposta.mensagem_assistente])
                await self._responder(resposta.texto.strip() or MENSAGEM_LIMITE)
                return
            resultados: list[ResultadoFerramenta] = []
            for chamada in resposta.chamadas:
                resultados.append(
                    await self._executar(chamada.id, chamada.nome, chamada.entrada, ctx)
                )
            await self._acrescentar(
                [resposta.mensagem_assistente, MensagemLLM("user", list(resultados))]
            )

        await self._evento("limite_iteracoes", {"max_iteracoes": c._max_iteracoes})
        await self._acrescentar([MensagemLLM("assistant", [BlocoTexto(MENSAGEM_LIMITE)])])
        await self._responder(MENSAGEM_LIMITE)

    async def _textos_das_entradas(self, entradas: list[EntradaConversa]) -> tuple[list[str], bool]:
        """Texto de cada entrada (audio transcrito aqui) e se TODAS foram audios sem transcricao."""
        if self._c._transcrever_audio is None:
            return [_texto_da_entrada(e) for e in entradas], False
        textos: list[str] = []
        so_falhas = True
        for e in entradas:
            if e.tipo is not TipoMensagem.AUDIO:
                textos.append(_texto_da_entrada(e))
                so_falhas = False
                continue
            transcrito = await self._transcrever(e)
            if transcrito is None:
                textos.append(
                    f"{_AUDIO_SEM_TRANSCRICAO} {e.texto}" if e.texto else _AUDIO_SEM_TRANSCRICAO
                )
                so_falhas = so_falhas and not e.texto
            else:
                textos.append(f"{PREFIXO_AUDIO_TRANSCRITO} {transcrito}")
                if e.texto:
                    textos[-1] += f" {e.texto}"
                so_falhas = False
        return textos, so_falhas

    async def _transcrever(self, entrada: EntradaConversa) -> str | None:
        """Texto do audio (ja salvo ou transcrito agora e gravado na mensagem); None se falhar."""
        c = self._c
        if entrada.transcricao:
            return entrada.transcricao
        try:
            if not entrada.midia_url or c._transcrever_audio is None:
                raise FalhaTranscricao("audio sem midia")
            texto = await c._transcrever_audio(entrada.midia_url)
        except Exception as exc:  # STT/armazenamento nunca derrubam a conversa
            if isinstance(exc, FalhaTranscricao):
                log.warning("sem transcricao do audio %s: %s", entrada.id, exc)
            else:
                log.exception("erro inesperado transcrevendo o audio %s", entrada.id)
            await self._evento(
                "stt_falha", {"mensagem_id": str(entrada.id), "erro": type(exc).__name__}
            )
            return None
        await c._conversas.salvar_transcricao(entrada.id, texto)
        return texto

    async def _pedir_texto(self, usuario: MensagemLLM, ate: CursorEntrada) -> None:
        """So havia audio que nao deu para transcrever: o codigo pede que digite (sem LLM)."""
        await self._c._transcricao.acrescentar(
            self._conversa.conversa_id,
            [usuario, MensagemLLM("assistant", [BlocoTexto(MENSAGEM_PEDIR_TEXTO)])],
            consumido_ate=ate,
        )
        await self._responder(MENSAGEM_PEDIR_TEXTO)

    async def _acrescentar(self, mensagens: list[MensagemLLM]) -> None:
        await self._c._transcricao.acrescentar(self._conversa.conversa_id, mensagens)
        self._historico.extend(mensagens)

    async def _executar(
        self, id_: str, nome: str, entrada: dict[str, Any], ctx: ContextoFerramentas
    ) -> ResultadoFerramenta:
        c = self._c
        try:
            res = await c._catalogo.executar(nome, entrada, self._estado, ctx)
        except Exception:
            log.exception("ferramenta %s falhou", nome)
            await self._evento(
                "ferramenta_erro",
                {
                    "nome": nome,
                    "entrada": entrada,
                    "traceback": traceback.format_exc()[-_TRACEBACK_MAX:],
                },
            )
            return ResultadoFerramenta(id_, json.dumps({"erro": _ERRO_FERRAMENTA}), True)
        for ev in res.eventos:
            await self._evento(
                str(ev.get("tipo", "ferramenta")), {k: v for k, v in ev.items() if k != "tipo"}
            )
        if res.estado != self._estado:
            self._estado = res.estado
            await c._atendimento.salvar(
                self._conversa.loja_id, self._conversa.lead_id, self._estado
            )
        await self._recalcular_etapa()
        return ResultadoFerramenta(id_, json.dumps(res.conteudo, ensure_ascii=False), res.erro)

    async def _recalcular_etapa(self) -> None:
        nova, mudou = atualizar_etapa(self._etapa, fatos_do_lead(self._estado), Ator.IA)
        if mudou is None:
            return
        self._etapa = nova
        await self._c._conversas.atualizar_etapa(self._conversa.lead_id, nova)
        await self._evento(
            "etapa_mudou",
            {
                "de": mudou.de.value,
                "para": mudou.para.value,
                "ator": mudou.ator.value,
                "motivo": mudou.motivo,
            },
        )
        await publicar_sem_falhar(
            self._c._painel,
            self._conversa.loja_id,
            EventoEtapaMudou(
                lead_id=self._conversa.lead_id,
                de=mudou.de,
                para=mudou.para,
                ator=mudou.ator.value,
                motivo=mudou.motivo,
                em=datetime.now(UTC),
            ),
        )

    async def _falha_llm(self, exc: ErroLLM) -> None:
        log.error("LLM indisponivel na conversa %s: %r", self._conversa.conversa_id, exc)
        c = self._c
        self._estado = replace(self._estado, handoff_solicitado=True, motivo_handoff="falha_llm")
        await c._atendimento.salvar(self._conversa.loja_id, self._conversa.lead_id, self._estado)
        await self._evento("handoff", {"motivo": "falha_llm", "erro": type(exc).__name__})
        await self._recalcular_etapa()
        await self._acrescentar([MensagemLLM("assistant", [BlocoTexto(MENSAGEM_ESPERA)])])
        await self._responder(MENSAGEM_ESPERA)

    async def _responder(self, texto: str) -> None:
        c, conversa = self._c, self._conversa
        canal = c._canais.get(conversa.canal)
        if canal is None:
            raise CanalNaoConfigurado(conversa.canal.value)
        saida = MensagemSaida(
            loja_id=conversa.loja_id,
            canal=conversa.canal,
            destinatario=conversa.contato,
            tipo=TipoMensagem.TEXTO,
            texto=texto,
            midia_url=None,
        )
        await canal.enviar(saida)
        await c._conversas.registrar_saida(conversa.conversa_id, saida)
        await publicar_sem_falhar(
            c._painel,
            conversa.loja_id,
            EventoMensagemNova(
                lead_id=conversa.lead_id,
                conversa_id=conversa.conversa_id,
                autor="ia",
                direcao="saida",
                tipo=saida.tipo.value,
                texto=saida.texto,
                midia_url=saida.midia_url,
                em=datetime.now(UTC),
            ),
        )
        if self._chamadas_llm:
            await self._evento(
                "llm_uso",
                {
                    "modelo": self._uso.modelo,
                    "entrada": self._uso.entrada,
                    "saida": self._uso.saida,
                    "cache_leitura": self._uso.cache_leitura,
                    "cache_escrita": self._uso.cache_escrita,
                    "chamadas": self._chamadas_llm,
                },
            )


__all__ = [
    "MENSAGEM_ESPERA",
    "MENSAGEM_LIMITE",
    "MENSAGEM_PEDIR_TEXTO",
    "PREFIXO_AUDIO_TRANSCRITO",
    "CanalNaoConfigurado",
    "ProcessarConversa",
]
