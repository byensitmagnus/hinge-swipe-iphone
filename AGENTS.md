# Instructions for coding agents

You are helping a person set up **Hinge Auto Swipe**: a Python tool in `iphone/` that drives the real Hinge app on their iPhone from their PC over USB.

## Set-up flow

1. `cd iphone && pip install -r requirements.txt`
2. `python make_ipa.py` builds `WebDriverAgentRunner.ipa`.
3. The **person** signs and installs it with Sideloadly using their own Apple ID, trusts the developer on the phone, and unlocks the phone. You cannot do these steps and must not ask for their passcode or Apple ID password. Walk them through `docs/index.html`.
4. Test in this order: `python swipe.py --dry`, then `python swipe.py --max 5`, then a normal run.

## Hard rules

- Never tap *Send a Rose* or any paid button. Never send messages.
- Do not raise the defaults (80 likes/day, 08:00–23:00, 30-minute sessions) unless the person explicitly asks, and tell them the ban risk first.
- Never enter a passcode or password on the person's behalf.
- Tell the person that automating Hinge is against Hinge's terms.

## Facts that save time

- The screen is 402×874 points. Hinge must stay open: the session is created with `shouldTerminateApp: False`.
- Buttons are found by accessibility name; they are Danish in the tested setup (`iphone/swipe.py` constants).
- Tests: `cd iphone && python -m unittest discover -s tests`.
- Auto-Lock must be *Never*, or the run stops with a "phone is locked" message.
