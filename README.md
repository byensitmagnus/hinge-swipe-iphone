<p align="center">
  <a href="https://byensitmagnus.github.io/hinge-swipe-iphone/"><img src="docs/banner.svg" alt="Hinge Auto Swipe. Your real iPhone, your PC, a calm human pace. No jailbreak, no fake API, open source." width="800"></a>
</p>

<p align="center">
  <a href="https://byensitmagnus.github.io/hinge-swipe-iphone/"><b>Setup guide (EN + DA)</b></a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#safety-and-pacing">Safety</a> ·
  <a href="#faq">FAQ</a>
</p>

<p align="center">
  <a href="https://github.com/byensitmagnus/hinge-swipe-iphone/stargazers"><img src="https://img.shields.io/github/stars/byensitmagnus/hinge-swipe-iphone?style=flat&color=a855f7&labelColor=14101f" alt="Stars"></a>
  <a href="https://github.com/byensitmagnus/hinge-swipe-iphone/network/members"><img src="https://img.shields.io/github/forks/byensitmagnus/hinge-swipe-iphone?style=flat&color=a855f7&labelColor=14101f" alt="Forks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a855f7?style=flat&labelColor=14101f" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-a855f7?style=flat&logo=python&logoColor=white&labelColor=14101f" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/PC-Windows%20(tested)-a855f7?style=flat&logo=windows&logoColor=white&labelColor=14101f" alt="Tested on Windows">
  <img src="https://img.shields.io/badge/iPhone-iOS%2017%2B-a855f7?style=flat&logo=apple&logoColor=white&labelColor=14101f" alt="iOS 17+">
</p>

## Start here

| You have | Go to |
|---|---|
| **An iPhone with Hinge, a USB cable and a PC** | The [setup guide](https://byensitmagnus.github.io/hinge-swipe-iphone/): about 10 minutes, English and Dansk. |
| **A coding agent (Claude Code, Codex, …)** | Point it at this repo and say *"set this up for my iPhone"*. [`AGENTS.md`](AGENTS.md) tells it how. |
| **Just curious** | Read [How it works](#how-it-works), then [Safety and pacing](#safety-and-pacing). |

## How it works

Hinge's own API is locked down, and fake clients get banned fast. This takes the other road: it drives the **real Hinge app on your real iPhone**, the way an app's UI test would.

| Step | What happens |
|---|---|
| **Connect** | Plug the iPhone into the PC. [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) opens a tunnel over USB. No admin rights, no jailbreak. |
| **Install once** | A small signed test app (Appium's [WebDriverAgent](https://github.com/appium/WebDriverAgent), built by `make_ipa.py`) is put on the phone with Sideloadly and a free Apple ID. |
| **Swipe** | `swipe.py` finds buttons **by name** (not by pixel position), taps *Like*, then *Send like*, and waits like a person would. |

Because it reads button names, it keeps working when Hinge shifts its layout around.

## Quick start

**Plug and play:** after the one-time phone set-up below, double-click `start.bat` (Windows) or `start.command` (Mac). It installs what it needs and opens the app in your browser: pick a mode, press **Start**, watch the live log and today's count, press **Stop**.

| Mode | Pace | Default cap | Risk |
|---|---|---|---|
| **Secure** | 8–18 s between likes, reads most profiles, long breaks | 50/day, 20 min | lowest |
| **Human** | 5–12 s, reads most profiles, 45–120 s breaks | 80/day, 30 min | normal (default) |
| **Fast** | ~8 s per like all in, no profile reading, short breaks | 200/day, 2 h | clearly higher ban risk |

Command line instead:

```powershell
git clone https://github.com/byensitmagnus/hinge-swipe-iphone.git
cd hinge-swipe-iphone/iphone
pip install -r requirements.txt
python make_ipa.py          # builds WebDriverAgentRunner.ipa
# sign + install it once with Sideloadly (free Apple ID): see the guide
python swipe.py --dry       # look, don't like
python swipe.py --max 5     # five likes, then stop
python swipe.py             # a normal 30-minute session (human mode)
python swipe.py --mode secure   # or --mode fast
python app.py               # the app UI
```

Keep the phone **unlocked and in the cable** (set *Settings → Display → Auto-Lock → Never*). Stop any time: create an empty file named `STOP` in `iphone/`, or press Ctrl+C.

## What it does

- Likes profiles in Hinge's Discover feed, one after another.
- **Three modes** (`--mode secure|human|fast`, see the table above). Human is the default: 5–12 s between likes, an occasional longer look, a 45–120 s break every 12–25 profiles, some scrolling before each like.
- **Cautious defaults:** 80 likes/day, 30-minute sessions, 08:00–23:00 only. All adjustable (`--daily`, `--minutes`, `--from-hour`, `--to-hour`).
- **Fast path:** fast mode finds the like button directly (~0.2 s) instead of reading the whole screen (~1.7 s), and falls back to the full check when anything looks different.
- Never taps the paid *Send a Rose*. Never sends messages.
- Stops on its own at the daily cap, outside the time window, when the phone locks, or after three unrecognised screens in a row.
- Accepts Hinge's random privacy pop-up so it doesn't block the run.

## Safety and pacing

Automating Hinge is **against Hinge's terms**. Your account can be limited or banned, and no pacing makes that risk zero. That is why the defaults are slow and capped, and why it never touches paid features or messages. Use it on your own account, at your own risk. Not affiliated with Hinge or Match Group. Don't use it to spam or harass anyone.

## FAQ

**Does it need a jailbreak?** No. A stock iPhone is enough.

**Does it cost anything?** No. A free Apple ID signs the test app. The signature lasts 7 days, then you re-sign it with Sideloadly.

**Can it send messages?** Not yet. Automatic first messages to *new* matches are planned; they need a real new match to build against safely.

**Is my password sent anywhere?** No. Nothing leaves your PC. The script talks to your phone over USB and to nothing else. Read [`swipe.py`](iphone/swipe.py) and [`wda.py`](iphone/wda.py): about 300 lines in total.

**It's in Danish?** The button names it looks for are Danish (the tested Hinge language). For another language change two constants in `swipe.py`; `python inspect_screen.py` prints the names Hinge uses on your screen.

**macOS or Linux?** pymobiledevice3 runs there too, so it should work, but only Windows 11 is tested so far. Reports welcome.

**Android?** Not supported. This uses Apple's UI-testing stack.

## Tested on

Windows 11 · iPhone (iOS 27.2) · Python 3.11 · pymobiledevice3 11.x · Appium WebDriverAgent v16.15.3 · Hinge with a Danish interface.

## Repository layout

| Path | What |
|---|---|
| `iphone/` | The iPhone swiper (Python): use this |
| `docs/index.html` | Step-by-step setup guide, English + Dansk |
| `experimental/rust-api-client/` | Older idea: an unofficial Hinge API client in Rust. Unverified against a real account; kept for reference |

```powershell
cd iphone
python -m unittest discover -s tests    # unit tests
```

## Contributing

Bug reports and pull requests are welcome, especially: more languages for the button names, macOS/Linux notes, and a safe first-message flow. See [CONTRIBUTING.md](CONTRIBUTING.md). Found a security problem? See [SECURITY.md](SECURITY.md).

## License

MIT, see [LICENSE](LICENSE). Made by [Byens IT](https://github.com/byensitmagnus).
