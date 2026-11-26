<#
Bygger Hinge Auto Swipe til Windows: kører testene, laver HingeAutoSwipe.exe (PyInstaller, én mappe),
en portabel zip og installeren (Inno Setup). Resultatet ligger i packaging\dist.

    powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1

Kræver uv (eller Python 3.12 via py-launcheren) og Inno Setup 6 (winget install JRSoftware.InnoSetup).
#>
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE) { throw "Fejlede med kode ${LASTEXITCODE}: $Command" }
}

$version = [regex]::Match((Get-Content ..\iphone\logic.py -Raw), 'VERSION = "([^"]+)"').Groups[1].Value
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$uv = Get-Command uv -ErrorAction SilentlyContinue
Write-Host "Hinge Auto Swipe $version"

if (-not (Test-Path $py)) {
    if ($uv) { Invoke-Checked { uv venv --python 3.12 .venv } } else { Invoke-Checked { py -3.12 -m venv .venv } }
}
if ($uv) { Invoke-Checked { uv pip install --python $py -r requirements-build.txt } }
else { Invoke-Checked { & $py -m pip install --disable-pip-version-check -r requirements-build.txt } }

Push-Location ..\iphone
try { Invoke-Checked { & $py -m unittest discover -s tests } } finally { Pop-Location }

if (-not (Test-Path icon.ico)) { Invoke-Checked { & $py make_icon.py } }
Invoke-Checked { & $py -m PyInstaller --noconfirm hinge.spec }

Compress-Archive -Path dist\HingeAutoSwipe -DestinationPath "dist\HingeAutoSwipe-$version-windows.zip" -Force

$iscc = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 mangler: winget install JRSoftware.InnoSetup" }
Invoke-Checked { & $iscc "/DAppVersion=$version" installer.iss }

Get-ChildItem dist -File | Format-Table Name, @{ n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } } -AutoSize
