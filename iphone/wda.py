"""Tynd hjælper til at styre en iPhone over USB via WebDriverAgent (WDA).

`phone()` starter WDA-runneren på telefonen, åbner en session i en app og rydder op bagefter.
Kræver at WebDriverAgentRunner er installeret på telefonen (se docs/index.html).
"""
import asyncio
import contextlib
import os
import warnings
import xml.etree.ElementTree as ET

warnings.filterwarnings("ignore")

from pymobiledevice3 import usbmux  # noqa: E402
from pymobiledevice3.remote.userspace_tunnel import establish_userspace_rsd  # noqa: E402
from pymobiledevice3.services.dvt.testmanaged.xcuitest import TestConfig, XCUITestService  # noqa: E402
from pymobiledevice3.services.installation_proxy import InstallationProxyService  # noqa: E402
from pymobiledevice3.services.wda import DEFAULT_WDA_PORT, WdaServiceClient  # noqa: E402

HINGE = "co.hinge.mobile.ios"
RUNNER_PREFIX = "com.facebook.WebDriverAgentRunner.xctrunner"


async def find_runner(lockdown) -> str:
    """Bundle-id på den installerede WDA-runner (ender på dit eget team-id). WDA_RUNNER kan sætte den manuelt."""
    if os.environ.get("WDA_RUNNER"):
        return os.environ["WDA_RUNNER"]
    apps = await InstallationProxyService(lockdown).get_apps()
    for bundle_id in apps:
        if bundle_id.startswith(RUNNER_PREFIX):
            return bundle_id
    raise RuntimeError("WebDriverAgentRunner er ikke installeret på telefonen – følg docs/index.html trin 3-5.")


@contextlib.asynccontextmanager
async def phone(bundle_id: str = HINGE):
    """Start WDA og giv en klient med en aktiv session i `bundle_id`. Appen genstartes ikke, hvis den allerede kører."""
    lockdown = await establish_userspace_rsd()  # iOS 17+: tunnel uden admin-rettigheder
    cfg = await TestConfig.create_for(lockdown, runner_bundle_id=await find_runner(lockdown))
    task = asyncio.create_task(XCUITestService(lockdown).run(cfg))
    try:
        for _ in range(300):  # vent op til ~30 s på at WDA svarer
            if task.done():
                task.result()
                raise RuntimeError("WDA-runneren stoppede uventet")
            device = await usbmux.select_device(lockdown.udid)
            try:
                (await device.connect(DEFAULT_WDA_PORT)).close()
                break
            except Exception:
                await asyncio.sleep(0.1)
        else:
            raise TimeoutError("WDA svarede ikke inden for 30 sekunder")

        client = WdaServiceClient(service_provider=lockdown, timeout=30.0)
        for attempt in range(6):  # WDA lukker nogle gange den første forbindelse lige efter opstart
            try:
                await client.start_session()
                break
            except Exception:
                if attempt == 5:
                    raise
                await asyncio.sleep(2)
        with contextlib.suppress(Exception):
            await client.unlock()  # låser telefonen sig selv, når der ikke er en kode på den
        await asyncio.sleep(1.5)

        # Vent ikke på at appen er "i ro" før hvert tryk/hver skærmlæsning – Hinge animerer konstant, så det koster sekunder pr. kald.
        caps = {"bundleId": bundle_id, "shouldTerminateApp": False, "forceAppLaunch": False,
                "shouldWaitForQuiescence": False, "waitForIdleTimeout": 0}
        data = await client._request_json("POST", "/session", {"capabilities": {"alwaysMatch": caps}, "desiredCapabilities": caps})
        client.session_id = data.get("sessionId") or data["value"]["sessionId"]
        with contextlib.suppress(Exception):
            await client._request_json("POST", f"/session/{client.session_id}/appium/settings",
                                       {"settings": {"waitForIdleTimeout": 0, "animationCoolOffTimeout": 0}})
        yield client
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


def elements(source: str) -> list[dict]:
    """Alle UI-elementer med navn/label/værdi fra WDA's XML (type, name, label, value, x, y, w, h, visible)."""
    out = []
    for e in ET.fromstring(source).iter():
        a = e.attrib
        if not (a.get("name") or a.get("label") or a.get("value")):
            continue
        out.append({
            "type": e.tag.replace("XCUIElementType", ""),
            "name": a.get("name"), "label": a.get("label"), "value": a.get("value"),
            "x": int(a.get("x", 0)), "y": int(a.get("y", 0)), "w": int(a.get("width", 0)), "h": int(a.get("height", 0)),
            "visible": a.get("visible") == "true",
        })
    return out


async def visible(c) -> list[dict]:
    """Synlige elementer på skærmen lige nu."""
    return [e for e in elements(await c.get_source(session_id=c.session_id)) if e["visible"]]


async def tap(c, name: str) -> bool:
    """Tryk på elementet med dette accessibility-id. False hvis det ikke findes."""
    try:
        element = await c.find_element("accessibility id", name, session_id=c.session_id)
        await c.click(element, session_id=c.session_id)
        return True
    except Exception:
        return False


async def find(c, using: str, value: str) -> str | None:
    """Element-id for første match (~0,2 s), eller None. Langt hurtigere end at læse hele skærmen (~1,7 s)."""
    try:
        return await c.find_element(using, value, session_id=c.session_id)
    except Exception:
        return None


async def attribute(c, element: str, name: str) -> str:
    data = await c._request_json("GET", f"/session/{c.session_id}/element/{element}/attribute/{name}")
    return data.get("value") or ""


async def activate(c, bundle_id: str = HINGE) -> bool:
    """Hent appen frem igen, hvis en anden app (fx en besked-notifikation) har taget forgrunden."""
    try:
        await c._request_json("POST", f"/session/{c.session_id}/wda/apps/activate", {"bundleId": bundle_id})
        return True
    except Exception:
        return False


async def accept_consent(c) -> bool:
    """Hinges privatlivs-vindue dukker op tilfældigt og kan ikke afvises varigt; her accepteres det."""
    return await tap(c, "Jeg er enig")
