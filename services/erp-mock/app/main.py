import asyncio
import random
import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from app.config import Settings
from app.repositorio import PaginaProdutos, Produto, carregar_produtos, paginar

Sleep = Callable[[float], Awaitable[None]]


def create_app(
    settings: Settings | None = None,
    *,
    sleep: Sleep = asyncio.sleep,
    rng: random.Random | None = None,
    produtos: list[Produto] | None = None,
) -> FastAPI:
    """Monta o ERP simulado. Relogio (sleep) e RNG sao injetaveis para testar sem dormir."""
    cfg = settings or Settings()
    gerador = rng or random.Random(cfg.seed)
    catalogo = produtos if produtos is not None else carregar_produtos()
    por_sku = {p.sku: p for p in catalogo}

    def exigir_token(request: Request) -> None:
        cabecalho = request.headers.get("authorization", "")
        esquema, _, credencial = cabecalho.partition(" ")
        if (
            esquema.lower() != "bearer"
            or not credencial
            or not secrets.compare_digest(credencial.encode(), cfg.token.encode())
        ):
            raise HTTPException(
                status_code=401,
                detail="token ausente ou invalido",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def simular_comportamento(_: Annotated[None, Depends(exigir_token)]) -> None:
        if cfg.latencia_ms > 0:
            await sleep(cfg.latencia_ms / 1000)
        if gerador.random() * 100 < cfg.erro_pct:
            raise HTTPException(status_code=500, detail="erro interno simulado")

    app = FastAPI(title="ERP simulado", version="0.1.0")
    protegido = APIRouter(dependencies=[Depends(simular_comportamento)])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @protegido.get("/produtos")
    def listar_produtos(
        pagina: Annotated[int, Query(ge=1)] = 1,
        tamanho: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> PaginaProdutos:
        return paginar(catalogo, pagina, tamanho)

    @protegido.get("/produtos/{sku}")
    def obter_produto(sku: str) -> Produto:
        produto = por_sku.get(sku)
        if produto is None:
            raise HTTPException(status_code=404, detail="produto nao encontrado")
        return produto

    app.include_router(protegido)
    return app


def _app_padrao() -> FastAPI:
    return create_app()


app = _app_padrao()
