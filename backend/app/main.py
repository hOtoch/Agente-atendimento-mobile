from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.adapters.inbound.health import router as health_router
from app.adapters.inbound.http.config import router as config_router
from app.adapters.inbound.http.erros import registrar_handlers
from app.adapters.inbound.http.followup import router as followup_router
from app.adapters.inbound.http.importacao import router as importacao_router
from app.adapters.inbound.http.midias import router as midias_router
from app.adapters.inbound.http.openapi import registrar_openapi
from app.adapters.inbound.http.painel import router as painel_router
from app.adapters.inbound.http.webchat import router as webchat_router
from app.adapters.inbound.http.whatsapp import router as whatsapp_router
from app.infra.settings import get_settings

app = FastAPI(title="Agente de Atendimento Mobile", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origens_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)
registrar_handlers(app)
registrar_openapi(app)
app.include_router(health_router)
app.include_router(config_router)
app.include_router(followup_router)
app.include_router(importacao_router)
app.include_router(webchat_router)
app.include_router(painel_router)
app.include_router(midias_router)
app.include_router(whatsapp_router)
