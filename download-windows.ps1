# Download and install the latest Fable-Mode Windows x86_64 release.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string] $InstallDir = (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'fable-mode')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = 'REX-codebase/fable-mode'
$ApiUrl = "https://api.github.com/repos/$Repository/releases/latest"
$TempDir = $null

function Fail([string] $Message) {
    throw "download-windows: ERROR: $Message"
}

try {
    # Windows PowerShell does not expose $IsWindows; this check works in both
    # Windows PowerShell 5.1 and PowerShell 7.  Only the published target is
    # accepted, rather than relying on a downloaded binary to fail later.
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        Fail 'this downloader supports Windows only'
    }
    $nativeArchitecture = $env:PROCESSOR_ARCHITEW6432
    if ([string]::IsNullOrEmpty($nativeArchitecture)) {
        $nativeArchitecture = $env:PROCESSOR_ARCHITECTURE
    }
    if ($nativeArchitecture -ne 'AMD64' -or -not [Environment]::Is64BitOperatingSystem) {
        Fail "unsupported Windows architecture '$nativeArchitecture' (supported: x86_64/AMD64)"
    }

    # New-TemporaryFile creates a file with a random name.  Replace that file
    # with a directory so all untrusted downloads remain private and scoped.
    $temporaryMarker = New-TemporaryFile
    $TempDir = $temporaryMarker.FullName
    Remove-Item -LiteralPath $TempDir -Force
    New-Item -ItemType Directory -LiteralPath $TempDir -Force | Out-Null

    $headers = @{
        Accept = 'application/vnd.github+json'
        'User-Agent' = 'fable-mode-release-downloader'
    }
    $releaseFile = Join-Path $TempDir 'release.json'
    try {
        Invoke-WebRequest -Uri $ApiUrl -Headers $headers -UseBasicParsing -OutFile $releaseFile
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        if ($statusCode -eq 404) {
            Fail 'no GitHub Release exists yet for this repository'
        }
        Fail "could not contact the GitHub Releases API$(if ($statusCode) { " (HTTP $statusCode)" })"
    }

    try {
        $release = Get-Content -LiteralPath $releaseFile -Raw | ConvertFrom-Json
    }
    catch {
        Fail 'GitHub returned an invalid release JSON response'
    }
    if ($null -eq $release -or $null -eq $release.tag_name) {
        Fail 'latest release did not contain a tag name'
    }
    $tag = [string]$release.tag_name
    if ($tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
        Fail "latest release has an unsupported tag '$tag'"
    }
    if ($null -eq $release.assets) {
        Fail 'latest release did not contain a usable assets list'
    }

    $archiveName = "fable-mode-$tag-windows-x86_64.zip"
    $expectedArchiveUrl = "https://github.com/$Repository/releases/download/$tag/$archiveName"
    $expectedSumsUrl = "https://github.com/$Repository/releases/download/$tag/SHA256SUMS"
    $archiveAsset = @($release.assets | Where-Object { [string]$_.name -ceq $archiveName })
    $sumsAsset = @($release.assets | Where-Object { [string]$_.name -ceq 'SHA256SUMS' })
    if ($archiveAsset.Count -eq 0) {
        Fail "latest release has no Windows x86_64 asset named '$archiveName'"
    }
    if ($archiveAsset.Count -ne 1) {
        Fail "release contains duplicate asset '$archiveName'"
    }
    if ($sumsAsset.Count -eq 0) {
        Fail 'latest release has no SHA256SUMS asset'
    }
    if ($sumsAsset.Count -ne 1) {
        Fail 'release contains duplicate SHA256SUMS assets'
    }
    $archiveUrl = [string]$archiveAsset[0].browser_download_url
    $sumsUrl = [string]$sumsAsset[0].browser_download_url
    if ($archiveUrl -cne $expectedArchiveUrl) {
        Fail "release asset '$archiveName' has an unexpected download URL"
    }
    if ($sumsUrl -cne $expectedSumsUrl) {
        Fail 'release SHA256SUMS asset has an unexpected download URL'
    }

    $archiveFile = Join-Path $TempDir $archiveName
    $sumsFile = Join-Path $TempDir 'SHA256SUMS'
    try {
        Invoke-WebRequest -Uri $archiveUrl -Headers $headers -UseBasicParsing -OutFile $archiveFile
        Invoke-WebRequest -Uri $sumsUrl -Headers $headers -UseBasicParsing -OutFile $sumsFile
    }
    catch {
        Fail 'could not download the selected release assets'
    }

    # Parse only a strict SHA-256 line whose filename is the expected basename.
    # Checksum content is data and is never evaluated as PowerShell code.
    $checksum = $null
    foreach ($line in (Get-Content -LiteralPath $sumsFile)) {
        if ($line -match '^\s*([0-9A-Fa-f]{64})\s+\*?([^\s]+)\s*$' -and $Matches[2] -ceq $archiveName) {
            if ($null -ne $checksum) {
                Fail "SHA256SUMS has duplicate checksums for '$archiveName'"
            }
            $checksum = $Matches[1].ToLowerInvariant()
        }
    }
    if ($null -eq $checksum) {
        Fail "SHA256SUMS has no unambiguous checksum for '$archiveName'"
    }
    $actualChecksum = (Get-FileHash -LiteralPath $archiveFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualChecksum -cne $checksum) {
        Fail 'SHA-256 checksum mismatch; archive was not extracted'
    }

    # Expand only after verification.  Inspect the ZIP entries first so a
    # path-traversal entry or unexpected layout is rejected before extraction.
    # Expand-Archive does not execute files; this script never launches the
    # downloaded executable.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archiveFile)
    try {
        $entries = @($zip.Entries)
        if ($entries.Count -ne 1 -or $entries[0].FullName -cne 'fable-mode.exe') {
            Fail "downloaded archive has an unexpected layout; refusing to extract"
        }
    }
    finally {
        $zip.Dispose()
    }
    $extractDir = Join-Path $TempDir 'extracted'
    Expand-Archive -LiteralPath $archiveFile -DestinationPath $extractDir -Force
    $executable = Join-Path $extractDir 'fable-mode.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        Fail "archive did not contain executable 'fable-mode.exe' at its root"
    }
    $destination = [System.IO.Path]::GetFullPath($InstallDir)
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        Fail "install path exists but is not a directory: $destination"
    }
    New-Item -ItemType Directory -LiteralPath $destination -Force | Out-Null
    $outputFile = Join-Path $destination 'fable-mode.exe'
    # Copy to a same-directory temporary name then rename, avoiding a partial
    # executable if copying is interrupted.  Move-Item never executes it.
    $temporaryOutput = Join-Path $destination ('.fable-mode.exe.tmp.' + [Guid]::NewGuid().ToString('N'))
    try {
        Copy-Item -LiteralPath $executable -Destination $temporaryOutput -Force
        Move-Item -LiteralPath $temporaryOutput -Destination $outputFile -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryOutput) {
            Remove-Item -LiteralPath $temporaryOutput -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "Installed verified executable: $outputFile"
    Write-Host "Next: & `"$outputFile`" install --yes"
}
finally {
    if ($null -ne $TempDir -and (Test-Path -LiteralPath $TempDir)) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
