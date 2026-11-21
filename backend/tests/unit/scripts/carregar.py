"""Carrega `scripts/custos.py` como modulo (scripts/ nao e pacote)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

BACKEND = Path(__file__).resolve().parents[3]


def carregar_custos() -> ModuleType:
    if "custos" in sys.modules:
        return sys.modules["custos"]
    spec = importlib.util.spec_from_file_location("custos", BACKEND / "scripts" / "custos.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["custos"] = modulo
    spec.loader.exec_module(modulo)
    return modulo
