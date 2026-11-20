"""Repositorios Postgres."""

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Mensagem


class MensagemRepositorio:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def inserir_se_nova(
        self,
        *,
        id: uuid.UUID,
        loja_id: uuid.UUID,
        conversa_id: uuid.UUID,
        canal: str,
        direcao: str,
        tipo: str = "texto",
        conteudo: str | None = None,
        midia_url: str | None = None,
        id_externo: str | None = None,
        autor: str | None = None,
    ) -> bool:
        """Insere a mensagem; se (canal, id_externo) ja existe, nao faz nada e devolve False.

        `autor` (cliente | ia | vendedor) padrao: `cliente` para entrada, `ia` para saida.
        """
        valores: dict[str, Any] = {
            "id": id,
            "loja_id": loja_id,
            "conversa_id": conversa_id,
            "canal": canal,
            "direcao": direcao,
            "autor": autor or ("cliente" if direcao == "entrada" else "ia"),
            "tipo": tipo,
            "conteudo": conteudo,
            "midia_url": midia_url,
            "id_externo": id_externo,
        }
        stmt = (
            insert(Mensagem)
            .values(**valores)
            .on_conflict_do_nothing(index_elements=["canal", "id_externo"])
            .returning(Mensagem.id)
        )
        resultado = await self._session.execute(stmt)
        return resultado.scalar_one_or_none() is not None
