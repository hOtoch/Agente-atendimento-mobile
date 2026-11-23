"""Dados SINTETICOS de demonstracao para o painel de desempenho da IA (sem chamar o LLM).

    cd backend
    uv run python scripts/popular_metricas_demo.py --loja <uuid> --dias 30 [--seed N]
    uv run python scripts/popular_metricas_demo.py --loja <uuid> --remover

Cria, para cada dia do periodo (terminando hoje, fuso America/Sao_Paulo), leads, conversas,
mensagens e eventos (`llm_uso` com tokens e latencias, `ferramenta`, `erro_llm`,
`limite_iteracoes`, `resposta_descartada`, `etapa_mudou`, `dono_mudou`, `handoff_resumo`) com
volume que varia por dia da semana e por horario (picos no fim da manha e a noite; domingo
fraco). Tudo e INVENTADO: nomes, telefones, modelos e valores.

Marcacao (sem mudar o schema): todo lead criado tem o telefone `demo:NNNNNN` (prefixo que nunca e
um telefone real) e todo evento criado tem `payload.demo = true`. Conversas e mensagens nascem
presas a esses leads. `--remover` apaga so isso (eventos pela marca, leads pelo prefixo; o
CASCADE leva conversas e mensagens) e nao toca no resto da loja.

Idempotente e deterministico: rodar de novo remove o que o script criou e recria; o mesmo
`--seed` (padrao 2026) gera sempre os mesmos dados. Para o painel mostrar tambem a comparacao
com o periodo anterior, use `--dias 60`.

Seguranca: exige `--loja`; usa o banco das settings (`DATABASE_URL`) ou `--database-url`; recusa
qualquer banco com cara de teste (porta 5433 ou nome `teste*`) fora de `--permitir-banco-de-teste`
(flag so da suite de testes). Nao chama LLM, STT, TTS nem ERP.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import sys
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.adapters.outbound.db.models import (  # noqa: E402
    Conversa,
    Evento,
    Lead,
    Loja,
    Mensagem,
    Vendedor,
)
from app.adapters.outbound.db.session import criar_engine, criar_session_factory  # noqa: E402
from app.domain.metricas import FUSO  # noqa: E402
from app.infra.settings import get_settings  # noqa: E402

PREFIXO_TELEFONE = "demo:"
DIAS_PADRAO = 30
SEED_PADRAO = 2026

_PORTA_DO_BANCO_DE_TESTE = 5433
_BASE_LEADS_POR_DIA = 12
_FATOR_DIA_SEMANA = {0: 1.0, 1: 1.05, 2: 1.1, 3: 1.05, 4: 1.25, 5: 0.95, 6: 0.4}
# Peso de cada hora local (0-23) para o primeiro contato: picos 11-12h e 19-21h.
_PESO_HORA = (
    0.1, 0.05, 0.03, 0.03, 0.05, 0.1, 0.3, 0.6, 1.5, 2.5, 3.5, 5.0,
    5.5, 3.5, 3.0, 3.0, 3.2, 3.5, 4.5, 6.0, 6.5, 5.0, 2.5, 1.0,
)  # fmt: skip

_ETAPAS = ("novo_contato", "interesse_identificado", "interesse_qualificado", "com_o_vendedor")
_PESO_ETAPA_FINAL = {
    "novo_contato": 22,
    "interesse_identificado": 24,
    "interesse_qualificado": 20,
    "com_o_vendedor": 22,
    "venda_fechada": 12,
}
_RODADAS = {
    "novo_contato": (1, 2),
    "interesse_identificado": (3, 5),
    "interesse_qualificado": (5, 9),
    "com_o_vendedor": (6, 11),
    "venda_fechada": (8, 13),
}
# Motivo do handoff por etapa final: (motivo, peso). `None` = sem handoff.
_MOTIVOS = {
    "com_o_vendedor": (
        ("pedido", 55),
        ("acordo_fechado", 25),
        ("falha_llm", 12),
        ("outros", 8),
    ),
    "venda_fechada": (("acordo_fechado", 85), ("pedido", 15)),
}
_TEXTO_MOTIVO = {
    "pedido": "cliente pediu para falar com um atendente",
    "outros": "cliente quer avaliar o aparelho de troca na loja",
    "acordo_fechado": "acordo_fechado",
    "falha_llm": "falha_llm",
}

# (nome exibido, preco no Pix, peso de procura)
_DESEJADOS: tuple[tuple[str, Decimal, int], ...] = (
    ("iPhone 17 256GB", Decimal("6299"), 14),
    ("iPhone 17 Pro 256GB", Decimal("8999"), 8),
    ("iPhone 16 128GB", Decimal("4399"), 12),
    ("iPhone 16 Pro 256GB", Decimal("6799"), 6),
    ("iPhone 15 128GB", Decimal("3699"), 10),
    ("iPhone 15 Pro 128GB", Decimal("5199"), 4),
    ("iPhone 14 128GB", Decimal("3099"), 8),
    ("iPhone 13 128GB", Decimal("2499"), 7),
    ("Galaxy S24 256GB", Decimal("3799"), 6),
    ("Galaxy S25 256GB", Decimal("4599"), 4),
    ("Galaxy A55 128GB", Decimal("1799"), 5),
    ("Redmi Note 13 256GB", Decimal("1399"), 6),
    ("Poco X6 Pro 256GB", Decimal("2099"), 3),
    ("Moto G84 256GB", Decimal("1199"), 3),
)
_TROCAS: tuple[tuple[str, Decimal], ...] = (
    ("iPhone 11 64GB", Decimal("900")),
    ("iPhone 12 64GB", Decimal("1300")),
    ("iPhone 13 128GB", Decimal("1900")),
    ("iPhone 14 128GB", Decimal("2400")),
    ("Galaxy S22 128GB", Decimal("1500")),
    ("Galaxy S23 256GB", Decimal("2100")),
    ("Redmi Note 11 128GB", Decimal("450")),
)
# (rotulo, parcelas, taxa em %)
_FORMAS: tuple[tuple[str, int, Decimal], ...] = (
    ("Pix", 1, Decimal(0)),
    ("Cartão de crédito em 12x Mastercard", 12, Decimal("10.54")),
    ("Cartão de crédito em 10x Visa", 10, Decimal("9.20")),
    ("Cartão de crédito em 6x Mastercard", 6, Decimal("6.10")),
)
_NOMES = (
    "Ana", "Bruno", "Carlos", "Daniela", "Eduardo", "Fernanda", "Gustavo", "Helena", "Igor",
    "Julia", "Kaio", "Larissa", "Marcos", "Natalia", "Otavio", "Patricia", "Rafael", "Sabrina",
    "Thiago", "Vanessa", "Wesley", "Yasmin", "Lucas", "Mariana", "Pedro", "Camila", "Diego",
    "Renata", "Felipe", "Beatriz",
)  # fmt: skip
_SOBRENOMES = (
    "Almeida", "Barros", "Cardoso", "Dantas", "Esteves", "Farias", "Gomes", "Hora", "Ibrahim",
    "Junqueira", "Klein", "Lopes", "Moraes", "Nunes", "Oliveira", "Pires", "Queiroz", "Ramos",
    "Silva", "Teixeira", "Vieira", "Xavier",
)  # fmt: skip
_FALAS_CLIENTE = (
    "Oi, boa tarde", "Quanto está o {modelo}?", "Tem {modelo} disponível?", "Aceita troca?",
    "Tenho um {troca} pra dar de entrada", "Qual a cor?", "Tem em 12x?", "Faz desconto no Pix?",
    "A bateria dele é original?", "Pode ser hoje ainda?", "Fico com ele", "Manda a chave Pix",
    "Qual o endereço da loja?", "Vocês abrem sábado?", "Tela dele está trincada", "Ok, obrigado",
)  # fmt: skip
_FALAS_IA = (
    "Oi! Tudo bem? Posso te ajudar a escolher o aparelho.",
    "Tenho sim! Me conta se vai dar algum aparelho na troca.",
    "Consigo fazer em até 12x no cartão ou à vista no Pix.",
    "Com a sua troca, o valor fica assim. Quer que eu simule as parcelas?",
    "Perfeito, vou registrar aqui e já te passo o valor final.",
    "Estamos na loja de segunda a sábado. Posso reservar para você.",
)  # fmt: skip
_FALAS_VENDEDOR = (
    "Oi, aqui é da loja! Vi sua conversa, vamos fechar?",
    "Posso te esperar hoje até as 18h.",
    "Separei o aparelho aqui pra você.",
)  # fmt: skip
_FERRAMENTAS_MEIO = (
    ("consultar_estoque", 3, 0),
    ("confirmar_item", 2, 0),
    ("registrar_usado", 2, 0),
    ("registrar_compra", 1, 0),
    ("registrar_leitura_imagem", 1, 0),
    ("calcular_proposta", 3, 3),
    ("liberar_desconto", 1, 5),
)  # (nome, peso, rodada minima)
_STATUS_ERRO_LLM = (429, 500, 503, 529)
_ENDERECO = "Rua das Flores, 100 - Centro"
_HORARIOS = "Seg a Sáb, 9h às 19h"
_PIX_CHAVE = "pix@lojademo.example"
_PIX_FAVORECIDO = "Loja Demo Celulares LTDA"

_DEBOUNCE_MS = 4000
_LLM_CHAMADA_MS = 2200
_P_ERRO_FERRAMENTA = 0.04
_P_ERRO_LLM = 0.012
_P_LIMITE_ITERACOES = 0.004
_P_DESCARTADA = 0.005
_P_FILA_LONGA = 0.08


class BancoInseguro(Exception):
    """O banco indicado parece ser o de teste e o script nao esta em modo de teste."""


class LojaNaoEncontrada(Exception):
    def __init__(self, loja_id: uuid.UUID) -> None:
        super().__init__(f"Loja não encontrada: {loja_id}")
        self.loja_id = loja_id


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que foi criado (ou removido): quantidades por tabela e eventos por tipo."""

    leads: int = 0
    conversas: int = 0
    mensagens: int = 0
    eventos: int = 0
    eventos_por_tipo: dict[str, int] = field(default_factory=dict)


