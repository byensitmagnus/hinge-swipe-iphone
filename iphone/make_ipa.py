"""Henter Appiums officielle WebDriverAgent-runner og pakker den som en .ipa, klar til Sideloadly.

Kør:  python make_ipa.py      ->  WebDriverAgentRunner.ipa i denne mappe
"""
import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

VERSION = "v16.15.3"
URL = f"https://github.com/appium/WebDriverAgent/releases/download/{VERSION}/WebDriverAgentRunner-Runner.zip"
OUT = Path(__file__).parent / "WebDriverAgentRunner.ipa"


def main() -> None:
    print(f"Henter {URL}")
    with urllib.request.urlopen(URL, timeout=60) as r:  # standard TLS-kontrol
        data = r.read()
    print(f"{len(data) / 1024:.0f} KB, sha256 {hashlib.sha256(data).hexdigest()}")
    src = zipfile.ZipFile(io.BytesIO(data))
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as ipa:
        for item in src.infolist():
            if ".dSYM" in item.filename:   # fejlsøgningssymboler, fylder bare
                continue
            info = zipfile.ZipInfo("Payload/" + item.filename, item.date_time)
            info.external_attr, info.compress_type = item.external_attr, zipfile.ZIP_DEFLATED
            ipa.writestr(info, src.read(item.filename))
    print(f"Skrev {OUT}")


if __name__ == "__main__":
    main()
