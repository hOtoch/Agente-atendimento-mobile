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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.canal import MensagemSaida  # noqa: E402
from app.application.llm import (  # noqa: E402
    BlocoTexto,
    DefinicaoFerramenta,
    LLMPort,
    MensagemLLM,
    RespostaLLM,
    UsoTokens,
)
from app.infra.llm import criar_llm  # noqa: E402
from app.infra.settings import get_settings  # noqa: E402
from evals.ambiente import montar_ambiente  # noqa: E402

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
    amb = await montar_ambiente(llm, _CanalTerminal(), hoje, "Loja Demo (terminal)")
    while True:
        try:
            linha = (await asyncio.to_thread(input, "voce> ")).strip()
        except EOFError:
            return
        if not linha:
            return
        await amb.cliente_fala(linha)
        print(f"[etapa: {amb.conversas.etapa(amb.lead_id).nome_exibicao}]")


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
