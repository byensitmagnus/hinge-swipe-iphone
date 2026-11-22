# Hinge Auto Swipe

**Let a script swipe Hinge on your real iPhone — from your PC, at a calm human pace.**

It drives the real Hinge app over USB, the way a UI test would. No fake API client, no jailbreak, nothing installed on the phone except a small signed test app. It presses buttons by name, so it also works when Hinge changes its layout.

> 📖 **[Setup guide (10 minutes, English + Dansk)](https://byensitmagnus.github.io/hinge-swipe-iphone/)**

## Quick start

```powershell
git clone https://github.com/byensitmagnus/hinge-swipe-iphone.git
cd hinge-swipe-iphone/iphone
pip install -r requirements.txt
python make_ipa.py          # builds WebDriverAgentRunner.ipa
# sign + install it once with Sideloadly (free Apple ID) – see the guide
python swipe.py --dry       # look, don't like
python swipe.py --max 5     # five likes, then stop
python swipe.py             # a normal session
```

Stop any time: create an empty file named `STOP` in `iphone/`, or press Ctrl+C.

## What it does

- Likes profiles in Hinge's Discover feed, one after another.
- Human-like pacing: 5–12 s between likes, an occasional longer look, a 45–120 s break every 12–25 profiles, a little scrolling before each like.
- Cautious defaults: **80 likes/day, 30-minute sessions, 08:00–23:00 only**. All adjustable.
- Never taps the paid *Send a Rose* button. Never sends messages.
- Stops on its own when the daily cap is reached, the time window ends, or it lands on screens it doesn't recognise three times in a row.
- Accepts Hinge's random privacy pop-up so it doesn't block the run.

## Not built yet

- Automatic first message to new matches (planned; needs a real new match to verify safely).

## Tested on

Windows 11 · iPhone (iOS 27.2) · Python 3.11 · pymobiledevice3 11.x · Appium WebDriverAgent v16.15.3 · Hinge with a Danish interface. Button names are Danish; for another language change two constants in `iphone/swipe.py` (`python inspect_screen.py` prints the names Hinge uses).

## ⚠️ Read before use

Automating Hinge is against Hinge's terms. Your account can be limited or banned, and no pacing makes that risk zero. This is for your own account, at your own risk. The project is not affiliated with Hinge or Match Group. Don't use it to spam or to harass anyone.

## Repository layout

| Path | What |
|---|---|
| `iphone/` | The iPhone swiper (Python) — use this |
| `docs/index.html` | Step-by-step setup guide, English + Dansk |
| `experimental/rust-api-client/` | Older idea: an unofficial Hinge API client in Rust. Unverified against a real account; kept for reference |

## Tests

```powershell
cd iphone
python -m unittest discover -s tests
```

## License

MIT — see [LICENSE](LICENSE).
