# Builds dist\WordPulse.exe, dist\WordPulse.scr (screensaver) and, if Inno Setup is installed,
# dist\WordPulse-Setup-<version>.exe.
#
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1
#
# Optional code signing (removes the "unknown publisher" warning on other PCs):
#   $env:WORDPULSE_SIGN_PFX = "C:\path\to\certificate.pfx"
#   $env:WORDPULSE_SIGN_PASSWORD = "..."     # if the certificate has one
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --user -q -r requirements.txt "pyinstaller>=6.10"

$version = (python -c "from src.version import APP_VERSION; print(APP_VERSION)").Trim()

# App icon, drawn from the same artwork as the tray icon
New-Item -ItemType Directory -Force assets | Out-Null
python -c "from src.core.tray import create_tray_image as c; c(256, 256).save('assets/wordpulse.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

python -m PyInstaller --noconfirm --clean wordpulse.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# The same program doubles as a screensaver; Windows just needs the .scr name
Copy-Item dist\WordPulse.exe dist\WordPulse.scr -Force

function Sign-File($path) {
    if (-not $env:WORDPULSE_SIGN_PFX) { return }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { Write-Warning "signtool.exe not found (install the Windows SDK); skipping signing"; return }
    $signArgs = @("sign", "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256", "/f", $env:WORDPULSE_SIGN_PFX)
    if ($env:WORDPULSE_SIGN_PASSWORD) { $signArgs += @("/p", $env:WORDPULSE_SIGN_PASSWORD) }
    & $signtool.FullName @signArgs $path
    if ($LASTEXITCODE -ne 0) { throw "Signing $path failed" }
}
Sign-File dist\WordPulse.exe
Sign-File dist\WordPulse.scr

# Installer (optional): needs Inno Setup 6
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" installer\wordpulse.iss
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
    Sign-File "dist\WordPulse-Setup-$version.exe"
    Write-Host "Built installer: dist\WordPulse-Setup-$version.exe" -ForegroundColor Green
} else {
    Write-Host "Inno Setup not found - skipped the installer (get it free from jrsoftware.org)." -ForegroundColor Yellow
}

Write-Host "Built: dist\WordPulse.exe and dist\WordPulse.scr (version $version)" -ForegroundColor Green
