from fastapi import FastAPI

from app import __version__
from app.adapters.inbound.health import router as health_router
from app.adapters.inbound.http.config import router as config_router
from app.adapters.inbound.http.erros import registrar_handlers
from app.adapters.inbound.http.importacao import router as importacao_router
from app.adapters.inbound.http.webchat import router as webchat_router

app = FastAPI(title="Agente de Atendimento Mobile", version=__version__)
registrar_handlers(app)
app.include_router(health_router)
app.include_router(config_router)
app.include_router(importacao_router)
app.include_router(webchat_router)
