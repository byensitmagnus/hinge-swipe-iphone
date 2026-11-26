"""Hinge Auto Swipe – desktop-appen. Start: python app.py (eller den installerede app).

En lokal webserver (kun 127.0.0.1) viser brugerfladen i et app-vindue (pywebview) eller, hvis det ikke kan,
i browseren. Telefonarbejdet (swipe, forbindelsestjek, skærmaflæsning) kører i en baggrundstråd – én ad gangen.
"""
from __future__ import annotations
import asyncio
import collections
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import make_ipa
import swipe
from logic import APP_NAME, MODES, VERSION, data_dir, load_settings, load_state, run_limits, save_settings, schedule_due
from wda import device_status, reveal_developer_mode, screen_names

RES = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))   # ui.html ligger her (også i den installerede app)
DATA = data_dir()
SETTINGS, STATE, STOP = DATA / "settings.json", DATA / "state.json", DATA / "STOP"
IPA = DATA / "WebDriverAgentRunner.ipa"
PORT = int(os.environ.get("HINGE_APP_PORT", "8765"))

APP_MSG = {
    "da": {"stopping": "Stopper …", "check": "Tjekker forbindelsen …", "ipa": "Henter testappen (WebDriverAgent) …",
           "ipa_done": "Testappen er klar – træk filen ind i Sideloadly.", "inspect": "Læser navnene på skærmen …",
           "inspect_done": "Fandt {n} navne på skærmen.", "scheduled": "Planlagt kørsel starter.", "error": "Fejl: {err}"},
    "en": {"stopping": "Stopping …", "check": "Checking the connection …", "ipa": "Downloading the test app (WebDriverAgent) …",
           "ipa_done": "The test app is ready – drag the file into Sideloadly.", "inspect": "Reading the names on screen …",
           "inspect_done": "Found {n} names on screen.", "scheduled": "Scheduled run starting.", "error": "Error: {err}"},
}

log: collections.deque[str] = collections.deque(maxlen=600)
lock = threading.RLock()          # én opgave ad gangen + indstillinger skrives ikke samtidigt
task: dict = {"name": None, "thread": None}
last: dict = {"check": None, "names": [], "device": None, "device_at": 0.0, "run": None}
dev_lock = threading.Lock()
quitting = threading.Event()
ui: dict = {"window": None, "server": None}


def msg(key: str, **kw) -> str:
    lang = load_settings(SETTINGS)["lang"]
    return APP_MSG[lang][key].format(**kw)


def note(text: str) -> None:
    log.append(f"{dt.datetime.now():%H:%M:%S}  {text}")


def busy() -> str | None:
    thread = task["thread"]
    return task["name"] if thread is not None and thread.is_alive() else None


def start_task(name: str, label: str, fn, *args) -> bool:
    """Kør fn i baggrunden, hvis intet andet kører. Telefonen kan kun bruges af én ting ad gangen."""
    with lock:
        if busy():
            return False
        swipe.LANG = load_settings(SETTINGS)["lang"]   # fejlbeskeder på brugerens sprog, også før første kørsel
        STOP.unlink(missing_ok=True)
        log.append(f"── ▶ {label}")

        def wrapper():
            try:
                fn(*args)
            except Exception as e:   # vis en forståelig besked; den fulde fejl går til app.log
                note(swipe.friendly_error(e) or msg("error", err=str(e)[:200] or type(e).__name__))
                traceback.print_exc()
            finally:
                log.append("── ■")

        thread = threading.Thread(target=wrapper, name=name, daemon=True)
        task.update(name=name, thread=thread)
        thread.start()
        return True


def do_swipe(cfg: dict) -> None:
    asyncio.run(swipe.run(cfg))


def do_check(cfg: dict) -> None:
    last["check"] = None
    try:
        res = asyncio.run(swipe.run(cfg))
        last["check"] = {"ok": res["ok"], "found": res["found"], "at": dt.datetime.now().isoformat(timespec="seconds")}
    except Exception:
        last["check"] = {"ok": False, "found": None, "at": dt.datetime.now().isoformat(timespec="seconds")}
        raise


def do_ipa() -> None:
    make_ipa.build(IPA, log=note)
    note(msg("ipa_done"))


