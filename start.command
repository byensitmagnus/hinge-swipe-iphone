#!/bin/bash
# Dobbeltklik på Mac: laver et lokalt Python-miljø første gang, installerer pakker og åbner appen i browseren.
cd "$(dirname "$0")/iphone" || exit 1
fail() { echo "$1"; read -r -p "Tryk Enter for at lukke."; exit 1; }
command -v python3 >/dev/null || fail "Python 3 mangler. Installer det fra https://www.python.org/downloads/ og dobbeltklik igen."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "Python er for gammel (kræver 3.9+). Installer en nyere fra python.org."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || fail "Kunne ikke lave Python-miljøet (.venv)."
fi
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt || fail "Installation af pakker fejlede – se fejlen ovenfor."
.venv/bin/python app.py
