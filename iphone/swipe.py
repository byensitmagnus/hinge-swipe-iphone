"""Like profiler i Hinge-appen på din iPhone – kernen bag appen og kommandolinjen.

Kør:   python swipe.py [--mode secure|human|fast] [--max N] [--minutes M] [--daily N] [--from-hour 8] [--to-hour 23] [--dry]
App:   python app.py  (eller den installerede app / start.bat / start.command)
Stop:  opret en tom fil med navnet STOP i datamappen (fra kildekode: denne mappe), eller tryk Ctrl+C.

Sikkerhed: trykker aldrig på 'Send en rose' (betalt) – kun 'Send synes godt om'. Sender ingen beskeder.
"""
from __future__ import annotations
import argparse
import asyncio
import datetime as dt
import random
import sys
import time

from logic import (DEFAULT_BUTTONS, MODES, clean_settings, data_dir, human_delay, in_active_hours, is_paid, load_settings,
                   load_state, run_limits, save_state)
from wda import NoRunnerError, Stopped, accept_consent, activate, attribute, find, phone, tap, visible

DATA = data_dir()
STATE, STOP, SETTINGS = DATA / "state.json", DATA / "STOP", DATA / "settings.json"
BUTTONS = dict(DEFAULT_BUTTONS)   # sættes fra indstillingerne, når en kørsel starter
LANG = "da"

MSG = {
    "da": {
        "ready": "Klar ({mode}). Likes i dag: {today}/{daily}",
        "stopped": "Stoppet.",
        "daily_cap": "Dagens grænse på {daily} likes er nået.",
        "run_cap": "Nået {max} likes i denne kørsel.",
        "time_cap": "Kørslen har varet {minutes} min – stopper.",
        "hours_over": "Tidsrummet er slut – stopper.",
        "outside_hours": "Uden for tidsrummet {start}–{end} – starter ikke (kan ændres under Indstillinger).",
        "locked": "Telefonen er låst – lås den op og sæt Autolås til 'Aldrig'. Stopper.",
        "consent": "Privatlivs-vindue accepteret.",
        "back_discover": "Var ikke på Discover – gik tilbage.",
        "dry": "Forbindelsen virker. Like-knapper på skærmen: {n}.",
        "dry_none": "Forbindelsen virker, men der er ingen like-knap på skærmen. Åbn Discover i Hinge.",
        "unexpected": "Uventet skærm ({n}/3): {shown}",
        "too_many": "For mange uventede skærme – stopper. Tjek telefonen.",
        "liked": "♥ {button}  (i dag {today})",
        "pause": "Pause på {s} s",
        "error_retry": "Fejl ({n}/3): {err} – genåbner Hinge.",
        "interrupted": "Afbrudt.",
        "no_device": "Ingen iPhone fundet – sæt USB-kablet i, lås telefonen op og tryk 'Stol på', hvis den spørger.",
        "no_wda": "Testappen (WebDriverAgent) er ikke installeret på telefonen – se Opsætning.",
        "devmode_off": "Developer Mode er slået fra på telefonen – se Opsætning.",
        "untrusted": "Testappen kunne ikke starte. Stol på udvikleren under Indstillinger → Generelt → VPN og enhedsstyring, "
                     "eller installer den igen med Sideloadly (med gratis Apple ID udløber den efter 7 dage).",
        "not_paired": "Telefonen stoler ikke på computeren endnu – lås den op og tryk 'Stol på'.",
        "wda_timeout": "Testappen svarede ikke – lås telefonen op, og prøv igen.",
    },
    "en": {
        "ready": "Ready ({mode}). Likes today: {today}/{daily}",
        "stopped": "Stopped.",
        "daily_cap": "Reached today's limit of {daily} likes.",
        "run_cap": "Reached {max} likes in this run.",
        "time_cap": "The run has lasted {minutes} min – stopping.",
        "hours_over": "Outside the allowed hours now – stopping.",
        "outside_hours": "Outside the allowed hours {start}–{end} – not starting (change it in Settings).",
        "locked": "The phone is locked – unlock it and set Auto-Lock to 'Never'. Stopping.",
        "consent": "Accepted the privacy pop-up.",
        "back_discover": "Wasn't on Discover – went back.",
        "dry": "The connection works. Like buttons on screen: {n}.",
        "dry_none": "The connection works, but there is no like button on screen. Open Discover in Hinge.",
        "unexpected": "Unexpected screen ({n}/3): {shown}",
        "too_many": "Too many unexpected screens – stopping. Check the phone.",
        "liked": "♥ {button}  (today {today})",
        "pause": "Break for {s} s",
        "error_retry": "Error ({n}/3): {err} – reopening Hinge.",
        "interrupted": "Interrupted.",
        "no_device": "No iPhone found – plug in the USB cable, unlock the phone and tap 'Trust' if it asks.",
        "no_wda": "The test app (WebDriverAgent) is not installed on the phone – see Setup.",
        "devmode_off": "Developer Mode is off on the phone – see Setup.",
        "untrusted": "The test app could not start. Trust the developer in Settings → General → VPN & Device Management, "
                     "or reinstall it with Sideloadly (with a free Apple ID it expires after 7 days).",
        "not_paired": "The phone doesn't trust this computer yet – unlock it and tap 'Trust'.",
        "wda_timeout": "The test app didn't respond – unlock the phone and try again.",
    },
}

