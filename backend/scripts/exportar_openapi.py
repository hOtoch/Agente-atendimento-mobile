"""Exporta o OpenAPI do backend para o cliente TypeScript.

Uso (a partir de backend/): `uv run python scripts/exportar_openapi.py [caminho]`.
Padrao: `../frontend/src/lib/api/openapi.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # roda como `python scripts/...`

from app.adapters.inbound.http.openapi import gerar_openapi  # noqa: E402
from app.main import app  # noqa: E402

PADRAO = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api" / "openapi.json"


def main(argv: list[str]) -> None:
    destino = Path(argv[1]) if len(argv) > 1 else PADRAO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(gerar_openapi(app), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI gravado em {destino}")


if __name__ == "__main__":
    main(sys.argv)
