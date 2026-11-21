"""Evolution falsa para o teste de carga: aceita qualquer envio e registra quando chegou.

    python3 infra/k6/stub_evolution.py --porta 8199 --log infra/k6/saida/stub.jsonl

So biblioteca padrao. Cada POST vira uma linha JSONL `{"t": <epoch>, "rota": ..., "numero": ...}`
(usada para medir a latencia ate a resposta ao cliente) e recebe `{"key": {"id": "<unico>"}}`,
como a Evolution devolve ao enviar texto. Nunca fala com o WhatsApp.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def criar_servidor(porta: int, arquivo_log: Path | None) -> ThreadingHTTPServer:
    trava = threading.Lock()
    log = arquivo_log.open("a", encoding="utf-8", buffering=1) if arquivo_log else None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _responder(self, corpo: dict[str, object]) -> None:
            dados = json.dumps(corpo).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_POST(self) -> None:  # noqa: N802
            tamanho = int(self.headers.get("Content-Length") or 0)
            bruto = self.rfile.read(tamanho) if tamanho else b""
            try:
                numero = json.loads(bruto).get("number")
            except (ValueError, AttributeError):
                numero = None
            if log is not None:
                linha = json.dumps({"t": time.time(), "rota": self.path, "numero": numero})
                with trava:
                    log.write(linha + "\n")
            self._responder({"key": {"id": f"STUB{uuid.uuid4().hex[:20]}"}})

        def do_GET(self) -> None:  # noqa: N802
            self._responder({"status": 200, "stub": True})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    servidor.daemon_threads = True
    return servidor


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--porta", type=int, default=8199)
    p.add_argument("--log", type=Path, default=None)
    a = p.parse_args()
    criar_servidor(a.porta, a.log).serve_forever()


if __name__ == "__main__":
    main()
