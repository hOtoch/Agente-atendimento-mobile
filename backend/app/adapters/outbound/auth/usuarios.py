"""Repositorio SQL de usuarios."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Loja, UsuarioRow
from app.application.auth.modelos import Usuario, normalizar_email


def _para_usuario(row: UsuarioRow, loja_nome: str) -> Usuario:
    return Usuario(
        id=row.id,
        loja_id=row.loja_id,
        loja_nome=loja_nome,
        email=row.email,
        senha_hash=row.senha_hash,
        senha_provisoria=row.senha_provisoria,
        ativo=row.ativo,
        ultimo_login_em=row.ultimo_login_em,
    )


class RepositorioUsuariosSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def _um(self, *condicoes: object) -> Usuario | None:
        consulta = (
            select(UsuarioRow, Loja.nome)
            .join(Loja, Loja.id == UsuarioRow.loja_id)
            .where(*condicoes)  # type: ignore[arg-type]
        )
        achado = (await self._s.execute(consulta)).first()
        return None if achado is None else _para_usuario(achado[0], achado[1])

    async def obter_por_email(self, email: str) -> Usuario | None:
        return await self._um(UsuarioRow.email == normalizar_email(email))

    async def obter_por_id(self, usuario_id: UUID) -> Usuario | None:
        return await self._um(UsuarioRow.id == usuario_id)

    async def criar(
        self, loja_id: UUID, email: str, senha_hash: str, *, senha_provisoria: bool
    ) -> Usuario:
        row = UsuarioRow(
            loja_id=loja_id,
            email=normalizar_email(email),
            senha_hash=senha_hash,
            senha_provisoria=senha_provisoria,
        )
        self._s.add(row)
        await self._s.flush()
        criado = await self.obter_por_id(row.id)
        assert criado is not None
        return criado

    async def atualizar_senha(
        self, usuario_id: UUID, senha_hash: str, *, senha_provisoria: bool
    ) -> None:
        await self._s.execute(
            update(UsuarioRow)
            .where(UsuarioRow.id == usuario_id)
            .values(senha_hash=senha_hash, senha_provisoria=senha_provisoria)
        )

    async def registrar_login(self, usuario_id: UUID, quando: datetime) -> None:
        await self._s.execute(
            update(UsuarioRow).where(UsuarioRow.id == usuario_id).values(ultimo_login_em=quando)
        )
