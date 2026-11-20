"""Prova que `uvicorn app.main:app` sobe de verdade (uvicorn e dependencia de runtime)."""

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_uvicorn_sobe_e_health_responde() -> None:
    porta = _porta_livre()
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(porta)],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        corpo = ""
        limite = time.monotonic() + 20
        while time.monotonic() < limite and proc.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{porta}/health", timeout=1) as r:
                    corpo = r.read().decode()
                    break
            except OSError:
                time.sleep(0.2)
        assert '"ok"' in corpo, corpo
    finally:
        proc.terminate()
        saida, _ = proc.communicate(timeout=10)
        assert "Traceback" not in saida, saida
