"""Ren logik uden telefon og netværk: tempo, tidsrum, dagstæller, historik og indstillinger.
Alt tilfældigt kommer ind som parameter, så det kan testes."""
from __future__ import annotations
import copy
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

APP_NAME = "Hinge Auto Swipe"
VERSION = "2.0.1"

MODES = {
    # secure: lavest ban-risiko. human: standard, menneskeligt tempo. fast: hurtigt, markant højere ban-risiko.
    "secure": {"daily": 50, "minutes": 20, "delay": (8.0, 18.0), "read": 0.9, "pause": (90, 180), "every": (8, 15), "quick": False},
    "human":  {"daily": 80, "minutes": 30, "delay": (5.0, 12.0), "read": 0.7, "pause": (45, 120), "every": (12, 25), "quick": False},
    "fast":   {"daily": 200, "minutes": 120, "delay": (1.0, 2.5), "read": 0.0, "pause": (15, 30), "every": (12, 25), "quick": True},
}

# Hinges knapnavne (accessibility) i den testede danske opsætning. Kan ændres under Indstillinger til andre sprog.
DEFAULT_BUTTONS = {
    "like_prefix": "Synes godt om ",   # fx "Synes godt om Elsas billede"
    "send_like": "Send synes godt om",
    "consent": "Jeg er enig",          # Hinges privatlivs-vindue
    "close": "Afslut",                 # luk en åben samtale/skærm
}

# Betalte knapper må appen aldrig trykke på (AGENTS.md). Kendte navne i små bogstaver + et mønster for andre sprog.
PAID_NAMES = ("send en rose", "send a rose", "rose", "roser", "roses")
_PAID_WORD = re.compile(r"\b(roses?|roser|rosa|boost)\b", re.I)


def is_paid(name: str) -> bool:
    """Er dette en betalt knap (rose, boost)? Like-knapper med en person, der hedder Rose, er ikke ("Synes godt om Roses billede")."""
    n = " ".join(str(name).split()).lower()
    return (n in PAID_NAMES or "boost" in n
            or re.match(r"(send|giv|give|sende)\b.*\b(roses?|roser|rosa)\b", n) is not None)


DEFAULT_SETTINGS = {
    "lang": "da",
    "mode": "human",
    "from_hour": 8,
    "to_hour": 23,
    "limits": {},   # egne grænser pr. tempo, fx {"fast": {"daily": 300, "minutes": 150}}
    "buttons": DEFAULT_BUTTONS,
    "schedule": {"enabled": False, "time": "18:00", "mode": "human", "last_run": ""},
    "accepted_terms": False,
}

HISTORY_DAYS = 120


def data_dir() -> Path:
    """Hvor indstillinger, tæller og testappen gemmes. Fra kildekode: iphone-mappen (som hidtil).
    Som installeret app: brugerens app-data (Program Files er skrivebeskyttet). HINGE_DATA_DIR overstyrer."""
    if os.environ.get("HINGE_DATA_DIR"):
        path = Path(os.environ["HINGE_DATA_DIR"])
    elif getattr(sys, "frozen", False):
        if sys.platform == "win32":
            path = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "HingeAutoSwipe"
        elif sys.platform == "darwin":
            path = Path.home() / "Library" / "Application Support" / "HingeAutoSwipe"
        else:
            path = Path.home() / ".local" / "share" / "HingeAutoSwipe"
    else:
        path = Path(__file__).parent
    path.mkdir(parents=True, exist_ok=True)
    return path


def human_delay(r1: float, r2: float, lo: float = 5.0, hi: float = 12.0) -> float:
    """Pause før næste like (sek). r1 vælger basis i [lo, hi]; r2 > 0.9 giver en ekstra 'kiggede lidt længere'-pause."""
    base = lo + (hi - lo) * min(max(r1, 0.0), 1.0)
    extra = (r2 - 0.9) * 10.0 * 3.0 * hi if r2 > 0.9 else 0.0
    return base + extra


