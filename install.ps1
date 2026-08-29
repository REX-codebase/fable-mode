# Source-mode compatibility shim. The implementation lives in fable_mode.installer.
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$RegisterHosts,
    [switch]$Aliases,
    [switch]$DryRun,
    [string]$InstallDir,
    [string]$Workspace
)
$ErrorActionPreference = 'Stop'
$wrapper = Join-Path $PSScriptRoot 'fable_mode_entry.py'
$arguments = @($wrapper, 'install')
if ($Yes) { $arguments += '--yes' }
if ($RegisterHosts) { $arguments += '--register-hosts' }
if ($Aliases) { $arguments += '--aliases' }
if ($DryRun) { $arguments += '--dry-run' }
if ($InstallDir) { $arguments += @('--install-dir', $InstallDir) }
if ($Workspace) { $arguments += @('--workspace', $Workspace) }
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & $py.Source -3 @arguments
} else {
    # Fallback only when the documented launcher is unavailable and `python`
    # explicitly reports Python 3 (avoid accidentally invoking Python 2).
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python launcher `py` (or a Python 3 `python`) is required.' }
    $version = (& $python.Source --version 2>&1 | Out-String)
    if ($version -notmatch 'Python 3\.') { throw 'Fallback `python` is not Python 3.' }
    & $python.Source @arguments
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
