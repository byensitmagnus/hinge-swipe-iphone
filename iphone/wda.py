"""Tynd hjælper til at styre en iPhone over USB via WebDriverAgent (WDA).

`phone()` starter WDA-runneren på telefonen, åbner en session i en app og rydder op bagefter.
Kræver at WebDriverAgentRunner er installeret på telefonen (se docs/index.html).
"""
from __future__ import annotations
import asyncio
import contextlib
import os
import warnings
import xml.etree.ElementTree as ET

warnings.filterwarnings("ignore")

from pymobiledevice3 import usbmux  # noqa: E402
from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel  # noqa: E402
from pymobiledevice3.services.dvt.testmanaged.xcuitest import TestConfig, XCUITestService  # noqa: E402
from pymobiledevice3.services.installation_proxy import InstallationProxyService  # noqa: E402
from pymobiledevice3.services.wda import DEFAULT_WDA_PORT, WdaServiceClient  # noqa: E402

from logic import is_paid  # noqa: E402

HINGE = "co.hinge.mobile.ios"
RUNNER_PREFIX = "com.facebook.WebDriverAgentRunner.xctrunner"


class NoRunnerError(RuntimeError):
    """Testappen (WebDriverAgentRunner) er ikke installeret på telefonen."""


class Stopped(Exception):
    """Brugeren trykkede Stop, mens forbindelsen til telefonen blev sat op."""


async def find_runner(lockdown) -> str:
    """Bundle-id på den installerede WDA-runner (ender på dit eget team-id). WDA_RUNNER kan sætte den manuelt."""
    if os.environ.get("WDA_RUNNER"):
        return os.environ["WDA_RUNNER"]
    apps = await InstallationProxyService(lockdown).get_apps()
    for bundle_id in apps:
        if bundle_id.startswith(RUNNER_PREFIX):
            return bundle_id
    raise NoRunnerError("WebDriverAgentRunner is not installed on the iPhone")


async def device_status() -> dict:
    """Hurtigt overblik (~0,2 s) uden at starte noget på telefonen: forbundet, navn, iOS, Developer Mode, testapp, Hinge."""
    from pymobiledevice3.lockdown import create_using_usbmux

    out = {"connected": False, "paired": False, "name": None, "model": None, "ios": None,
           "developer_mode": None, "wda": False, "hinge": False, "error": None}
    try:
        devices = [d for d in await usbmux.list_devices() if d.is_usb]
    except Exception:   # usbmuxd svarer ikke: Apples USB-driver (følger med iTunes) mangler eller kører ikke
        out["error"] = "no_driver"
        return out
    if not devices:
        return out
    out["connected"] = True
    try:
        lockdown = await create_using_usbmux(serial=devices[0].serial, autopair=True, pair_timeout=2)
    except Exception as e:   # ikke parret endnu: telefonen viser 'Stol på denne computer?'
        out["error"] = type(e).__name__
        return out
    try:
        out.update(paired=True, name=lockdown.short_info.get("DeviceName"), model=lockdown.display_name,
                   ios=lockdown.product_version)
        with contextlib.suppress(Exception):
            out["developer_mode"] = await lockdown.get_developer_mode_status()
        apps = await InstallationProxyService(lockdown).get_apps(application_type="User")
        out["wda"] = any(b.startswith(RUNNER_PREFIX) for b in apps)
        out["hinge"] = HINGE in apps
    finally:
        with contextlib.suppress(Exception):
            await lockdown.close()
    return out


async def reveal_developer_mode() -> None:
    """Få 'Developer Mode' til at dukke op under Indstillinger > Anonymitet og sikkerhed på telefonen."""
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.amfi import AmfiService

    lockdown = await create_using_usbmux(autopair=False)
    try:
        await AmfiService(lockdown).reveal_developer_mode_option_in_ui()
    finally:
        with contextlib.suppress(Exception):
            await lockdown.close()


@contextlib.asynccontextmanager
async def phone(bundle_id: str = HINGE, should_stop=None):
    """Start WDA og giv en klient med en aktiv session i `bundle_id`. Appen genstartes ikke, hvis den allerede kører.
    should_stop() kaldes, mens der ventes på telefonen; returnerer den True, afbrydes opstarten med Stopped."""
    def check_stop():
        if should_stop is not None and should_stop():
            raise Stopped()

    # iOS 17+: tunnel uden admin-rettigheder. Den åbnes og lukkes pr. session: den hører til den event-loop,
    # der skabte den, og appen kører hver opgave i sin egen loop.
    async with UserspaceRsdTunnel() as lockdown:
        cfg = await TestConfig.create_for(lockdown, runner_bundle_id=await find_runner(lockdown))
        task = asyncio.create_task(XCUITestService(lockdown).run(cfg))
        try:
            for _ in range(300):  # vent op til ~30 s på at WDA svarer
                check_stop()
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
                check_stop()
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
    """Tryk på elementet med dette accessibility-id. False hvis det ikke findes – eller er en betalt knap (rose, boost)."""
    if is_paid(name):
        return False
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


async def screen_names() -> list[str]:
    """Navnene på de synlige elementer i Hinge lige nu – til at finde knapnavne på et andet sprog. Ændrer ingenting."""
    async with phone() as c:
        return sorted({e["name"] for e in await visible(c) if e["name"] and len(e["name"]) <= 80})


async def accept_consent(c, name: str = "Jeg er enig") -> bool:
    """Hinges privatlivs-vindue dukker op tilfældigt og kan ikke afvises varigt; her accepteres det."""
    return await tap(c, name)