def in_active_hours(hour: int, start: int, end: int) -> bool:
    """Er klokkeslættet i det tilladte tidsrum? start==end eller 0..24 betyder hele døgnet; start>end går over midnat."""
    if start == end or (start == 0 and end == 24):
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _retry(fn):
    """Windows: en fil, der lige nu læses eller erstattes af en anden tråd, giver kortvarigt PermissionError."""
    for attempt in range(40):
        try:
            return fn()
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.025)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(_retry(lambda: path.read_text(encoding="utf-8")))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Atomisk: appen læser filerne samtidig og må aldrig se en halvskrevet fil."""
    tmp = path.with_name(path.name + ".tmp")
    _retry(lambda: tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"))
    _retry(lambda: os.replace(tmp, path))


def load_state(path: Path, today: str | None = None) -> dict:
    """Dagens tæller + historik pr. dag. Ved ny dato flyttes gårsdagens tal til historikken.
    Ødelagt eller manglende fil giver en tom tæller."""
    today = today or dt.date.today().isoformat()
    state = _read_json(path)
    history = state.get("history") if isinstance(state.get("history"), dict) else {}
    history = {d: n for d, n in history.items() if isinstance(d, str) and isinstance(n, int)}
    if state.get("date") != today:
        if isinstance(state.get("date"), str) and isinstance(state.get("likes_today"), int) and state["likes_today"] > 0:
            history[state["date"]] = state["likes_today"]
        state = {"date": today, "likes_today": 0}
    if not isinstance(state.get("likes_today"), int):
        state["likes_today"] = 0
    state["history"] = dict(sorted(history.items())[-HISTORY_DAYS:])
    return state


def save_state(path: Path, state: dict) -> None:
    _write_json(path, state)


def _int(value, lo: int, hi: int, default: int | None) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if lo <= n <= hi else default


def clean_settings(raw: dict | None) -> dict:
    """Flet gemte/indsendte indstillinger med standarderne og afvis alt ugyldigt (typer, intervaller, ukendte nøgler)."""
    raw = raw if isinstance(raw, dict) else {}
    s = copy.deepcopy(DEFAULT_SETTINGS)
    if raw.get("lang") in ("da", "en"):
        s["lang"] = raw["lang"]
    if raw.get("mode") in MODES:
        s["mode"] = raw["mode"]
    for key in ("from_hour", "to_hour"):
        s[key] = _int(raw.get(key), 0, 24, s[key])
    limits = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    for mode, lim in limits.items():
        if mode in MODES and isinstance(lim, dict):
            clean = {k: v for k, v in (("daily", _int(lim.get("daily"), 1, 1000, None)),
                                       ("minutes", _int(lim.get("minutes"), 1, 720, None))) if v is not None}
            if clean:
                s["limits"][mode] = clean
    buttons = raw.get("buttons") if isinstance(raw.get("buttons"), dict) else {}
    for key in DEFAULT_BUTTONS:
        value = buttons.get(key)
        if not isinstance(value, str) or len(value.strip()) < 3 or len(value) > 80 or "\n" in value or _PAID_WORD.search(value):
            continue   # tomt, for kort til at være entydigt, eller navnet på en betalt knap
        if key == "like_prefix" and any(p.startswith(value.lower()) for p in PAID_NAMES):
            continue   # fx "Send" ville også ramme "Send en rose"
        s["buttons"][key] = value if key == "like_prefix" else value.strip()   # like_prefix må slutte med mellemrum
    sched = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    s["schedule"]["enabled"] = sched.get("enabled") is True
    if isinstance(sched.get("time"), str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", sched["time"]):
        s["schedule"]["time"] = sched["time"]
    if sched.get("mode") in MODES:
        s["schedule"]["mode"] = sched["mode"]
    if isinstance(sched.get("last_run"), str) and re.fullmatch(r"\d{4}-\d\d-\d\d|", sched["last_run"]):
        s["schedule"]["last_run"] = sched["last_run"]
    s["accepted_terms"] = raw.get("accepted_terms") is True
    return s


def load_settings(path: Path) -> dict:
    return clean_settings(_read_json(path))


def save_settings(path: Path, settings: dict) -> dict:
    settings = clean_settings(settings)
    _write_json(path, settings)
    return settings


def run_limits(settings: dict, mode: str) -> tuple[int, int]:
    """(likes pr. dag, minutter pr. kørsel) for et tempo: egne grænser fra indstillinger, ellers tempoets standard."""
    own = settings.get("limits", {}).get(mode, {})
    return own.get("daily", MODES[mode]["daily"]), own.get("minutes", MODES[mode]["minutes"])


def schedule_due(schedule: dict, now: dt.datetime, window_minutes: int = 30) -> bool:
    """Skal den planlagte kørsel starte nu? Kun i et vindue lige efter klokkeslættet og højst én gang pr. dag."""
    if not schedule.get("enabled") or schedule.get("last_run") == now.date().isoformat():
        return False
    hh, mm = map(int, schedule.get("time", "18:00").split(":"))
    minutes_after = (now.hour * 60 + now.minute) - (hh * 60 + mm)
    return 0 <= minutes_after <= window_minutes