_sink = None


def set_sink(fn) -> None:
    """Appen sender loggen til sin egen visning i stedet for stdout."""
    global _sink
    _sink = fn


def say(key: str, **kw) -> str:
    return MSG.get(LANG, MSG["da"]).get(key, MSG["da"][key]).format(**kw)


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%H:%M:%S}  {msg}"
    if _sink:
        _sink(line)
    else:
        print(line, flush=True)


def friendly_error(e: BaseException) -> str | None:
    """Kendte fejl som en kort besked på brugerens sprog. None = ukendt fejl (vis den rå fejl)."""
    text, name = str(e), type(e).__name__
    if "unlocked" in text or "Locked" in text:
        return say("locked")
    if name == "NoDeviceConnectedError" or "Device is not connected" in text:
        return say("no_device")
    if isinstance(e, NoRunnerError):
        return say("no_wda")
    if "DeveloperMode" in name or "Developer Mode" in text:
        return say("devmode_off")
    if any(s in text for s in ("explicitly trusted", "invalid code signature", "could not be verified", "WDA-runneren stoppede")):
        return say("untrusted")
    if name in ("NotPairedError", "PairingDialogResponsePendingError", "UserDeniedPairingError", "PasswordRequiredError"):
        return say("not_paired")
    if isinstance(e, TimeoutError) and "WDA" in text:
        return say("wda_timeout")
    return None


async def nap(c, seconds: float) -> bool:
    """Sov, men reagér på STOP-filen. True = stop. Rører skærmen let hver ~12 s, så iPhonen ikke autolåser (Autolås min. 30 s)."""
    end = time.monotonic() + seconds
    touch = time.monotonic() + 12
    while time.monotonic() < end and not STOP.exists():
        await asyncio.sleep(min(1.0, max(0.0, end - time.monotonic())))
        if time.monotonic() >= touch and time.monotonic() < end - 2:
            touch = time.monotonic() + random.uniform(9, 13)
            try:   # lille scroll på profilen = ægte berøring, ændrer intet
                await c.swipe(200, 500, 200, random.choice((470, 530)), duration=0.3, session_id=c.session_id)
            except Exception:
                pass
    return STOP.exists()


async def ensure_discover(c, names: set) -> bool:
    """Gå tilbage til Discover, hvis Hinge står et andet sted (fx i en samtale). True hvis vi flyttede os."""
    if "discover_screen" in names:
        return False
    if "Hinge" not in names and await activate(c):   # en anden app (fx Messenger) er forrest
        await asyncio.sleep(2)
        names = {e["name"] for e in await visible(c)}
        if "discover_screen" in names:
            return True
    for back in ("BackButton", BUTTONS["close"]):
        if back in names:
            await tap(c, back)
            await asyncio.sleep(1.5)
    await tap(c, "Discover")
    await asyncio.sleep(2)
    return True


