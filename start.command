#!/bin/bash
# Dobbeltklik på Mac: installerer pakker første gang og åbner appen i browseren.
cd "$(dirname "$0")/iphone" || exit 1
if ! command -v python3 >/dev/null; then
  echo "Python 3 mangler. Installer det fra https://www.python.org/downloads/ og dobbeltklik igen."
  read -r -p "Tryk Enter for at lukke."
  exit 1
fi
python3 -m pip install -q --disable-pip-version-check -r requirements.txt
python3 app.py
