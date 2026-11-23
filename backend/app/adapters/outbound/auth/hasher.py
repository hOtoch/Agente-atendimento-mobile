"""Hash de senha com argon2id (argon2-cffi, parametros padrao RFC 9106 baixo-consumo).

O argon2 gasta CPU de proposito (dezenas de ms): roda numa thread para nao congelar o
event loop, que serve tambem os streams SSE do painel e do chat.
"""

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class HasherSenhaArgon2:
    def __init__(self) -> None:
        self._ph = PasswordHasher()  # argon2id por padrao

    async def gerar(self, senha: str) -> str:
        return await to_thread.run_sync(self._ph.hash, senha)

    async def conferir(self, senha: str, hash_: str) -> bool:
        return await to_thread.run_sync(self._conferir, senha, hash_)

    def _conferir(self, senha: str, hash_: str) -> bool:
        try:
            return self._ph.verify(hash_, senha)
        except (VerificationError, InvalidHashError):
            return False