async def like_current(c, names: list, fast: bool = False) -> str | None:
    """Like profilen på skærmen (names = elementnavne fra den aktuelle skærm). Returnerer navnet på like-knappen, ellers None."""
    send = BUTTONS["send_like"]
    button = "(åbent kommentarfelt)"
    if send not in names:   # kommentarfeltet er ikke allerede åbent (fx efter en afbrudt kørsel)
        likes = [n for n in names if n.startswith(BUTTONS["like_prefix"]) and not is_paid(n)]
        if not likes or not await tap(c, likes[0]):
            return None
        button = likes[0]
        await asyncio.sleep(random.uniform(0.6, 1.0) if fast else random.uniform(1.0, 2.0))
    for _ in range(2):   # tryk 'Send', og tjek at feltet lukkede – ellers tryk igen (første tryk kan ramme midt i tastatur-animationen)
        if not await tap(c, send):
            return None
        await asyncio.sleep(random.uniform(0.5, 0.9) if fast else random.uniform(1.5, 2.5))
        if send not in {e["name"] for e in await visible(c)}:
            return button
    return None


async def quick_like(c) -> str | None:
    """Hurtig vej uden at læse hele skærmen: find like-knap, tryk, tryk 'Send', tjek at feltet lukkede.
    None = noget var anderledes; så tager hovedløkken den grundige vej (låst telefon, Discover, pop-ups)."""
    prefix = BUTTONS["like_prefix"].replace("\\", "\\\\").replace("'", "\\'")
    like = await find(c, "-ios predicate string", f"name BEGINSWITH '{prefix}' AND visible == 1")
    if like is None:
        return None
    try:
        button = await attribute(c, like, "name")
        if is_paid(button):   # aldrig en betalt knap
            return None
        await c.click(like, session_id=c.session_id)
    except Exception:
        return None
    await asyncio.sleep(random.uniform(0.6, 1.0))
    for _ in range(2):
        if not await tap(c, BUTTONS["send_like"]):
            return None
        await asyncio.sleep(random.uniform(0.5, 0.9))
        if await find(c, "accessibility id", BUTTONS["send_like"]) is None:
            return button
    return None


async def read_profile(c) -> None:
    """Scroll lidt ned på profilen, som en der læser den."""
    for _ in range(random.randint(1, 2)):
        await c.swipe(200, 600, 200, random.randint(300, 400), duration=random.uniform(0.35, 0.7), session_id=c.session_id)
        await asyncio.sleep(random.uniform(0.8, 2.0))


async def run(cfg: dict) -> dict:
    """Én kørsel. cfg: mode, max, daily, minutes, from_hour, to_hour, dry, buttons, lang.
    Returnerer {"ok", "liked", "found"}. Fejl, der ikke kan klares undervejs, kastes videre (se friendly_error)."""
    global LANG
    LANG = cfg.get("lang", "da")
    BUTTONS.update(DEFAULT_BUTTONS)
    BUTTONS.update(cfg.get("buttons") or {})
    m = MODES[cfg["mode"]]
    daily, minutes, quick = cfg["daily"], cfg["minutes"], m["quick"]
    result = {"ok": False, "liked": 0, "found": None}

    STOP.unlink(missing_ok=True)
    if not cfg.get("dry") and not in_active_hours(dt.datetime.now().hour, cfg["from_hour"], cfg["to_hour"]):
        log(say("outside_hours", start=cfg["from_hour"], end=cfg["to_hour"]))
        return result

    state = load_state(STATE)
    started = time.monotonic()
    done = anomalies = since_break = errors = 0
    next_break = random.randint(*m["every"])

    try:
        async with phone(should_stop=STOP.exists) as c:
            log(say("ready", mode=cfg["mode"], today=state["likes_today"], daily=daily))
            result["ok"] = True
            while True:
                if STOP.exists():
                    log(say("stopped"))
                    return result
                if not cfg.get("dry") and state["likes_today"] >= daily:   # et tjek liker intet, så grænsen gælder ikke
                    log(say("daily_cap", daily=daily))
                    return result
                if cfg.get("max") and done >= cfg["max"]:
                    log(say("run_cap", max=cfg["max"]))
                    return result
                if time.monotonic() - started > minutes * 60:
                    log(say("time_cap", minutes=minutes))
                    return result
                if not cfg.get("dry") and not in_active_hours(dt.datetime.now().hour, cfg["from_hour"], cfg["to_hour"]):
                    log(say("hours_over"))
                    return result

                try:
                    button = await quick_like(c) if quick and not cfg.get("dry") else None
                    if button is None:
                        names = [e["name"] or "" for e in await visible(c)]   # grundig vej: skærmen læses én gang (~1,7 s)
                        if "SBCoverSheetWindow" in names:
                            log(say("locked"))
                            result["ok"] = False
                            return result
                        if BUTTONS["consent"] in names and await accept_consent(c, BUTTONS["consent"]):
                            log(say("consent"))
                            await asyncio.sleep(2)
                            continue
                        if await ensure_discover(c, set(names)):
                            log(say("back_discover"))
                            continue

                        if cfg.get("dry"):
                            found = [n for n in names if n.startswith(BUTTONS["like_prefix"])]
                            result["found"] = len(found)
                            log(say("dry", n=len(found)) if found else say("dry_none"))
                            return result

                        if random.random() < m["read"]:   # scroll lidt på profilen, som en der læser den
                            await read_profile(c)
                        button = await like_current(c, names, quick)
                    if button is None:
                        anomalies += 1
                        now = await visible(c)
                        if any(e["name"] == "SBCoverSheetWindow" for e in now):
                            log(say("locked"))
                            result["ok"] = False
                            return result
                        shown = " | ".join((e["name"] or "")[:30] for e in now[:12])
                        log(say("unexpected", n=anomalies, shown=shown))
                        if anomalies >= 3:
                            log(say("too_many"))
                            return result
                        await asyncio.sleep(3)
                        continue

                    anomalies = 0
                    done += 1
                    result["liked"] = done
                    state["likes_today"] += 1
                    save_state(STATE, state)
                    log(say("liked", button=button, today=state["likes_today"]))

                    since_break += 1
                    if since_break >= next_break:
                        since_break, next_break = 0, random.randint(*m["every"])
                        pause = random.uniform(*m["pause"])
                        log(say("pause", s=f"{pause:.0f}"))
                        await nap(c, pause)
                    await nap(c, human_delay(random.random(), random.random(), *m["delay"]))
                    errors = 0
                except Exception as e:   # WDA-hik eller Hinge lukket/crashet: genåbn Hinge og prøv igen
                    if friendly_error(e) in (say("locked"), say("no_device")):
                        raise
                    errors += 1
                    log(say("error_retry", n=errors, err=str(e)[:120]))
                    if errors >= 3:
                        raise
                    await activate(c)
                    await asyncio.sleep(4)
    except Stopped:   # Stop trykket, mens forbindelsen blev sat op
        log(say("stopped"))
        return result


