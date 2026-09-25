$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
function Run-Step([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE)" }
}
Run-Step 'py' @('-3.12', '-m', 'venv', '.venv-windows')
$Python = Join-Path $PWD '.venv-windows\Scripts\python.exe'
Run-Step $Python @('-m', 'pip', 'install', '-r', 'requirements-desktop.txt')
Run-Step 'npm.cmd' @('ci')
Run-Step 'npm.cmd' @('run', 'assets')
Run-Step 'npm.cmd' @('run', 'build')
Run-Step $Python @('-m', 'PyInstaller', '--noconfirm', '--distpath', 'release', 'packaging/windows/PoseParallax.spec')
$Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$Iscc = if ($Compiler) { $Compiler.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
if (!(Test-Path $Iscc)) { throw 'Inno Setup 6 is required to build the installer. The portable app is in release\PoseParallax.' }
Run-Step $Iscc @('packaging/windows/installer.iss')
Write-Host 'Windows app and installer are in release\'
