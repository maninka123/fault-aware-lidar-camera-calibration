$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
function New-AppShortcut {
    $shellObject = New-Object -ComObject WScript.Shell
    $shortcut = $shellObject.CreateShortcut((Join-Path $projectRoot 'Fault-Aware Calibration.lnk'))
    $shortcut.TargetPath = Join-Path $projectRoot 'Start.bat'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = (Join-Path $projectRoot 'app\gui\assets\app_icon.ico') + ',0'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}
$candidates = @(@('py.exe', '-3.11'), @('py.exe', '-3.10'), @('python.exe'), @("$env:USERPROFILE\anaconda3\python.exe"))
foreach ($candidate in $candidates) {
    $candidateExecutable = $candidate[0]
    $candidateArguments = @($candidate | Select-Object -Skip 1)
    if (-not (Get-Command $candidateExecutable -ErrorAction SilentlyContinue)) { continue }
    try {
        & $candidateExecutable @candidateArguments -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,10),(3,11)) else 1)" 2>$null
    } catch { continue }
    if ($LASTEXITCODE -eq 0) {
        & $candidateExecutable @candidateArguments "$PSScriptRoot\setup_source.py"
        if ($LASTEXITCODE -eq 0) { New-AppShortcut }
        exit $LASTEXITCODE
    }
}
Add-Type -AssemblyName System.Windows.Forms
$picker = New-Object System.Windows.Forms.OpenFileDialog
$picker.Title = 'Select Python 3.10 or 3.11 (python.exe) for one-time setup'
$picker.Filter = 'Python interpreter (python.exe)|python.exe'
if ($picker.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    & $picker.FileName "$PSScriptRoot\setup_source.py"
    if ($LASTEXITCODE -eq 0) { New-AppShortcut }
    exit $LASTEXITCODE
}
Write-Host 'Setup cancelled. Use the portable EXE package if Python is not installed.'
exit 1
