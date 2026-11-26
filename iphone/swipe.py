"""Like profiler i Hinge-appen på din iPhone i roligt tempo.

Kør:   python swipe.py [--mode secure|human|fast] [--max N] [--minutes M] [--daily N] [--from-hour 8] [--to-hour 23] [--dry]
App:   python app.py  (eller dobbeltklik start.bat / start.command i roden)
Stop:  opret en tom fil med navnet STOP i denne mappe (eller tryk Ctrl+C).

Sikkerhed: trykker aldrig på 'Send en rose' (betalt) – kun 'Send synes godt om'. Sender ingen beskeder.
"""
import argparse
import asyncio
import datetime as dt
import random
import sys
import time
from pathlib import Path

from logic import MODES, human_delay, in_active_hours, load_state, save_state
from wda import accept_consent, activate, attribute, find, phone, tap, visible

HERE = Path(__file__).parent
STATE, STOP = HERE / "state.json", HERE / "STOP"
LIKE_PREFIX = "Synes godt om "   # fx "Synes godt om Elsas billede"
SEND_LIKE = "Send synes godt om"


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%H:%M:%S}  {msg}", flush=True)


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
    for back in ("BackButton", "Afslut"):
        if back in names:
            await tap(c, back)
            await asyncio.sleep(1.5)
    await tap(c, "Discover")
    await asyncio.sleep(2)
    return True


async def like_current(c, names: list, fast: bool = False) -> str | None:
    """Like profilen på skærmen (names = elementnavne fra den aktuelle skærm). Returnerer navnet på like-knappen, ellers None."""
    button = "(åbent kommentarfelt)"
    if SEND_LIKE not in names:   # kommentarfeltet er ikke allerede åbent (fx efter en afbrudt kørsel)
        likes = [n for n in names if n.startswith(LIKE_PREFIX)]
        if not likes or not await tap(c, likes[0]):
            return None
        button = likes[0]
        await asyncio.sleep(random.uniform(0.6, 1.0) if fast else random.uniform(1.0, 2.0))
    for _ in range(2):   # tryk 'Send', og tjek at feltet lukkede – ellers tryk igen (første tryk kan ramme midt i tastatur-animationen)
        if not await tap(c, SEND_LIKE):
            return None
        await asyncio.sleep(random.uniform(0.5, 0.9) if fast else random.uniform(1.5, 2.5))
        if SEND_LIKE not in {e["name"] for e in await visible(c)}:
            return button
    return None


async def quick_like(c) -> str | None:
    """Hurtig vej uden at læse hele skærmen: find like-knap, tryk, tryk 'Send', tjek at feltet lukkede.
    None = noget var anderledes; så tager hovedløkken den grundige vej (låst telefon, Discover, pop-ups)."""
    like = await find(c, "-ios predicate string", f"name BEGINSWITH '{LIKE_PREFIX}' AND visible == 1")
    if like is None:
        return None
    try:
        button = await attribute(c, like, "name")
        await c.click(like, session_id=c.session_id)
    except Exception:
        return None
    await asyncio.sleep(random.uniform(0.6, 1.0))
    for _ in range(2):
        if not await tap(c, SEND_LIKE):
            return None
        await asyncio.sleep(random.uniform(0.5, 0.9))
        if await find(c, "accessibility id", SEND_LIKE) is None:
            return button
    return None


