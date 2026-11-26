# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: Hinge Auto Swipe som én mappe med HingeAutoSwipe.exe (vinduesapp uden konsol).
# Køres af build_windows.ps1. Testet med Python 3.12, PyInstaller 6.22.3, pymobiledevice3 11.61.1 og
# pywebview 5.4 (se requirements-build.txt) – inkl. iOS 17+-tunnelen.
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

HERE = Path(SPECPATH)
SRC = HERE.parent / "iphone"
VERSION = re.search(r'^VERSION = "(.+)"', (SRC / "logic.py").read_text(encoding="utf-8"), re.M).group(1)
NUMS = tuple(int(n) for n in VERSION.split(".")) + (0,)

binaries = collect_dynamic_libs("pytun_pmd3")    # wintun.dll indlæses, når tunnel-koden importeres
datas = [(str(SRC / "ui.html"), ".")]            # app.py finder den via sys._MEIPASS
datas += copy_metadata("pyimg4")                 # pyimg4 læser sin egen version ved import
datas += collect_data_files("pymobiledevice3")   # ressourcefiler (1,3 MB), for en sikkerheds skyld

version = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Byens IT"),
            StringStruct("FileDescription", "Hinge Auto Swipe"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "HingeAutoSwipe"),
            StringStruct("LegalCopyright", "Copyright (c) 2026 Byens IT. MIT License."),
            StringStruct("OriginalFilename", "HingeAutoSwipe.exe"),
            StringStruct("ProductName", "Hinge Auto Swipe"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    [str(SRC / "app.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    # Kun størrelse (97 → 61 MB): IPython hentes dovent af pymobiledevice3's shell-hjælper og trækker jedi med;
    # PIL kommer kun via IPython og pygments.
    excludes=["IPython", "PIL"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HingeAutoSwipe",
    console=False,
    upx=False,   # UPX kan ødelægge WebView2-DLL'er og giver falske antivirus-alarmer
    icon=str(HERE / "icon.ico"),
    version=version,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="HingeAutoSwipe")
