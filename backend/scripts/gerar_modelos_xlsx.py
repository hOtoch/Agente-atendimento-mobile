"""Gera os modelos de planilha em `docs/modelos/` (rode a partir de `backend/`).

uv run python scripts/gerar_modelos_xlsx.py
"""

from pathlib import Path

from app.adapters.outbound.planilhas.modelos_xlsx import TIPOS, gerar_modelo

DESTINO = Path(__file__).resolve().parents[2] / "docs" / "modelos"


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for tipo in TIPOS:
        caminho = DESTINO / f"modelo-{tipo}.xlsx"
        caminho.write_bytes(gerar_modelo(tipo))
        print(f"gerado: {caminho}")


if __name__ == "__main__":
    main()
