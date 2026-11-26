"""Hinge Auto Swipe – lokal app med UI. Start: python app.py (åbner http://127.0.0.1:8765 i browseren).

Appen starter swipe.py som en baggrundsproces, viser loggen live og stopper den pænt via STOP-filen.
Kun lokal adgang (127.0.0.1); ingen ekstra pakker.
"""
import collections
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logic import MODES, load_state

HERE = Path(__file__).parent
PORT = int(os.environ.get("HINGE_APP_PORT", "8765"))
STOP = HERE / "STOP"

log = collections.deque(maxlen=400)
proc: subprocess.Popen | None = None
lock = threading.Lock()


def running() -> bool:
    return proc is not None and proc.poll() is None


def launch(args: list[str]) -> None:
    global proc
    STOP.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-u", str(HERE / "swipe.py"), *args], cwd=HERE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    log.append(f"── start: {' '.join(args) or '(standard)'}")

    def pump(p):
        for line in p.stdout:
            line = line.rstrip()
            if line and "DTXMessage" not in line:   # støj fra WDA-runneren
                log.append(line)
        log.append(f"── stoppet (kode {p.wait()})")

    threading.Thread(target=pump, args=(proc,), daemon=True).start()


def status() -> dict:
    return {"running": running(), "likes_today": load_state(HERE / "state.json")["likes_today"],
            "log": list(log), "modes": MODES}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self.send(200, (HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self.send(200, json.dumps(status()).encode())
        self.send(404, b"{}")

    def do_POST(self):
        # Kun samme oprindelse: en anden hjemmeside må ikke kunne starte/stoppe appen.
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send(403, b'{"error":"forbidden"}')
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        with lock:
            if self.path == "/api/start":
                if running():
                    return self.send(409, b'{"error":"k\\u00f8rer allerede"}')
                mode = body.get("mode") if body.get("mode") in MODES else "human"
                args = ["--mode", mode]
                for key in ("max", "daily", "minutes"):
                    if str(body.get(key) or "").isdigit() and int(body[key]) > 0:
                        args += [f"--{key}", str(int(body[key]))]
                launch(args)
            elif self.path == "/api/check":
                if running():
                    return self.send(409, b'{"error":"k\\u00f8rer allerede"}')
                launch(["--dry"])
            elif self.path == "/api/stop":
                STOP.touch()   # swipe.py stopper pænt ved næste tjek
                log.append("── stopper …")
            else:
                return self.send(404, b"{}")
        self.send(200, json.dumps(status()).encode())


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Hinge Auto Swipe kører på {url}  (luk dette vindue for at stoppe appen)", flush=True)
    if not os.environ.get("HINGE_APP_NO_BROWSER"):
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if running():
            STOP.touch()


if __name__ == "__main__":
    main()