def config(settings: dict, mode: str | None = None, **override) -> dict:
    """Kørsels-opsætning ud fra indstillingerne; override (max, daily, minutes, from_hour, to_hour, dry) vinder, hvis sat."""
    mode = mode if mode in MODES else settings["mode"]
    daily, minutes = run_limits(settings, mode)
    cfg = {"mode": mode, "max": 0, "daily": daily, "minutes": minutes, "from_hour": settings["from_hour"],
           "to_hour": settings["to_hour"], "dry": False, "buttons": settings["buttons"], "lang": settings["lang"]}
    cfg.update({k: v for k, v in override.items() if v is not None})
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="human",
                    help="secure (50/dag, langsomt), human (80/dag, standard), fast (200/dag, højere ban-risiko)")
    ap.add_argument("--fast", action="store_true", help="samme som --mode fast")
    ap.add_argument("--max", type=int, help="max likes i denne kørsel (0 = ingen grænse)")
    ap.add_argument("--minutes", type=int, help="stop efter så mange minutter (standard fra tempoet)")
    ap.add_argument("--daily", type=int, help="max likes pr. dag (standard fra tempoet)")
    ap.add_argument("--from-hour", type=int)
    ap.add_argument("--to-hour", type=int)
    ap.add_argument("--dry", action="store_true", help="tjek forbindelsen og vis, hvad der ville ske – liker intet")
    a = ap.parse_args()
    saved = load_settings(SETTINGS)
    base = clean_settings({"buttons": saved["buttons"], "lang": saved["lang"]})   # appens tempo og grænser gælder ikke her
    cfg = config(base, "fast" if a.fast else a.mode, max=a.max, daily=a.daily or None,
                 minutes=a.minutes or None, from_hour=a.from_hour, to_hour=a.to_hour, dry=a.dry)
    global LANG
    LANG = cfg["lang"]
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        log(say("interrupted"))
    except Exception as e:
        msg = friendly_error(e)
        if not msg:
            raise
        log(msg)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-konsollen er cp1252 og kan ikke skrive fx dansk/♥
    main()