def do_inspect() -> None:
    last["names"] = asyncio.run(screen_names())
    note(msg("inspect_done", n=len(last["names"])))


def device() -> dict:
    """Enhedsstatus, højst hvert 3. sekund (selve tjekket tager ~0,2 s og starter intet på telefonen)."""
    with dev_lock:
        if time.monotonic() - last["device_at"] > 3:
            try:
                last["device"] = asyncio.run(device_status())
            except Exception as e:
                last["device"] = {"connected": False, "error": type(e).__name__}
            last["device_at"] = time.monotonic()
        return last["device"]


def status() -> dict:
    settings = load_settings(SETTINGS)
    state = load_state(STATE)
    return {
        "app": APP_NAME, "version": VERSION, "task": busy(), "running": busy() is not None,
        "today": state["date"], "likes_today": state["likes_today"], "history": state["history"],
        "log": list(log), "modes": MODES, "settings": settings,
        "limits": {m: run_limits(settings, m) for m in MODES},
        "ipa": IPA.exists(), "check": last["check"], "names": last["names"], "data_dir": str(DATA),
        "run": last["run"],   # tempo og max for den igangværende/seneste kørsel
    }


def update_settings(posted: dict) -> dict:
    """Flet de indsendte felter ind i de gemte (én niveau ned for sektioner) og gem det validerede resultat."""
    with lock:
        current = load_settings(SETTINGS)
        for key, value in posted.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict) and key != "limits":
                current[key] = {**current[key], **value}
            else:
                current[key] = value
        return save_settings(SETTINGS, current)


def reveal(path: Path) -> None:
    """Vis filen/mappen i Stifinder/Finder."""
    if sys.platform == "win32":
        if path.is_file():
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            os.startfile(path)   # noqa: S606 – fast, lokal sti
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


def scheduler() -> None:
    """Starter den planlagte kørsel (Indstillinger → Planlægning), mens appen er åben."""
    while not quitting.wait(20):
        try:
            settings = load_settings(SETTINGS)
            now = dt.datetime.now()
            if not settings["accepted_terms"] or not schedule_due(settings["schedule"], now) or busy():
                continue
            update_settings({"schedule": {"last_run": now.date().isoformat()}})
            mode = settings["schedule"]["mode"]
            note(msg("scheduled"))
            if start_task("swipe", mode, do_swipe, swipe.config(settings, mode)):
                last["run"] = {"mode": mode, "max": None}
        except Exception:   # én fejl må ikke stoppe planlægningen resten af dagen
            traceback.print_exc()


