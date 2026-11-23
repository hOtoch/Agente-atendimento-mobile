"""Redefine a senha de um usuario (o dono esqueceu; nao ha recuperacao por e-mail).

    cd backend
    uv run python scripts/redefinir_senha.py --email dono@loja.com

Gera uma nova senha provisoria (`senha_provisoria=true`), encerra todas as sessoes abertas do
usuario no Redis (as mesmas settings da API: `REDIS_URL`, `SESSAO_TTL_HORAS`) e imprime a senha
UMA vez no fim; ela nunca vai para log. Sai com codigo 1 se o e-mail nao existir.
Usa o banco das settings (`DATABASE_URL`) ou `--database-url`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redis.asyncio import Redis  # noqa: E402

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2  # noqa: E402
from app.adapters.outbound.auth.sessoes import SessoesRedis  # noqa: E402
from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql  # noqa: E402
from app.adapters.outbound.db.session import criar_engine, criar_session_factory  # noqa: E402
from app.application.auth.contas import RedefinirSenha, UsuarioNaoEncontrado  # noqa: E402
from app.application.auth.portas import Sessoes  # noqa: E402
from app.infra.settings import get_settings  # noqa: E402


async def redefinir(database_url: str, email: str, sessoes: Sessoes) -> str:
    """Troca a senha, marca como provisoria e derruba as sessoes; devolve a nova senha."""
    engine = criar_engine(database_url)
    try:
        async with criar_session_factory(engine)() as session:
            try:
                caso = RedefinirSenha(RepositorioUsuariosSql(session), HasherSenhaArgon2(), sessoes)
                senha = await caso(email)
                await session.commit()
                return senha
            except BaseException:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


async def executar(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redefine a senha de um usuario.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        sessoes = SessoesRedis(redis, ttl_s=settings.sessao_ttl_horas * 3600)
        senha = await redefinir(args.database_url or settings.database_url, args.email, sessoes)
    except UsuarioNaoEncontrado as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        await redis.aclose()
    print(f"Login: {args.email.strip().lower()}")
    print(f"Senha provisoria: {senha}")
    print("Anote agora: a senha nao sera exibida de novo. Sessoes abertas foram encerradas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(executar()))
