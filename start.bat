@echo off
title Hinge Auto Swipe
cd /d "%~dp0iphone"
where python >nul 2>nul
if errorlevel 1 (
  echo Python mangler. Installerer Python 3.12 via winget ...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo Luk dette vindue og dobbeltklik start.bat igen.
  pause
  exit /b 1
)
python -m pip install -q --disable-pip-version-check -r requirements.txt
python app.py
pause