async def read_profile(c) -> None:
    """Scroll lidt ned på profilen, som en der læser den."""
    for _ in range(random.randint(1, 2)):
        await c.swipe(200, 600, 200, random.randint(300, 400), duration=random.uniform(0.35, 0.7), session_id=c.session_id)
        await asyncio.sleep(random.uniform(0.8, 2.0))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="human", help="secure (50/dag, langsomt), human (80/dag, standard), fast (200/dag, højere ban-risiko)")
    ap.add_argument("--fast", action="store_true", help="samme som --mode fast")
    ap.add_argument("--max", type=int, default=0, help="max likes i denne kørsel (0 = ingen grænse)")
    ap.add_argument("--minutes", type=int, help="stop efter så mange minutter (standard fra tempoet)")
    ap.add_argument("--daily", type=int, help="max likes pr. dag (standard fra tempoet)")
    ap.add_argument("--from-hour", type=int, default=8)
    ap.add_argument("--to-hour", type=int, default=23)
    ap.add_argument("--dry", action="store_true", help="vis kun, hvad der ville ske")
    a = ap.parse_args()
    m = MODES["fast" if a.fast else a.mode]
    a.daily = a.daily or m["daily"]
    a.minutes = a.minutes or m["minutes"]
    quick = m["quick"]

    STOP.unlink(missing_ok=True)
    if not in_active_hours(dt.datetime.now().hour, a.from_hour, a.to_hour):
        return log(f"Uden for tidsrummet {a.from_hour}-{a.to_hour} – starter ikke.")

    state = load_state(STATE)
    started = time.monotonic()
    done = anomalies = since_break = 0
    next_break = random.randint(*m["every"])

    async with phone() as c:
        log(f"Klar ({'fast' if a.fast else a.mode}). Likes i dag: {state['likes_today']}/{a.daily}")
        while True:
            if STOP.exists():
                return log("Stoppet (STOP-fil).")
            if state["likes_today"] >= a.daily:
                return log(f"Dagens grænse på {a.daily} er nået.")
            if a.max and done >= a.max:
                return log(f"Nået {a.max} likes i denne kørsel.")
            if time.monotonic() - started > a.minutes * 60:
                return log(f"Sessionen har kørt {a.minutes} min – stopper.")
            if not in_active_hours(dt.datetime.now().hour, a.from_hour, a.to_hour):
                return log("Tidsrummet er slut – stopper.")

            button = await quick_like(c) if quick and not a.dry else None
            if button is None:
                names = [e["name"] or "" for e in await visible(c)]   # grundig vej: skærmen læses én gang (~1,7 s)
                if "SBCoverSheetWindow" in names:
                    return log("Telefonen er låst – lås op og sæt Indstillinger > Skærm > Autolås til 'Aldrig'. Stopper.")
                if "Jeg er enig" in names and await accept_consent(c):
                    log("Privatlivs-vindue accepteret.")
                    await asyncio.sleep(2)
                    continue
                if await ensure_discover(c, set(names)):
                    log("Var ikke på Discover – gik tilbage.")
                    continue

                if a.dry:
                    return log(f"(prøve) like-knapper på skærmen: {[n for n in names if n.startswith(LIKE_PREFIX)]}")

                if random.random() < m["read"]:   # scroll lidt på profilen, som en der læser den
                    await read_profile(c)
                button = await like_current(c, names, quick)
            if button is None:
                anomalies += 1
                shown = " | ".join((e["name"] or "")[:30] for e in (await visible(c))[:12])
                log(f"Uventet skærm ({anomalies}/3): {shown}")
                if anomalies >= 3:
                    return log("For mange uventede skærme – stopper (tjek telefonen).")
                await asyncio.sleep(3)
                continue

            anomalies = 0
            done += 1
            state["likes_today"] += 1
            save_state(STATE, state)
            log(f"♥ {button}  (i dag {state['likes_today']})")

            since_break += 1
            if since_break >= next_break:
                since_break, next_break = 0, random.randint(*m["every"])
                pause = random.uniform(*m["pause"])
                log(f"Pause på {pause:.0f} s")
                await nap(c, pause)
            await nap(c, human_delay(random.random(), random.random(), *m["delay"]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-konsollen er cp1252 og kan ikke skrive fx dansk/♥
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Afbrudt.")
    except Exception as e:
        if "unlocked" in str(e) or "Locked" in str(e):
            log("Telefonen er låst – lås op (og sæt Autolås til 'Aldrig'), kør så igen.")
        else:
            raise
