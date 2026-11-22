"""Ren logik uden telefon og netværk: tempo, tidsrum og dagstæller. Alt tilfældigt kommer ind som parameter, så det kan testes."""
import datetime as dt
import json
from pathlib import Path


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


def load_state(path: Path, today: str | None = None) -> dict:
    """Dagens tæller. Nulstilles automatisk ved ny dato; ødelagt eller manglende fil giver en tom tæller."""
    today = today or dt.date.today().isoformat()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError
    except (OSError, ValueError):
        state = {}
    if state.get("date") != today:
        state = {"date": today, "likes_today": 0}
    state.setdefault("likes_today", 0)
    return state


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state), encoding="utf-8")
