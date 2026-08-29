# Compatibility shim for explicit Antigravity registration via the safe package installer.
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$DryRun,
    [string]$InstallDir,
    [string]$Workspace
)
$ErrorActionPreference = 'Stop'
$wrapper = Join-Path $PSScriptRoot 'fable_mode_entry.py'
# Explicitly enable the documented antigravity executable alias.  The helper
# still preserves unrelated Claude/Codex registrations and fails closed on
# unsupported host CLI state.
$arguments = @($wrapper, 'install', '--register-hosts', '--aliases')
if ($Yes) { $arguments += '--yes' }
if ($DryRun) { $arguments += '--dry-run' }
if ($InstallDir) { $arguments += @('--install-dir', $InstallDir) }
if ($Workspace) { $arguments += @('--workspace', $Workspace) }
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & $py.Source -3 @arguments
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python launcher `py` (or a Python 3 `python`) is required.' }
    $version = (& $python.Source --version 2>&1 | Out-String)
    if ($version -notmatch 'Python 3\.') { throw 'Fallback `python` is not Python 3.' }
    & $python.Source @arguments
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