def quit_app() -> None:
    quitting.set()
    if busy():
        STOP.touch()   # swipe stopper pænt ved næste tjek
    if ui["window"] is not None:
        ui["window"].destroy()
    elif ui["server"] is not None:
        threading.Thread(target=ui["server"].shutdown, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")   # en hjemmeside må ikke vise appen i en iframe (clickjacking)
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_host(self) -> bool:
        """Mod DNS-rebinding: kun forespørgsler til 127.0.0.1/localhost på vores port."""
        if self.headers.get("Host") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return True
        self.send(403, {"error": "forbidden"})
        return False

    def do_GET(self):
        if not self.local_host():
            return
        if self.path == "/":
            return self.send(200, (RES / "ui.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self.send(200, status())
        if self.path == "/api/device":
            return self.send(200, device())
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # Kun samme oprindelse: en anden hjemmeside må ikke kunne styre appen.
        if not self.local_host():
            return
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65536:
            return self.send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send(400, {"error": "bad json"})
        handler = ROUTES.get(self.path)
        if handler is None:
            return self.send(404, {"error": "not found"})
        code, result = handler(body)
        self.send(code, result if result is not None else status())


def route_start(body: dict):
    settings = load_settings(SETTINGS)
    if not settings["accepted_terms"]:
        return 409, {"error": "terms"}
    mode = body.get("mode") if body.get("mode") in MODES else settings["mode"]
    run_max = body.get("max")
    run_max = int(run_max) if str(run_max or "").isdigit() and 0 < int(run_max) <= 1000 else None
    if not start_task("swipe", mode, do_swipe, swipe.config(settings, mode, max=run_max)):
        return 409, {"error": "busy"}
    last["run"] = {"mode": mode, "max": run_max}
    return 200, None


def route_check(_body: dict):
    settings = load_settings(SETTINGS)
    if not start_task("check", msg("check"), do_check, swipe.config(settings, None, dry=True)):
        return 409, {"error": "busy"}
    return 200, None


def route_stop(_body: dict):
    if busy():
        STOP.touch()
        note(msg("stopping"))
    return 200, None


def route_settings(body: dict):
    update_settings(body)
    return 200, None


def route_ipa(_body: dict):
    if not start_task("ipa", msg("ipa"), do_ipa):
        return 409, {"error": "busy"}
    return 200, None


def route_inspect(_body: dict):
    if not start_task("inspect", msg("inspect"), do_inspect):
        return 409, {"error": "busy"}
    return 200, None


def route_devmode(_body: dict):
    swipe.LANG = load_settings(SETTINGS)["lang"]
    try:
        asyncio.run(reveal_developer_mode())
        return 200, {"ok": True}
    except Exception as e:
        return 200, {"ok": False, "error": swipe.friendly_error(e) or str(e)[:200]}


def route_open(body: dict):
    target = {"data": DATA, "ipa": IPA}.get(body.get("what"))
    if target is None or not target.exists():
        return 404, {"error": "not found"}
    reveal(target)
    return 200, {"ok": True}


def route_quit(_body: dict):
    threading.Timer(0.3, quit_app).start()   # svar først, luk bagefter
    return 200, {"ok": True}


ROUTES = {"/api/start": route_start, "/api/check": route_check, "/api/stop": route_stop, "/api/settings": route_settings,
          "/api/ipa": route_ipa, "/api/inspect": route_inspect, "/api/devmode": route_devmode, "/api/open": route_open,
          "/api/quit": route_quit}


class Server(ThreadingHTTPServer):
    # På Windows lader SO_REUSEADDR en app mere (eller et andet program) binde samme port. Kræv porten for os selv.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def existing_instance(port: int) -> str | None:
    """Kører appen allerede? Så åbner vi bare et vindue til den i stedet for at starte en ny."""
    url = f"http://127.0.0.1:{port}"
    no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1 må aldrig gå via en proxy
    try:
        with no_proxy.open(url + "/api/status", timeout=1) as r:
            return url if json.load(r).get("app") == APP_NAME else None
    except Exception:
        return None


def open_window(url: str) -> bool:
    """Vis appen i et rigtigt vindue (pywebview). False hvis det ikke kan lade sig gøre – så bruges browseren."""
    try:
        import webview
    except Exception:
        return False
    try:
        ui["window"] = webview.create_window(APP_NAME, url, width=1180, height=820, min_size=(820, 600))
        webview.start()   # blokerer, til vinduet lukkes
        return True
    except Exception:
        traceback.print_exc()
        ui["window"] = None
        return False


def main() -> None:
    global PORT
    url = existing_instance(PORT)
    if url:   # appen kører allerede: vis den i stedet for at starte en til
        if not open_window(url):
            webbrowser.open(url)
        return
    if sys.stdout is None or sys.stderr is None:   # vinduesudgaven har ingen konsol
        sys.stdout = sys.stderr = open(DATA / "app.log", "w", encoding="utf-8", buffering=1)
    swipe.set_sink(log.append)
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:   # porten er optaget af noget andet: tag en ledig
        server = Server(("127.0.0.1", 0), Handler)
    PORT = server.server_address[1]
    ui["server"] = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}"
    print(f"{APP_NAME} {VERSION}: {url}", flush=True)

    try:
        if os.environ.get("HINGE_APP_NO_BROWSER") or not open_window(url):
            if not os.environ.get("HINGE_APP_NO_BROWSER"):
                webbrowser.open(url)
            print("Appen kører i din browser. Luk med Afslut i appen eller Ctrl+C her.", flush=True)
            while not quitting.wait(0.5):
                pass
    except KeyboardInterrupt:
        pass
    finally:
        quitting.set()
        if busy():
            STOP.touch()
            if task["thread"] is not None:
                task["thread"].join(timeout=20)   # lad swipe stoppe pænt og rydde op på telefonen
        server.shutdown()


if __name__ == "__main__":
    main()
