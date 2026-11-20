from fastapi import FastAPI

from app import __version__
from app.adapters.inbound.health import router as health_router

app = FastAPI(title="Agente de Atendimento Mobile", version=__version__)
app.include_router(health_router)