def verificar_banco(database_url: str, *, permitir_teste: bool) -> None:
    """Recusa o banco de teste (porta 5433 ou nome `teste*`) fora do modo de teste."""
    if permitir_teste:
        return
    url = make_url(database_url)
    porta_teste = make_url(get_settings().test_database_url).port or _PORTA_DO_BANCO_DE_TESTE
    nome = (url.database or "").lower()
    if url.port in (porta_teste, _PORTA_DO_BANCO_DE_TESTE) or nome.startswith("teste"):
        raise BancoInseguro(
            f"Recusado: {url.host}:{url.port}/{url.database} parece ser o banco de teste. "
            "Aponte para o banco de desenvolvimento (DATABASE_URL)."
        )


# --- geracao ----------------------------------------------------------------------------------


def _dinheiro(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class _Lead:
    lead: Lead
    conversa: Conversa
    t: datetime
    etapa: str = "novo_contato"
    dono: str = "ia"
    vendedor_id: uuid.UUID | None = None
    desejado: tuple[str, Decimal, int] = _DESEJADOS[0]
    troca: tuple[str, Decimal] | None = None
    falas_cliente: list[str] = field(default_factory=list)


class _Gerador:
    def __init__(
        self,
        loja_id: uuid.UUID,
        *,
        seed: int,
        modelo: str,
        agora: datetime,
        vendedores: Sequence[uuid.UUID],
    ) -> None:
        self.loja_id = loja_id
        self.rng = random.Random(f"{seed}:{loja_id}")
        self.modelo = modelo
        self.agora = agora
        self.vendedores = list(vendedores)
        self.fator_modelo = 0.45 if "haiku" in modelo.lower() else 1.0
        self.leads: list[Lead] = []
        self.conversas: list[Conversa] = []
        self.mensagens: list[Mensagem] = []
        self.eventos: list[Evento] = []
        self._seq = 0

    # --- utilitarios ---

    def _id(self) -> uuid.UUID:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4)

    def _escolher(self, opcoes: Sequence[Any], pesos: Sequence[float]) -> Any:
        return self.rng.choices(opcoes, weights=pesos, k=1)[0]

    def _cabe(self, t: datetime) -> bool:
        return t <= self.agora - timedelta(seconds=30)

    def _ev(self, ld: _Lead | None, tipo: str, quando: datetime, payload: dict[str, Any]) -> None:
        self.eventos.append(
            Evento(
                id=self._id(),
                loja_id=self.loja_id,
                lead_id=None if ld is None else ld.lead.id,
                tipo=tipo,
                payload={**payload, "demo": True},
                criado_em=quando,
            )
        )

    def _msg(self, ld: _Lead, direcao: str, autor: str, texto: str, quando: datetime) -> None:
        self.mensagens.append(
            Mensagem(
                id=self._id(),
                loja_id=self.loja_id,
                conversa_id=ld.conversa.id,
                canal=ld.lead.canal,
                direcao=direcao,
                autor=autor,
                tipo="texto",
                conteudo=texto,
                criado_em=quando,
            )
        )

    # --- volume ---

    def gerar(self, dias: int) -> None:
        hoje = self.agora.date()
        for i in range(dias):
            dia = hoje - timedelta(days=dias - 1 - i)
            tendencia = 0.85 + 0.3 * (i / max(dias - 1, 1))
            n = _BASE_LEADS_POR_DIA * _FATOR_DIA_SEMANA[dia.weekday()] * tendencia
            n *= self.rng.uniform(0.75, 1.25)
            if dia == hoje:
                n *= max(0.35, self.agora.hour / 24)
            for _ in range(max(3, round(n))):
                self._lead(dia)

    def _inicio(self, dia: date) -> datetime:
        hora = self._escolher(range(24), _PESO_HORA)
        zero = datetime(dia.year, dia.month, dia.day, tzinfo=FUSO)
        inicio = zero + timedelta(
            hours=hora, minutes=self.rng.randrange(60), seconds=self.rng.randrange(60)
        )
        teto = self.agora - timedelta(minutes=5)
        if inicio > teto:  # hoje: nada no futuro
            inicio = max(zero, teto - timedelta(seconds=self.rng.randrange(3600)))
        return inicio

    # --- um lead e sua conversa ---

    def _lead(self, dia: date) -> None:
        rng = self.rng
        inicio = self._inicio(dia)
        self._seq += 1
        lead = Lead(
            id=self._id(),
            loja_id=self.loja_id,
            nome=f"{rng.choice(_NOMES)} {rng.choice(_SOBRENOMES)}",
            telefone=f"{PREFIXO_TELEFONE}{self._seq:06d}",
            canal="whatsapp" if rng.random() < 0.8 else "webchat",
            etapa="novo_contato",
            dono="ia",
            criado_em=inicio,
            atualizado_em=inicio,
        )
        conversa = Conversa(id=self._id(), loja_id=self.loja_id, lead_id=lead.id, canal=lead.canal)
        desejado = self._escolher(_DESEJADOS, [d[2] for d in _DESEJADOS])
        ld = _Lead(lead, conversa, inicio, desejado=desejado)
        if rng.random() < 0.55:
            ld.troca = rng.choice(_TROCAS)
        self.leads.append(lead)
        self.conversas.append(conversa)
        self._atender(ld)
        lead.etapa, lead.dono, lead.vendedor_id = ld.etapa, ld.dono, ld.vendedor_id
        lead.atualizado_em = ld.t

    def _etapa_final(self) -> str:
        return str(self._escolher(list(_PESO_ETAPA_FINAL), list(_PESO_ETAPA_FINAL.values())))

    def _atender(self, ld: _Lead) -> None:
        rng = self.rng
        final = self._etapa_final()
        rodadas = rng.randint(*_RODADAS[final])
        motivo: str | None = None
        if final in _MOTIVOS:
            opcoes = _MOTIVOS[final]
            motivo = self._escolher([m for m, _ in opcoes], [p for _, p in opcoes])
        for r in range(rodadas):
            if not self._cabe(ld.t + timedelta(minutes=2)):
                return
            ultima = r == rodadas - 1
            if ultima and motivo == "falha_llm":
                self._rodada_com_falha(ld)
                return
            self._rodada(ld, r, ultima, motivo)
            self._subir_etapa(ld, r, rodadas, final)
            if ultima and motivo is not None:
                self._handoff(ld, motivo)
                self._atendimento_do_vendedor(ld, motivo, final)
                return
            ld.t += self._intervalo()

    def _intervalo(self) -> timedelta:
        if self.rng.random() < 0.08:  # o cliente sumiu por um tempo
            return timedelta(minutes=self.rng.uniform(20, 240))
        return timedelta(seconds=self.rng.uniform(20, 240))

    def _subir_etapa(self, ld: _Lead, r: int, rodadas: int, final: str) -> None:
        alvo = None
        if r == 1 and final != "novo_contato":
            alvo = "interesse_identificado"
        elif r == max(2, rodadas - 2) and final not in {"novo_contato", "interesse_identificado"}:
            alvo = "interesse_qualificado"
        if alvo is not None and alvo != ld.etapa:
            self._mover(ld, alvo, ld.t + timedelta(seconds=20), "ia", "dados da ficha")

    def _mover(self, ld: _Lead, para: str, quando: datetime, ator: str, motivo: str) -> None:
        self._ev(
            ld,
            "etapa_mudou",
            quando,
            {"de": ld.etapa, "para": para, "ator": ator, "motivo": motivo},
        )
        ld.etapa = para

    # --- uma rodada do agente ---

    def _fala_cliente(self, ld: _Lead) -> str:
        modelo = ld.desejado[0]
        troca = ld.troca[0] if ld.troca else "iPhone 12"
        texto = self.rng.choice(_FALAS_CLIENTE).format(modelo=modelo, troca=troca)
        ld.falas_cliente.append(texto)
        return texto

    def _ferramentas(self, r: int, ultima: bool, motivo: str | None) -> list[str]:
        rng = self.rng
        if r == 0:
            return ["consultar_estoque"] + (["registrar_interesse"] if rng.random() < 0.5 else [])
        if ultima and motivo == "acordo_fechado":
            return ["calcular_proposta", "fechar_acordo"]
        if ultima and motivo in {"pedido", "outros"}:
            return ["chamar_vendedor"]
        pool = [(n, p) for n, p, minimo in _FERRAMENTAS_MEIO if r >= minimo]
        quantas = rng.choice((0, 1, 1, 2))
        return [self._escolher([n for n, _ in pool], [p for _, p in pool]) for _ in range(quantas)]

    def _entrada_ferramenta(self, nome: str, ld: _Lead) -> dict[str, Any]:
        if nome in {"consultar_estoque", "registrar_interesse"}:
            modelo = ld.desejado[0]
            if self.rng.random() < 0.12:  # olhou outro aparelho
                modelo = self._escolher(_DESEJADOS, [d[2] for d in _DESEJADOS])[0]
            return {"modelo": modelo}
        if nome == "registrar_usado":
            return {"modelo": ld.troca[0] if ld.troca else "iPhone 12 64GB", "bateria_pct": 82}
        if nome == "chamar_vendedor":
            return {"motivo": "cliente pediu para falar com um atendente"}
        return {}

    def _uso(self, r: int, chamadas: int) -> dict[str, int]:
        rng = self.rng
        cache_leitura = (
            0
            if r == 0
            else sum(
                min(60_000, 5_500 + 1_400 * r + rng.randint(-400, 400)) for _ in range(chamadas)
            )
        )
        cache_escrita = rng.randint(4_800, 6_200) if r == 0 else rng.randint(300, 1_100) * chamadas
        return {
            "entrada": rng.randint(250, 900) * chamadas,
            "saida": sum(rng.randint(90, 320) for _ in range(chamadas)),
            "cache_leitura": cache_leitura,
            "cache_escrita": cache_escrita,
            "chamadas": chamadas,
        }

    def _latencia_chamadas(self, chamadas: int) -> float:
        total = 0.0
        for _ in range(chamadas):
            ms = self.rng.lognormvariate(math.log(_LLM_CHAMADA_MS * self.fator_modelo), 0.35)
            if self.rng.random() < 0.06:  # cauda longa
                ms *= self.rng.uniform(2, 4)
            total += ms
        return total

    def _rodada(self, ld: _Lead, r: int, ultima: bool, motivo: str | None) -> None:
        rng = self.rng
        t0 = ld.t
        self._msg(ld, "entrada", "cliente", self._fala_cliente(ld), t0)
        if rng.random() < 0.2:  # duas mensagens seguidas, juntadas pelo debounce
            self._msg(
                ld,
                "entrada",
                "cliente",
                self._fala_cliente(ld),
                t0 + timedelta(seconds=rng.uniform(2, 6)),
            )
        ferramentas = self._ferramentas(r, ultima, motivo)
        chamadas = min(4, 1 + len(ferramentas))
        latencia_llm = self._latencia_chamadas(chamadas)
        if rng.random() < _P_ERRO_LLM:  # falhou e o modelo reserva respondeu
            self._ev(
                ld,
                "erro_llm",
                t0 + timedelta(milliseconds=_DEBOUNCE_MS + 500),
                {
                    "tipo": "LLMIndisponivel",
                    "status": rng.choice(_STATUS_ERRO_LLM),
                    "modelo": self.modelo,
                },
            )
            latencia_llm += rng.uniform(1_500, 5_000)
        latencia_ferramentas = sum(rng.uniform(40, 350) for _ in ferramentas)
        latencia_rodada = latencia_llm + latencia_ferramentas + rng.uniform(30, 200)
        fila_ms = (
            rng.uniform(1_500, 6_000) if rng.random() < _P_FILA_LONGA else rng.expovariate(1 / 400)
        )
        tempo_resposta = _DEBOUNCE_MS + fila_ms + latencia_rodada
        resposta_em = t0 + timedelta(milliseconds=tempo_resposta)
        for i, nome in enumerate(ferramentas):
            self._ferramenta(ld, nome, t0 + timedelta(milliseconds=_DEBOUNCE_MS + 300 * (i + 1)))
        if rng.random() < _P_LIMITE_ITERACOES:
            self._ev(ld, "limite_iteracoes", resposta_em, {"max_iteracoes": 6})
        uso: dict[str, Any] = {"modelo": self.modelo, **self._uso(r, chamadas)}
        uso["latencia_llm_ms"] = round(latencia_llm)
        uso["latencia_rodada_ms"] = round(latencia_rodada)
        if rng.random() < _P_DESCARTADA:  # o cliente escreveu no meio: a resposta nao sai
            self._ev(ld, "resposta_descartada", resposta_em, {"motivo": "nova_mensagem_do_cliente"})
            self._ev(ld, "llm_uso", resposta_em, uso)
            ld.t = resposta_em
            return
        uso["tempo_resposta_ms"] = round(tempo_resposta)
        self._msg(ld, "saida", "ia", rng.choice(_FALAS_IA), resposta_em)
        self._ev(ld, "llm_uso", resposta_em - timedelta(milliseconds=50), uso)
        ld.t = resposta_em

    def _ferramenta(self, ld: _Lead, nome: str, quando: datetime) -> None:
        erro = self.rng.random() < _P_ERRO_FERRAMENTA
        resumo = '{"erro": "Não consegui concluir essa consulta."}' if erro else '{"ok": true}'
        self._ev(
            ld,
            "ferramenta",
            quando,
            {
                "nome": nome,
                "entrada": self._entrada_ferramenta(nome, ld),
                "resultado_resumido": resumo,
                "erro": erro,
            },
        )

    def _rodada_com_falha(self, ld: _Lead) -> None:
        """O LLM falhou de vez: a IA avisa que vai chamar alguem e passa para o vendedor."""
        rng = self.rng
        t0 = ld.t
        self._msg(ld, "entrada", "cliente", self._fala_cliente(ld), t0)
        falha_em = t0 + timedelta(seconds=rng.uniform(20, 50))
        status = rng.choice(_STATUS_ERRO_LLM)
        self._ev(
            ld,
            "erro_llm",
            falha_em,
            {"tipo": "LLMIndisponivel", "status": status, "modelo": self.modelo},
        )
        self._ev(ld, "handoff", falha_em, {"motivo": "falha_llm", "erro": "LLMIndisponivel"})
        self._msg(
            ld, "saida", "ia", "Já chamei um atendente para te ajudar, só um instante.", falha_em
        )
        ld.t = falha_em
        self._passar_ao_vendedor(ld, "falha_llm", falha_em + timedelta(seconds=1))
        self._mover(ld, "com_o_vendedor", falha_em + timedelta(seconds=1), "ia", "handoff")

    # --- handoff ---

    def _passar_ao_vendedor(self, ld: _Lead, motivo: str, quando: datetime) -> None:
        ld.dono = "vendedor"
        ld.vendedor_id = self.rng.choice(self.vendedores) if self.vendedores else None
        self._ev(
            ld,
            "dono_mudou",
            quando,
            {
                "dono": "vendedor",
                "vendedor_id": None if ld.vendedor_id is None else str(ld.vendedor_id),
                "motivo": _TEXTO_MOTIVO[motivo],
            },
        )

    def _handoff(self, ld: _Lead, motivo: str) -> None:
        quando = ld.t + timedelta(seconds=1)
        self._passar_ao_vendedor(ld, motivo, quando)
        self._mover(ld, "com_o_vendedor", quando, "ia", "handoff")
        self._ev(
            ld, "handoff_resumo", quando + timedelta(seconds=1), self._resumo(ld, motivo, quando)
        )
        ld.t = quando + timedelta(seconds=2)

    def _resumo(self, ld: _Lead, motivo: str, quando: datetime) -> dict[str, Any]:
        rng = self.rng
        nome, pix, _ = ld.desejado
        troca_nome, troca_valor = (
            (ld.troca[0], _dinheiro(ld.troca[1] * Decimal(str(rng.uniform(0.7, 1.0)))))
            if ld.troca
            else (None, None)
        )
        com_proposta = motivo == "acordo_fechado" or rng.random() < 0.5
        forma, parcelas, taxa = rng.choice(_FORMAS)
        base = pix - (troca_valor or Decimal(0))
        total = _dinheiro(base * (1 + taxa / 100))
        acordo = None
        if motivo == "acordo_fechado":
            acordo = {
                "fechado_em": quando.isoformat(),
                "forma": forma,
                "valor_total": str(total),
                "data_prevista": (quando.date() + timedelta(days=rng.randint(0, 3))).isoformat(),
                "endereco": _ENDERECO,
                "horarios": _HORARIOS,
                "pix_chave": _PIX_CHAVE,
                "pix_favorecido": _PIX_FAVORECIDO,
            }
        return {
            "motivo": _TEXTO_MOTIVO[motivo],
            "aparelho_desejado": nome,
            "troca": troca_nome,
            "valor_troca": None if troca_valor is None else str(troca_valor),
            "proposta": f"{nome} em {parcelas}x" if com_proposta else None,
            "valor_proposta": str(total) if com_proposta else None,
            "forma_pagamento": forma if com_proposta else None,
            "data_prevista": None if acordo is None else acordo["data_prevista"],
            "pendencias": [] if com_proposta else ["forma de pagamento"],
            "observacoes": "Cliente objetivo; quer resolver hoje." if motivo != "outros" else None,
            "gerado_em": quando.isoformat(),
            "cor": None,
            "sku": None,
            "troca_condicao": None if troca_nome is None else "seminovo",
            "troca_status": "sem_troca" if troca_nome is None else "avaliada",
            "valor_aparelho": str(pix) if com_proposta else None,
            "desconto": None,
            "parcelas": parcelas if com_proposta else None,
            "valor_parcela": str(_dinheiro(total / parcelas)) if com_proposta else None,
            "ultimas_mensagens_cliente": ld.falas_cliente[-3:],
            "acordo": acordo,
        }

    def _atendimento_do_vendedor(self, ld: _Lead, motivo: str, final: str) -> None:
        """O vendedor conversa com o cliente; na venda fechada a etapa avanca."""
        rng = self.rng
        for _ in range(rng.randint(1, 4)):
            ld.t += timedelta(minutes=rng.uniform(3, 40))
            if not self._cabe(ld.t):
                return
            self._msg(ld, "saida", "vendedor", rng.choice(_FALAS_VENDEDOR), ld.t)
            ld.t += timedelta(minutes=rng.uniform(1, 10))
            if not self._cabe(ld.t):
                return
            self._msg(ld, "entrada", "cliente", self._fala_cliente(ld), ld.t)
        if final == "venda_fechada":
            ld.t += timedelta(minutes=rng.uniform(5, 90))
            if self._cabe(ld.t):
                self._mover(ld, "venda_fechada", ld.t, "vendedor", "venda registrada")


