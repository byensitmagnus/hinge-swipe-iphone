@echo off
title Hinge Auto Swipe
cd /d "%~dp0iphone"
rem "where python" kan ramme Microsoft Store-genvejen, saa vi tjekker at Python faktisk kan koere.
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if not defined PY python --version >nul 2>nul && set PY=python
if not defined PY (
  echo Python mangler. Installerer Python 3.12 via winget ...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo Luk dette vindue og dobbeltklik start.bat igen.
  pause
  exit /b 1
)
%PY% -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Installation af pakker fejlede - se fejlen ovenfor.
  pause
  exit /b 1
)
%PY% app.py
pause
