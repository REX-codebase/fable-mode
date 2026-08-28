#requires -Version 5.1
<#
.SYNOPSIS
    One-command installer for Fable-Mode in an Antigravity-compatible host layout.
.DESCRIPTION
    Downloads the public REX-codebase repository archive, expands it in a
    temporary directory, runs the verified local installer, and optionally merges
    the fable-engine entry into the host MCP configuration without overwriting
    other servers.
#>
[CmdletBinding()]
param(
    [string]$TargetDir = "$HOME\.gemini",
    [switch]$SkipTests,
    [switch]$NoRegisterMcp,
    [switch]$KeepDownload
)

$ErrorActionPreference = "Stop"
# Pin the downloaded source to an immutable reviewed commit and verify the
# archive bytes before any installer code is executed. Update both values
# together for a release. The bootstrap itself is pinned separately in README.
$pinnedCommit = "2c049cb77a5ba5066d7bcbcf2f488c272b6c0195"
$expectedArchiveSha256 = "8d470ba5854c55cd6b23736e1fb28dfff8a9e8e703db25b2030e197a7b9ad85c"
$repoArchive = "https://api.github.com/repos/REX-codebase/fable-mode/zipball/$pinnedCommit"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("fable-mode-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempRoot "fable-mode.zip"

try {
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    Write-Host "[+] Downloading Fable-Mode from REX-codebase..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $repoArchive -OutFile $archivePath -Headers @{
        Accept = "application/vnd.github+json"
        "User-Agent" = "fable-mode-installer"
    }
    $actualArchiveSha256 = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualArchiveSha256 -ne $expectedArchiveSha256) {
        throw "Downloaded archive integrity check failed; no installer code was executed."
    }
    Write-Host "[OK] Verified commit $pinnedCommit and SHA-256 $actualArchiveSha256" -ForegroundColor Green

    Write-Host "[+] Expanding package..." -ForegroundColor Cyan
    Expand-Archive -Path $archivePath -DestinationPath $tempRoot -Force
    $sourceRoot = Get-ChildItem -Path $tempRoot -Directory |
        Where-Object { $_.FullName -ne $tempRoot } |
        Select-Object -First 1
    if (-not $sourceRoot -or -not (Test-Path (Join-Path $sourceRoot.FullName "install.ps1"))) {
        throw "Downloaded archive did not contain a valid Fable-Mode installer."
    }

    $installer = Join-Path $sourceRoot.FullName "install.ps1"
    $registerMcp = -not $NoRegisterMcp
    Write-Host "[+] Installing into the host-compatible layout..." -ForegroundColor Cyan
    & $installer `
        -TargetDir $TargetDir `
        -SkipTests:$SkipTests `
        -RegisterMcp:$registerMcp

    Write-Host "`n[OK] Fable-Mode is installed and ready." -ForegroundColor Green
} catch {
    Write-Error "Fable-Mode installation failed: $($_.Exception.Message)"
    exit 1
} finally {
    if (-not $KeepDownload -and (Test-Path $tempRoot)) {
        Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    } elseif ($KeepDownload) {
        Write-Host "[i] Download retained at: $tempRoot" -ForegroundColor Yellow
    }
}