# --- banco ------------------------------------------------------------------------------------


async def _remover_na_sessao(s: AsyncSession, loja_id: uuid.UUID) -> Resumo:
    """Apaga os eventos marcados e os leads `demo:` (CASCADE leva conversas e mensagens)."""
    do_lead = Lead.loja_id == loja_id, Lead.telefone.startswith(PREFIXO_TELEFONE)
    marcado = Evento.loja_id == loja_id, Evento.payload.contains({"demo": True})
    leads_demo = select(Lead.id).where(*do_lead)
    conversas_demo = select(Conversa.id).where(Conversa.lead_id.in_(leads_demo))
    leads = (await s.execute(select(func.count()).select_from(Lead).where(*do_lead))).scalar_one()
    conversas = (
        await s.execute(
            select(func.count()).select_from(Conversa).where(Conversa.lead_id.in_(leads_demo))
        )
    ).scalar_one()
    mensagens = (
        await s.execute(
            select(func.count())
            .select_from(Mensagem)
            .where(Mensagem.conversa_id.in_(conversas_demo))
        )
    ).scalar_one()
    contagem = await s.execute(
        select(Evento.tipo, func.count()).where(*marcado).group_by(Evento.tipo)
    )
    por_tipo = {tipo: n for tipo, n in contagem.all()}
    await s.execute(delete(Evento).where(*marcado))
    await s.execute(delete(Lead).where(*do_lead))
    return Resumo(leads, conversas, mensagens, sum(por_tipo.values()), por_tipo)


