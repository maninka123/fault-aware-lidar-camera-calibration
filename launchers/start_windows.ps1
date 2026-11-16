$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$configuration = Join-Path $projectRoot '.runtime.json'
$interpreter = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $configuration) {
    $interpreter = (Get-Content -LiteralPath $configuration -Raw | ConvertFrom-Json).python
}
if (-not $interpreter -or -not (Test-Path -LiteralPath $interpreter)) {
    Write-Host 'Run Setup.bat once in the project folder, then open Start.bat.'
    exit 1
}
$windowed = Join-Path (Split-Path -Parent $interpreter) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowed)) { $windowed = $interpreter }
$script = Join-Path $projectRoot 'app\gui\research_gui.py'
Start-Process -FilePath $windowed -ArgumentList @('"' + $script + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden
