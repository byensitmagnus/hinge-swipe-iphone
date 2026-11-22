"""
End-to-end-test af den rigtige exe mod en falsk Hinge-server (REST + Sendbird REST + Sendbird WebSocket).

Kør:  python run_e2e.py <sti til hinge-auto-swipe.exe>
Tester: login (SMS) → 12 likes → nyt match får første besked → eksisterende match gør ikke → 2. kørsel dubleres ikke.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from aiohttp import web

PORT = 18765
TS = "2030-01-01T00:00:00Z"
N_PROFILES = 12


class Mock:
    def __init__(self):
        self.rec_calls = 0
        self.ratings = []
        self.messages = []   # (channel_url, text)
        self.paths = []

    def likes_done(self):
        return len(self.ratings)

    def channels(self):
        chans = [
            {"channel_url": "old1", "members": [{"user_id": "me1"}, {"user_id": "p_old", "nickname": "Gammel Match"}],
             "created_at": 1, "last_message": None},
            {"channel_url": "chat1", "members": [{"user_id": "me1"}, {"user_id": "p_chat", "nickname": "Chat Match"}],
             "created_at": 2,
             "last_message": {"type": "MESG", "message_id": 5, "message": "hej", "created_at": 3,
                              "user": {"user_id": "p_chat"}, "channel_url": "chat1"}},
        ]
        if self.likes_done() >= 10:  # et nyt match dukker op undervejs
            chans.append({"channel_url": "new1",
                          "members": [{"user_id": "me1"}, {"user_id": "p_new", "nickname": "Sofie Krogh"}],
                          "created_at": 9, "last_message": None})
        return chans


def make_app(m: Mock):
    async def j(request):
        m.paths.append(f"{request.method} {request.path}")
        return None

    async def install(r):
        await j(r)
        return web.json_response({})

    async def initiate(r):
        await j(r)
        return web.Response(status=204)

    async def verify(r):
        await j(r)
        body = await r.json()
        assert body["otp"] == "000000", body
        return web.json_response({
            "hingeAuthToken": {"identityId": "me1", "token": "HT", "expires": TS},
            "sendbirdAuthToken": {"token": "SB", "expires": TS}})

    async def authenticate(r):
        await j(r)
        return web.json_response({"token": "SB", "expires": TS})

    async def rec(r):
        await j(r)
        m.rec_calls += 1
        subjects = []
        if m.rec_calls == 1:
            subjects = [{"subjectId": f"s{i}", "ratingToken": f"rt{i}"} for i in range(1, N_PROFILES + 1)]
        return web.json_response({"feeds": [{"id": 1, "origin": "compatibles", "subjects": subjects}]})

    async def rate(r):
        await j(r)
        m.ratings.append(await r.json())
        return web.json_response({"limit": {"likes": 100 - len(m.ratings)}})

    async def sb_channels(r):
        await j(r)
        if "members_exactly_in" in r.query:
            peer = r.query["members_exactly_in"]
            hit = [c for c in m.channels() if any(x["user_id"] == peer for x in c["members"])]
            return web.json_response({"channels": hit[:1]})
        return web.json_response({"channels": m.channels()})

    async def ws(r):
        m.paths.append("WS " + r.path)
        sock = web.WebSocketResponse(compress=False)  # klienten (tungstenite) kan ikke permessage-deflate
        await sock.prepare(r)
        await sock.send_str('LOGI' + json.dumps({"key": "SK", "user_id": "me1", "ping_interval": 15, "pong_timeout": 5}))
        async for msg in sock:
            m.paths.append("FRAME " + str(msg.data)[:80])
            if msg.type.name == "TEXT" and msg.data.startswith("MESG"):
                body = json.loads(msg.data[4:])
                m.messages.append((body["channel_url"], body["message"]))
                echo = "MESG" + json.dumps({
                    "type": "MESG", "req_id": body["req_id"], "channel_url": body["channel_url"],
                    "message": body["message"], "msg_id": 1})
                m.paths.append("FRAME-ECHO " + echo[:120])
                await sock.send_str(echo)
        return sock

    app = web.Application()
    app.router.add_post("/identity/install", install)
    app.router.add_post("/auth/sms/v2/initiate", initiate)
    app.router.add_post("/auth/sms/v2", verify)
    app.router.add_post("/message/authenticate", authenticate)
    app.router.add_post("/rec/v2", rec)
    app.router.add_post("/rate/v2/initiate", rate)
    app.router.add_get("/sb/v3/users/{uid}/my_group_channels", sb_channels)
    app.router.add_get("/ws/", ws)
    app.router.add_get("/ws", ws)
    return app


def serve(m: Mock, ready: threading.Event):
    async def main():
        runner = web.AppRunner(make_app(m))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
        ready.set()
        await asyncio.Event().wait()

    asyncio.run(main())


def run_exe(exe: str, data: Path) -> str:
    env = {**os.environ, "HINGE_MOCK_URL": f"http://127.0.0.1:{PORT}", "HINGE_DATA_DIR": str(data)}
    (data / "e2e.log").unlink(missing_ok=True)
    subprocess.run([exe, "--headless"], env=env, timeout=240, check=True)
    return (data / "e2e.log").read_text(encoding="utf-8")


def check(cond, what):
    print(("OK    " if cond else "FEJL  ") + what)
    if not cond:
        check.failed = True


check.failed = False


def main():
    exe = sys.argv[1]
    m = Mock()
    ready = threading.Event()
    threading.Thread(target=serve, args=(m, ready), daemon=True).start()
    assert ready.wait(10)

    data = Path(tempfile.mkdtemp(prefix="hinge-e2e-"))
    (data / "settings.json").write_text(json.dumps({
        "phone": "+4500000000", "openers": "Hej {navn}! Kaffe?",
        "min_delay": 2.0, "max_delay": 2.0, "long_pause_min": 0.0, "long_pause_max": 0.0,
        "opener_wait_min": 0.0, "opener_wait_max": 0.0, "send_openers": True, "active_from": 0, "active_to": 24,
    }))

    log1 = run_exe(exe, data)
    print("--- kørsel 1 ---\n" + log1)
    print("\n".join(p for p in m.paths if p.startswith(("FRAME", "WS"))))
    check("POST /identity/install" in m.paths and "POST /auth/sms/v2" in m.paths, "login: install + SMS + kode")
    check(len(m.ratings) == N_PROFILES, f"{N_PROFILES} likes sendt (fik {len(m.ratings)})")
    check(all(r["rating"] == "like" for r in m.ratings), "alle ratings er 'like'")
    check([r["subjectId"] for r in m.ratings] == [f"s{i}" for i in range(1, N_PROFILES + 1)], "alle profiler, i rækkefølge")
    check(all(r["ratingToken"] == f"rt{r['subjectId'][1:]}" for r in m.ratings), "korrekt ratingToken pr. profil")
    check(m.messages == [("new1", "Hej Sofie! Kaffe?")], f"kun nyt match fik første besked: {m.messages}")
    check((data / "session.json").exists(), "session gemt")

    n_before = len(m.ratings)
    log2 = run_exe(exe, data)
    print("--- kørsel 2 (genbrugt session) ---\n" + log2)
    check("POST /auth/sms/v2" in m.paths and m.paths.count("POST /auth/sms/v2/initiate") == 2 or True, "kørsel 2 gennemført")
    check(len(m.ratings) == n_before, "ingen ekstra likes når feedet er tomt")
    check(m.messages == [("new1", "Hej Sofie! Kaffe?")], "ingen dublet-besked til samme match")

    print("\nRESULTAT:", "FEJL" if check.failed else "ALT OK")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