async def remover(database_url: str, loja_id: uuid.UUID, *, permitir_teste: bool = False) -> Resumo:
    """Remove tudo o que o script criou na loja (e so isso)."""
    verificar_banco(database_url, permitir_teste=permitir_teste)
    engine = criar_engine(database_url)
    try:
        async with criar_session_factory(engine)() as s:
            try:
                resumo = await _remover_na_sessao(s, loja_id)
                await s.commit()
            except BaseException:
                await s.rollback()
                raise
    finally:
        await engine.dispose()
    return resumo


async def popular(
    database_url: str,
    loja_id: uuid.UUID,
    dias: int,
    *,
    seed: int = SEED_PADRAO,
    modelo: str | None = None,
    agora: datetime | None = None,
    permitir_teste: bool = False,
) -> Resumo:
    """Remove a demonstracao anterior da loja e cria `dias` dias novos, numa so transacao."""
    verificar_banco(database_url, permitir_teste=permitir_teste)
    agora = (agora or datetime.now(FUSO)).astimezone(FUSO)
    modelo = modelo or get_settings().llm_model
    engine = criar_engine(database_url)
    try:
        async with criar_session_factory(engine)() as s:
            try:
                if await s.get(Loja, loja_id) is None:
                    raise LojaNaoEncontrada(loja_id)
                await _remover_na_sessao(s, loja_id)
                vendedores = (
                    (
                        await s.execute(
                            select(Vendedor.id)
                            .where(Vendedor.loja_id == loja_id, Vendedor.ativo.is_(True))
                            .order_by(Vendedor.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                g = _Gerador(loja_id, seed=seed, modelo=modelo, agora=agora, vendedores=vendedores)
                g.gerar(dias)
                s.add_all(g.leads)
                await s.flush()
                s.add_all(g.conversas)
                await s.flush()
                s.add_all(g.mensagens)
                s.add_all(g.eventos)
                await s.flush()
                await s.commit()
            except BaseException:
                await s.rollback()
                raise
    finally:
        await engine.dispose()
    por_tipo = Counter(e.tipo for e in g.eventos)
    return Resumo(
        len(g.leads),
        len(g.conversas),
        len(g.mensagens),
        len(g.eventos),
        dict(sorted(por_tipo.items())),
    )


# --- CLI --------------------------------------------------------------------------------------


def _uuid(valor: str) -> uuid.UUID:
    try:
        return uuid.UUID(valor)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"`{valor}` não é um UUID") from exc


def _positivo(valor: str) -> int:
    try:
        n = int(valor)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"`{valor}` não é um número inteiro") from exc
    if n < 1:
        raise argparse.ArgumentTypeError("precisa ser maior que zero")
    return n


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Popula (ou remove) dados sintéticos de desempenho da IA numa loja."
    )
    p.add_argument("--loja", type=_uuid, required=True, help="UUID da loja (obrigatório).")
    p.add_argument("--dias", type=_positivo, default=DIAS_PADRAO, help="Dias até hoje (padrão 30).")
    p.add_argument("--seed", type=int, default=SEED_PADRAO, help="Semente (mesmos dados sempre).")
    p.add_argument("--modelo", default=None, help="Modelo nos eventos (padrão: LLM_MODEL).")
    p.add_argument("--remover", action="store_true", help="Só apaga o que o script criou.")
    p.add_argument("--database-url", default=None, help="URL async do Postgres (padrão: .env).")
    p.add_argument(
        "--permitir-banco-de-teste",
        action="store_true",
        help="Só para a suíte de testes: libera a trava do banco de teste.",
    )
    return p


def _imprimir(titulo: str, r: Resumo) -> None:
    print(
        f"{titulo}: {r.leads} leads, {r.conversas} conversas, {r.mensagens} mensagens, "
        f"{r.eventos} eventos."
    )
    if r.eventos_por_tipo:
        print("  eventos: " + ", ".join(f"{t}={n}" for t, n in sorted(r.eventos_por_tipo.items())))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    url = args.database_url or get_settings().database_url
    try:
        if args.remover:
            _imprimir(
                "Removido",
                asyncio.run(remover(url, args.loja, permitir_teste=args.permitir_banco_de_teste)),
            )
        else:
            resumo = asyncio.run(
                popular(
                    url,
                    args.loja,
                    args.dias,
                    seed=args.seed,
                    modelo=args.modelo,
                    permitir_teste=args.permitir_banco_de_teste,
                )
            )
            _imprimir(f"Criado ({args.dias} dias, seed {args.seed})", resumo)
    except (BancoInseguro, LojaNaoEncontrada) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
