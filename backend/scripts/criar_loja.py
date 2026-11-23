"""Cria uma loja nova e o login do dono (nao ha cadastro publico).

    cd backend
    uv run python scripts/criar_loja.py --nome "Loja X" --email dono@loja.com \
        [--senha-provisoria ...]

Cria loja e usuario (com `senha_provisoria=true`: o dono troca no primeiro acesso) numa transacao
so. Sem `--senha-provisoria`, gera uma senha aleatoria forte e a imprime UMA vez no fim; ela nunca
vai para log. Sai com codigo 1 se o e-mail ja existir (nada e criado) e 2 em dados invalidos.
Usa o banco das settings (`DATABASE_URL`) ou `--database-url`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2  # noqa: E402
from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql  # noqa: E402
from app.adapters.outbound.db.session import criar_engine, criar_session_factory  # noqa: E402
from app.application.auth.contas import (  # noqa: E402
    ContaCriada,
    CriarLojaComLogin,
    EmailJaCadastrado,
)
from app.application.config.modelos import ErrosDeValidacao  # noqa: E402
from app.infra.seed import casos_de_uso  # noqa: E402
from app.infra.settings import get_settings  # noqa: E402


async def criar(
    database_url: str, nome: str, email: str, senha_provisoria: str | None
) -> ContaCriada:
    """Loja + usuario numa transacao; se qualquer passo falhar, nada fica gravado."""
    engine = criar_engine(database_url)
    try:
        async with criar_session_factory(engine)() as session:
            try:
                caso = CriarLojaComLogin(
                    casos_de_uso(session).criar_loja,
                    RepositorioUsuariosSql(session),
                    HasherSenhaArgon2(),
                )
                conta = await caso(nome, email, senha_provisoria)
                await session.commit()
                return conta
            except BaseException:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


async def executar(argv: Sequence[str] | None = None, database_url: str | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cria a loja e o login do dono.")
    parser.add_argument("--nome", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--senha-provisoria", default=None)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)
    url = database_url or args.database_url or get_settings().database_url
    try:
        conta = await criar(url, args.nome, args.email, args.senha_provisoria)
    except EmailJaCadastrado as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except (ValueError, ErrosDeValidacao) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    print(f"Loja criada: {args.nome.strip()} ({conta.loja_id})")
    print(f"Login: {conta.usuario.email}")
    print(f"Senha provisoria: {conta.senha}")
    print("Anote agora: a senha nao sera exibida de novo. O dono troca no primeiro acesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(executar()))
