# WordPulse PowerShell Launcher
param (
    [switch]$Demo,
    [string]$Style = "ship",
    [string]$Mode = "fullscreen"
)

$argsList = @()
if ($Demo) { $argsList += "--demo" }
if ($Style) { $argsList += "--style"; $argsList += $Style }
if ($Mode) { $argsList += "--mode"; $argsList += $Mode }

Write-Host "Launching WordPulse ($Style, $Mode)..." -ForegroundColor Cyan
python run_wordpulse.py @argsList

