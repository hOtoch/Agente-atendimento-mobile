import random
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TOKEN = "token-teste"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class SleepFalso:
    """Substitui asyncio.sleep: registra as esperas sem dormir de verdade."""

    def __init__(self) -> None:
        self.chamadas: list[float] = []

    async def __call__(self, segundos: float) -> None:
        self.chamadas.append(segundos)


@pytest.fixture
def sleep_falso() -> SleepFalso:
    return SleepFalso()


@pytest.fixture
def fazer_client(sleep_falso: SleepFalso) -> Callable[..., TestClient]:
    def _fazer(**overrides: float | int | None) -> TestClient:
        settings = Settings(token=TOKEN, **overrides)  # type: ignore[arg-type]
        app = create_app(settings, sleep=sleep_falso, rng=random.Random(settings.seed))
        return TestClient(app)

    return _fazer


@pytest.fixture
def client(fazer_client: Callable[..., TestClient]) -> TestClient:
    return fazer_client()
