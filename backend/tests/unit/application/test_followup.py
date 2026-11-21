"""Follow-up automatico (fakes, relogio fake): quem recebe, quando, quantas vezes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from app.adapters.outbound.llm.fake import FakeLLM, RespostaRoteirizada
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria
from app.application.agente.transcricao import RepositorioTranscricaoEmMemoria
from app.application.canal import Canal, MensagemSaida
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.memoria import criar_casos_em_memoria
from app.application.config.modelos import ErrosDeValidacao, LojaNaoEncontrada
from app.application.followup import (
    CandidatoFollowup,
    ConfigurarFollowup,
    EntradaFollowup,
    EnviarFollowups,
    RedatorFollowupLLM,
)
from app.application.followup_memoria import ConfigFollowupEmMemoria, FollowupEmMemoria
from app.application.llm import BlocoTexto, ErroLLM, MensagemLLM
from app.application.painel.eventos import EventoMensagemNova
from app.application.painel.memoria import PublicadorEmMemoria
from app.domain.followup import ConfigFollowup
from app.domain.kanban import Etapa
from app.infra.seed import aplicar_dados

# sexta 2026-11-20, 12:00 em Sao Paulo (UTC-3)
MEIO_DIA = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


class RelogioFalso:
    def __init__(self, agora: datetime = MEIO_DIA) -> None:
        self.t = agora

    def __call__(self) -> datetime:
        return self.t

    def avancar(self, **kw: float) -> None:
        self.t += timedelta(**kw)


class RedatorFixo:
    def __init__(self, texto: str | None = "Oi! Ainda quer o iPhone 16?") -> None:
        self.texto = texto
        self.chamadas: list[tuple[CandidatoFollowup, int, int]] = []

    async def redigir(
        self, candidato: CandidatoFollowup, *, tentativa: int, max_tentativas: int
    ) -> str | None:
        self.chamadas.append((candidato, tentativa, max_tentativas))
        return self.texto


class CanalFalso:
    def __init__(self) -> None:
        self.enviadas: list[MensagemSaida] = []

    async def enviar(self, msg: MensagemSaida) -> None:
        self.enviadas.append(msg)


class TravaFalsa:
    def __init__(self, ocupadas: set[UUID] | None = None) -> None:
        self.ocupadas = ocupadas or set()
        self.liberadas: list[UUID] = []

    async def adquirir(self, conversa_id: UUID, ttl_s: float) -> bool:
        return conversa_id not in self.ocupadas

    async def liberar(self, conversa_id: UUID) -> None:
        self.liberadas.append(conversa_id)


@dataclass
class Cenario:
    relogio: RelogioFalso
    configs: ConfigFollowupEmMemoria
    repo: FollowupEmMemoria
    redator: RedatorFixo
    canal: CanalFalso
    painel: PublicadorEmMemoria
    transcricao: RepositorioTranscricaoEmMemoria
    caso: EnviarFollowups
    loja_id: UUID = field(default_factory=uuid4)

    async def configurar(self, **campos: object) -> None:
        base: dict[str, object] = {
            "ligado": True,
            "horas_por_etapa": {Etapa.INTERESSE_QUALIFICADO: 2},
            "max_tentativas": 2,
            "intervalo_horas": 24,
            "hora_inicio": time(9, 0),
            "hora_fim": time(18, 0),
        }
        base.update(campos)
        await self.configs.salvar(self.loja_id, ConfigFollowup(**base))  # type: ignore[arg-type]

    def lead(
        self,
        *,
        etapa: Etapa = Etapa.INTERESSE_QUALIFICADO,
        parado_h: float = 3,
        dono: str = "ia",
        autor_ultima: str = "ia",
    ) -> UUID:
        lead_id = uuid4()
        self.repo.adicionar_lead(
            loja_id=self.loja_id, lead_id=lead_id, conversa_id=uuid4(), etapa=etapa, dono=dono
        )
        self.repo.mensagem(lead_id, "cliente", self.relogio() - timedelta(hours=parado_h + 1))
        self.repo.mensagem(lead_id, autor_ultima, self.relogio() - timedelta(hours=parado_h))
        return lead_id


def montar(trava: TravaFalsa | None = None, redator: RedatorFixo | None = None) -> Cenario:
    relogio = RelogioFalso()
    configs = ConfigFollowupEmMemoria()
    repo = FollowupEmMemoria(relogio)
    redator = redator or RedatorFixo()
    canal = CanalFalso()
    painel = PublicadorEmMemoria()
    transcricao = RepositorioTranscricaoEmMemoria()
    caso = EnviarFollowups(
        configs=configs,
        leads=repo,
        redator=redator,
        tentativas=repo,
        saidas=repo,
        transcricao=transcricao,
        canais={Canal.WEBCHAT: canal},
        agora=relogio,
        painel=painel,
        trava=trava,
    )
    c = Cenario(relogio, configs, repo, redator, canal, painel, transcricao, caso)
    return c


async def test_lead_parado_recebe_um_followup_e_nao_recebe_outro_antes_do_intervalo() -> None:
    c = montar()
    await c.configurar()
    lead = c.lead(parado_h=3)

    assert await c.caso() == 1
    assert [m.texto for m in c.canal.enviadas] == ["Oi! Ainda quer o iPhone 16?"]
    assert c.canal.enviadas[0].destinatario == "contato-1"

    # rodadas seguintes (a cada 5 min, depois de 2h30...) ainda dentro do intervalo de 24h
    for _ in range(40):
        c.relogio.avancar(minutes=5)
        assert await c.caso() == 0
    c.relogio.avancar(hours=19)
    assert await c.caso() == 0
    assert len(c.canal.enviadas) == 1
    assert len(c.repo.followups_enviados(lead)) == 1


async def test_segunda_tentativa_depois_do_intervalo_e_para_no_maximo() -> None:
    c = montar()
    await c.configurar(max_tentativas=2, intervalo_horas=24)
    c.lead(parado_h=3)
    assert await c.caso() == 1
    c.relogio.avancar(hours=24)  # 12:00 de sabado (ainda e dia util da loja: 9h-18h)
    assert await c.caso() == 1
    assert [t for _, t, _ in c.redator.chamadas] == [1, 2]
    c.relogio.avancar(hours=48)
    assert await c.caso() == 0  # maximo de 2 atingido
    assert len(c.canal.enviadas) == 2


async def test_cliente_que_responde_reinicia_o_ciclo() -> None:
    c = montar()
    await c.configurar(max_tentativas=1)
    lead = c.lead(parado_h=3)
    assert await c.caso() == 1
    c.relogio.avancar(hours=21)  # sabado 09:00
    assert await c.caso() == 0  # maximo atingido
    # o cliente volta, a IA responde e ele some de novo
    c.repo.mensagem(lead, "cliente", c.relogio())
    c.repo.mensagem(lead, "ia", c.relogio() + timedelta(seconds=30))
    c.relogio.avancar(hours=3)
    assert await c.caso() == 1
    assert len(c.canal.enviadas) == 2


async def test_fora_do_horario_comercial_espera_e_envia_quando_abre() -> None:
    c = montar()
    await c.configurar()
    c.relogio.t = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)  # 18:30 em Sao Paulo
    c.lead(parado_h=5)
    assert await c.caso() == 0
    assert c.canal.enviadas == []
    c.relogio.t = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)  # 09:00 do dia seguinte
    assert await c.caso() == 1


async def test_dono_vendedor_nao_recebe_followup_da_ia() -> None:
    c = montar()
    await c.configurar(horas_por_etapa={Etapa.INTERESSE_QUALIFICADO: 2})
    lead = c.lead(dono="vendedor")
    assert await c.caso() == 0
    assert c.canal.enviadas == []
    assert c.redator.chamadas == []  # nem gasta LLM
    # devolveu para a IA: volta a valer
    c.repo.definir_dono(lead, "ia")
    assert await c.caso() == 1


async def test_respeita_o_tempo_configurado_por_etapa() -> None:
    c = montar()
    await c.configurar(
        horas_por_etapa={Etapa.INTERESSE_QUALIFICADO: 2, Etapa.INTERESSE_IDENTIFICADO: 24}
    )
    qualificado = c.lead(etapa=Etapa.INTERESSE_QUALIFICADO, parado_h=3)
    identificado = c.lead(etapa=Etapa.INTERESSE_IDENTIFICADO, parado_h=3)
    novo = c.lead(etapa=Etapa.NOVO_CONTATO, parado_h=48)
    assert await c.caso() == 1
    assert c.repo.followups_enviados(qualificado)
    assert not c.repo.followups_enviados(identificado)
    assert not c.repo.followups_enviados(novo)


async def test_loja_com_followup_desligado_nao_envia() -> None:
    c = montar()
    await c.configurar(ligado=False)
    c.lead()
    assert await c.caso() == 0


async def test_so_atende_lojas_com_followup_ligado() -> None:
    c = montar()
    await c.configurar()
    c.lead()
    outra = uuid4()
    c.repo.adicionar_lead(
        loja_id=outra, lead_id=uuid4(), conversa_id=uuid4(), etapa=Etapa.INTERESSE_QUALIFICADO
    )
    assert await c.caso() == 1


async def test_ultima_mensagem_do_cliente_nao_gera_followup() -> None:
    c = montar()
    await c.configurar()
    c.lead(autor_ultima="cliente")
    assert await c.caso() == 0


async def test_conversa_em_atendimento_pula_a_rodada() -> None:
    trava = TravaFalsa()
    c = montar(trava=trava)
    await c.configurar()
    lead = c.lead()
    conversa = c.repo._leads[lead].conversa_id
    trava.ocupadas.add(conversa)
    assert await c.caso() == 0
    trava.ocupadas.clear()
    assert await c.caso() == 1
    assert trava.liberadas == [conversa]


async def test_sem_texto_do_redator_nao_envia_nem_consome_tentativa() -> None:
    c = montar(redator=RedatorFixo(texto=None))
    await c.configurar()
    lead = c.lead()
    assert await c.caso() == 0
    assert c.repo.followups_enviados(lead) == []
    c.redator.texto = "Oi!"
    assert await c.caso() == 1


async def test_falha_em_um_lead_nao_para_os_outros() -> None:
    c = montar()
    await c.configurar()
    ruim = c.lead()
    c.lead()

    original = c.canal.enviar
    primeira = True

    async def enviar(msg: MensagemSaida) -> None:
        nonlocal primeira
        if primeira:
            primeira = False
            raise RuntimeError("canal fora")
        await original(msg)

    c.canal.enviar = enviar  # type: ignore[method-assign]
    assert await c.caso() == 1
    assert len(c.canal.enviadas) == 1
    assert ruim in c.repo._leads


async def test_envio_publica_no_painel_e_grava_na_transcricao() -> None:
    c = montar()
    await c.configurar()
    lead = c.lead()
    await c.caso()
    eventos = [e for _, e in c.painel.publicados if isinstance(e, EventoMensagemNova)]
    assert len(eventos) == 1
    assert eventos[0].lead_id == lead
    assert (eventos[0].autor, eventos[0].direcao) == ("ia", "saida")
    conversa = c.repo._leads[lead].conversa_id
    historico = await c.transcricao.listar(conversa)
    assert historico == [MensagemLLM("assistant", [BlocoTexto("Oi! Ainda quer o iPhone 16?")])]
    assert c.repo.saidas[0][0] == conversa


# --- redator (LLM falso) ---------------------------------------------------------------------


async def _redator(llm: FakeLLM) -> tuple[RedatorFollowupLLM, CandidatoFollowup]:
    casos: CasosDeUsoConfig = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Loja Teste")
    await aplicar_dados(casos, loja_id)
    transcricao = RepositorioTranscricaoEmMemoria()
    conversa_id = uuid4()
    await transcricao.acrescentar(
        conversa_id,
        [
            MensagemLLM("user", [BlocoTexto("quero um iPhone 16 128GB")]),
            MensagemLLM("system", [BlocoTexto("ESTADO interno")]),
            MensagemLLM("assistant", [BlocoTexto("Temos sim! Qual cor prefere?")]),
        ],
    )
    candidato = CandidatoFollowup(
        loja_id=loja_id,
        lead_id=uuid4(),
        conversa_id=conversa_id,
        canal=Canal.WEBCHAT,
        contato="x",
        etapa=Etapa.INTERESSE_QUALIFICADO,
        dono="ia",
        ultima_mensagem_em=MEIO_DIA - timedelta(hours=3),
        ultima_mensagem_do_cliente=False,
        tentativas=0,
        ultimo_followup_em=None,
    )
    redator = RedatorFollowupLLM(
        llm=llm,
        config=casos,
        atendimento=RepositorioAtendimentoEmMemoria(),
        transcricao=transcricao,
        agora=lambda: MEIO_DIA,
    )
    return redator, candidato


async def test_redator_usa_contexto_sem_ferramentas_e_devolve_o_texto() -> None:
    llm = FakeLLM([RespostaRoteirizada(texto="  Oi! Ainda posso te ajudar com o iPhone?  ")])
    redator, cand = await _redator(llm)
    texto = await redator.redigir(cand, tentativa=2, max_tentativas=2)
    assert texto == "Oi! Ainda posso te ajudar com o iPhone?"
    chamada = llm.chamadas[0]
    assert chamada.ferramentas == []
    assert len(chamada.mensagens) == 1 and chamada.mensagens[0].papel == "user"
    prompt = " ".join(b.texto for b in chamada.mensagens[0].blocos if isinstance(b, BlocoTexto))
    assert "Cliente: quero um iPhone 16 128GB" in prompt
    assert "Você: Temos sim! Qual cor prefere?" in prompt
    assert "ESTADO interno" not in prompt
    assert "ÚLTIMA tentativa" in prompt
    assert "3 h" in prompt


async def test_redator_devolve_none_se_o_llm_falha_ou_responde_vazio() -> None:
    redator, cand = await _redator(FakeLLM([RespostaRoteirizada(erro=ErroLLM("fora"))]))
    assert await redator.redigir(cand, tentativa=1, max_tentativas=2) is None
    redator2, cand2 = await _redator(FakeLLM([RespostaRoteirizada(texto="   ")]))
    assert await redator2.redigir(cand2, tentativa=1, max_tentativas=2) is None


# --- configuracao ----------------------------------------------------------------------------


async def test_configurar_followup_valida_e_persiste() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("L")
    configs = ConfigFollowupEmMemoria()
    cfg = ConfigurarFollowup(casos.lojas, configs)

    assert (await cfg.obter(loja_id)).ligado is False
    entrada = EntradaFollowup(
        ligado=True,
        horas_por_etapa={"interesse_qualificado": 3},
        max_tentativas=3,
        intervalo_horas=12,
        hora_inicio=time(8, 0),
        hora_fim=time(19, 0),
        max_dias_parado=5,
    )
    salvo = await cfg.atualizar(loja_id, entrada)
    assert salvo.horas_por_etapa == {Etapa.INTERESSE_QUALIFICADO: 3}
    assert await cfg.obter(loja_id) == salvo
    assert await configs.lojas_com_followup_ligado() == [loja_id]


@pytest.mark.parametrize(
    ("campos", "caminho"),
    [
        ({"max_tentativas": 0}, "max_tentativas"),
        ({"horas_por_etapa": {"venda_fechada": 2}}, "horas_por_etapa.venda_fechada"),
        ({"horas_por_etapa": {"interesse_qualificado": 0}}, "horas_por_etapa"),
        ({"hora_inicio": time(20, 0)}, "hora_inicio"),
    ],
)
async def test_configurar_followup_recusa_valores_invalidos(
    campos: dict[str, object], caminho: str
) -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("L")
    base: dict[str, object] = {
        "ligado": True,
        "horas_por_etapa": {"interesse_qualificado": 2},
        "max_tentativas": 2,
        "intervalo_horas": 24,
        "hora_inicio": time(9, 0),
        "hora_fim": time(18, 0),
        "max_dias_parado": 7,
    }
    base.update(campos)
    with pytest.raises(ErrosDeValidacao) as exc:
        await ConfigurarFollowup(casos.lojas, ConfigFollowupEmMemoria()).atualizar(
            loja_id,
            EntradaFollowup(**base),  # type: ignore[arg-type]
        )
    assert exc.value.erros[0].caminho == caminho


async def test_configurar_followup_de_loja_inexistente() -> None:
    casos = criar_casos_em_memoria()
    with pytest.raises(LojaNaoEncontrada):
        await ConfigurarFollowup(casos.lojas, ConfigFollowupEmMemoria()).obter(uuid4())
