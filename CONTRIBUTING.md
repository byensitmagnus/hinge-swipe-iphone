# Contributing

Thanks for helping. This is a small project; keep changes small too.

## Good first contributions

- **Button names for other Hinge languages.** Run `python inspect_screen.py` with Hinge open and send the names (`Synes godt om …`, `Send synes godt om`, `discover_screen`, …) in an issue or PR.
- **macOS / Linux notes.** Only Windows 11 is tested. If it works for you, say so (and what you changed).
- **Pacing ideas** that make the bot look less like a bot, with the reasoning.
- **A safe first-message flow** for *new, empty* matches only. It must never touch a conversation that already has messages.

## Rules

- Never add anything that taps a paid feature (Rose, Boost, subscriptions).
- Never add anything that sends messages without an explicit, separate opt-in flag.
- No secrets, tokens, accounts or screenshots of real people in issues or PRs.
- Run the tests before opening a PR: `cd iphone && python -m unittest discover -s tests`.

## Reporting a bug

Include your iOS version, Hinge language, the command you ran, and the last 20 lines of output. Remove names of people you saw.
