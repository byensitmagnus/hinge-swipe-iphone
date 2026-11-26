"""App-serverens sikkerhedstjek – uden telefon (der startes aldrig en kørsel)."""
import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        app.PORT = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", app.PORT, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        return r.status, r.read()

    def test_status_and_page(self):
        status, body = self.req("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(body)["modes"]), {"secure", "human", "fast"})
        self.assertEqual(self.req("GET", "/")[0], 200)

    def test_rejects_foreign_host(self):   # DNS-rebinding
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.example:80"})[0], 403)

    def test_rejects_foreign_origin(self):   # CSRF fra en anden hjemmeside
        self.assertEqual(self.req("POST", "/api/start", b"{}", {"Origin": "http://evil.example"})[0], 403)

    def test_bad_json(self):
        self.assertEqual(self.req("POST", "/api/start", b"[1]")[0], 400)
        self.assertEqual(self.req("POST", "/api/start", b"{nope")[0], 400)


if __name__ == "__main__":
    unittest.main()
