"""Conversa com o agente pelo terminal, na loja demo (tudo em memoria; sem Postgres nem Redis).

    cd backend
    uv run python scripts/conversar.py          # LLM REAL (precisa de ANTHROPIC_API_KEY; custa)
    uv run python scripts/conversar.py --fake   # LLM eco, so para testar o fio

Digite as mensagens do cliente; linha vazia ou Ctrl+D encerra. As ferramentas, o estoque e a
config da loja demo sao as reais; a conversa nao e gravada em banco.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql  # noqa: E402
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter  # noqa: E402
from app.application.agente.conversa_portas import (  # noqa: E402
    ConversasEmMemoria,
    EventosEmMemoria,
)
from app.application.agente.ferramentas import CatalogoFerramentas  # noqa: E402
from app.application.agente.processar_conversa import ProcessarConversa  # noqa: E402
from app.application.agente.repositorio import RepositorioAtendimentoEmMemoria  # noqa: E402
from app.application.agente.transcricao import RepositorioTranscricaoEmMemoria  # noqa: E402
from app.application.canal import Canal, MensagemSaida  # noqa: E402
from app.application.config.memoria import criar_casos_em_memoria  # noqa: E402
from app.application.llm import (  # noqa: E402
    BlocoTexto,
    DefinicaoFerramenta,
    LLMPort,
    MensagemLLM,
    RespostaLLM,
    UsoTokens,
)
from app.infra.composicao import hoje_brasil  # noqa: E402
from app.infra.llm import criar_llm  # noqa: E402
from app.infra.seed import aplicar_dados  # noqa: E402
from app.infra.settings import get_settings  # noqa: E402

MENSAGEM_SEM_CHAVE = (
    "ANTHROPIC_API_KEY nao configurada. Defina a chave no .env (raiz do repo) ou no ambiente "
    "para conversar com o agente real, ou use --fake para testar o fio com um LLM eco.\n"
    "Aviso: o LLM real e pago."
)


class EcoLLM:
    """LLM de mentira: repete a ultima fala do cliente (nao usa ferramentas)."""

    async def responder(
        self,
        sistema: list[str],
        mensagens: list[MensagemLLM],
        ferramentas: list[DefinicaoFerramenta],
        max_tokens: int = 1024,
    ) -> RespostaLLM:
        falas = [
            b.texto
            for m in mensagens
            if m.papel == "user"
            for b in m.blocos
            if isinstance(b, BlocoTexto)
        ]
        texto = f"eco: {falas[-1] if falas else ''}"
        return RespostaLLM(
            texto=texto,
            chamadas=[],
            mensagem_assistente=MensagemLLM("assistant", [BlocoTexto(texto)]),
            uso=UsoTokens.vazio("eco"),
            motivo_parada="end_turn",
            modelo_usado="eco",
        )


class _CanalTerminal:
    async def enviar(self, msg: MensagemSaida) -> None:
        print(f"\nagente> {msg.texto}\n")


async def conversar(llm: LLMPort, hoje: date | None = None) -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Loja Demo (terminal)")
    await aplicar_dados(casos, loja_id)
    conversas = ConversasEmMemoria()
    lead_id = uuid4()
    conversa_id = conversas.criar_conversa(
        loja_id=loja_id, lead_id=lead_id, canal=Canal.WEBCHAT, contato="terminal"
    )
    caso = ProcessarConversa(
        conversas=conversas,
        transcricao=RepositorioTranscricaoEmMemoria(),
        atendimento=RepositorioAtendimentoEmMemoria(),
        eventos=EventosEmMemoria(),
        llm=llm,
        catalogo=CatalogoFerramentas(),
        canais={Canal.WEBCHAT: _CanalTerminal()},
        config=casos,
        estoque=PlanilhaAdapter(FonteEstoqueLocalSql(casos.estoque)),
        hoje=(lambda: hoje) if hoje else hoje_brasil,
    )
    while True:
        try:
            linha = (await asyncio.to_thread(input, "voce> ")).strip()
        except EOFError:
            return
        if not linha:
            return
        conversas.adicionar_entrada(conversa_id, linha)
        await caso(conversa_id)
        print(f"[etapa: {conversas.etapa(lead_id).nome_exibicao}]")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conversa com o agente pelo terminal.")
    parser.add_argument("--fake", action="store_true", help="usa um LLM eco (sem custo)")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.fake:
        llm: LLMPort = EcoLLM()
    elif not settings.anthropic_api_key:
        print(MENSAGEM_SEM_CHAVE, file=sys.stderr)
        return 2
    else:
        llm = criar_llm(settings)
    asyncio.run(conversar(llm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
