"""App-serverens sikkerhedstjek og indstillinger – uden telefon (der startes aldrig en kørsel)."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TMP = tempfile.TemporaryDirectory()
os.environ["HINGE_DATA_DIR"] = TMP.name   # skriv aldrig i den rigtige datamappe
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = app.Server(("127.0.0.1", 0), app.Handler)
        app.PORT = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", app.PORT, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        return r.status, r.read()

    def post(self, path, data):
        status, body = self.req("POST", path, json.dumps(data).encode(), {"Content-Type": "application/json"})
        return status, json.loads(body)

    def test_status_and_page(self):
        status, body = self.req("GET", "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(set(data["modes"]), {"secure", "human", "fast"})
        self.assertEqual(data["data_dir"], TMP.name)
        self.assertEqual(data["limits"]["human"], [80, 30])
        self.assertEqual(self.req("GET", "/")[0], 200)

    def test_rejects_foreign_host(self):   # DNS-rebinding
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.example:80"})[0], 403)

    def test_rejects_foreign_origin(self):   # CSRF fra en anden hjemmeside
        self.assertEqual(self.req("POST", "/api/start", b"{}", {"Origin": "http://evil.example"})[0], 403)

    def test_bad_json(self):
        self.assertEqual(self.req("POST", "/api/start", b"[1]")[0], 400)
        self.assertEqual(self.req("POST", "/api/start", b"{nope")[0], 400)

    def test_start_needs_accepted_terms(self):
        status, data = self.post("/api/start", {"mode": "human"})
        self.assertEqual((status, data), (409, {"error": "terms"}))
        self.assertIsNone(app.busy())

    def test_settings_merge_and_validate(self):
        status, data = self.post("/api/settings", {"mode": "secure", "from_hour": 99, "schedule": {"time": "07:15"},
                                                   "limits": {"secure": {"daily": 40}}})
        self.assertEqual(status, 200)
        s = data["settings"]
        self.assertEqual((s["mode"], s["from_hour"], s["schedule"]["time"]), ("secure", 8, "07:15"))
        self.assertEqual(s["schedule"]["mode"], "human")   # resten af sektionen er bevaret
        self.assertEqual(data["limits"]["secure"], [40, 20])
        _, data = self.post("/api/settings", {"limits": {}})   # grænser erstattes helt, så de kan nulstilles
        self.assertEqual(data["limits"]["secure"], [50, 20])
        self.assertFalse(data["settings"]["accepted_terms"])

    def test_open_unknown_target(self):
        self.assertEqual(self.post("/api/open", {"what": "../etc"})[0], 404)

    def test_not_frameable(self):   # clickjacking: en anden side må ikke vise appen i en iframe
        conn = http.client.HTTPConnection("127.0.0.1", app.PORT, timeout=5)
        conn.request("GET", "/")
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))

    def test_check_is_remembered(self):   # Opsætning skal huske tjekket – og hvorfor det fejlede – når appen startes igen
        app.remember_check(False, None, "Telefonen er låst")
        self.assertEqual(app.saved_check()["reason"], "Telefonen er låst")
        app.remember_check(True, 2)
        self.assertEqual(app.saved_check()["found"], 2)
        self.assertTrue(json.loads(self.req("GET", "/api/status")[1])["check"]["ok"])

    def test_port_is_exclusive(self):   # en app mere må ikke kunne dele porten (Windows: SO_REUSEADDR)
        with self.assertRaises(OSError):
            app.Server(("127.0.0.1", app.PORT), app.Handler)


if __name__ == "__main__":
    unittest.main()
