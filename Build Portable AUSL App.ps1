param(
    [switch]$NonInteractive,
    [switch]$AcceptRuntimeHash,
    [ValidateSet("core", "approved-enrichment")]
    [string]$DistributionProfile = "core",
    [string]$PythonVersion = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "The AUSL virtual environment was not found. Run 'Setup AUSL Environment.bat' first."
}

$requiredExports = @(
    "data\exports\ausl_rosters.xlsx",
    "data\exports\ausl_season_stats.xlsx",
    "data\exports\ausl_career_stats.xlsx",
    "data\exports\ausl_team_context.xlsx",
    "data\exports\update_manifest.json",
    "data\exports\refresh_attempt.json"
)

function Copy-ShareableExports {
    param([string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($relativePath in $requiredExports) {
        $source = Join-Path $PSScriptRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required data export is missing: $relativePath"
        }
    }
    & $python (Join-Path $PSScriptRoot "tools\build_distribution_profile.py") `
        (Join-Path $PSScriptRoot "data\exports") `
        $Destination `
        --profile $DistributionProfile
    if ($LASTEXITCODE -ne 0) {
        throw "Distribution profile staging failed with exit code $LASTEXITCODE."
    }
}

function Confirm-CleanDistribution {
    param([string[]]$Targets)
    & $python (Join-Path $PSScriptRoot "tools\verify_distribution.py") `
        --profile $DistributionProfile `
        @Targets
    if ($LASTEXITCODE -ne 0) {
        throw "Distribution privacy verification failed with exit code $LASTEXITCODE."
    }
}

function Write-PortableChecksum {
    param([string]$ArchivePath)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArchivePath).Hash.ToLowerInvariant()
    $fileName = [System.IO.Path]::GetFileName($ArchivePath)
    Set-Content -LiteralPath "$ArchivePath.sha256.txt" -Value "$hash  $fileName" -Encoding Ascii
}

# The grafted Tk files must come from a full CPython install with the same
# minor version as the embedded runtime, so the local interpreter decides which
# embeddable archive is downloaded unless the caller overrides it.
$pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonBase -PathType Container)) {
    throw "Could not resolve the base Python installation for the AUSL virtual environment."
}
if (-not $PythonVersion) {
    $PythonVersion = (& $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve the local Python version."
    }
}
if ($PythonVersion -notmatch '^3\.12\.\d+$') {
    throw "The portable package targets Python 3.12.x, but found $PythonVersion."
}

$libDir = Join-Path $pythonBase "Lib"
$dllsDir = Join-Path $pythonBase "DLLs"
$tclDir = Join-Path $pythonBase "tcl"
foreach ($required in @($libDir, $dllsDir, $tclDir)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) {
        throw "The base Python installation is missing a required folder: $required"
    }
}

$dist = Join-Path $PSScriptRoot "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$cache = Join-Path $dist "runtime-downloads"
New-Item -ItemType Directory -Force -Path $cache | Out-Null

$archiveName = "python-$PythonVersion-embed-amd64.zip"
$archivePath = Join-Path $cache $archiveName
$archiveUrl = "https://www.python.org/ftp/python/$PythonVersion/$archiveName"
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    Write-Host "Downloading the official CPython $PythonVersion embeddable runtime..."
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing
}

$pinArguments = @(
    (Join-Path $PSScriptRoot "tools\build_portable_runtime.py"),
    "pin",
    $archivePath
)
if ($AcceptRuntimeHash) { $pinArguments += "--accept" }
& $python @pinArguments
if ($LASTEXITCODE -ne 0) {
    throw "The embeddable runtime archive failed SHA-256 pin verification."
}

$package = Join-Path $dist "AUSL Broadcast Stats Portable"
if (Test-Path $package) { Remove-Item $package -Recurse -Force }
New-Item -ItemType Directory -Force -Path $package | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $package "src") | Out-Null

Copy-Item "src\*.py" (Join-Path $package "src") -Force
Copy-Item "README.txt" $package -Force
# Shipped as provenance only. The recipient never installs these; the manifest
# hashes them so the bundled runtime can be audited against its pinned set.
Copy-Item "requirements.txt" $package -Force
Copy-Item "constraints.txt" $package -Force
Copy-ShareableExports -Destination (Join-Path $package "data\exports")

Write-Host "Staging the bundled CPython $PythonVersion runtime..."
& $python (Join-Path $PSScriptRoot "tools\build_portable_runtime.py") `
    stage `
    $package `
    --embeddable-archive $archivePath `
    --lib-dir $libDir `
    --dlls-dir $dllsDir `
    --tcl-dir $tclDir
if ($LASTEXITCODE -ne 0) {
    throw "Portable runtime staging failed with exit code $LASTEXITCODE."
}

$sitePackages = Join-Path $package "runtime\Lib\site-packages"
Write-Host "Installing pinned AUSL libraries into the bundled runtime..."
& $python -m pip install `
    --disable-pip-version-check `
    --no-compile `
    --only-binary=:all: `
    --implementation cp `
    --python-version 3.12 `
    --platform win_amd64 `
    --target $sitePackages `
    -r requirements.txt `
    -c constraints.txt
if ($LASTEXITCODE -ne 0) {
    throw "Bundled runtime dependency installation failed with exit code $LASTEXITCODE."
}

& $python (Join-Path $PSScriptRoot "tools\build_portable_runtime.py") `
    prune (Join-Path $package "runtime")
if ($LASTEXITCODE -ne 0) {
    throw "Portable runtime pruning failed with exit code $LASTEXITCODE."
}

& $python (Join-Path $PSScriptRoot "tools\build_portable_runtime.py") `
    verify (Join-Path $package "runtime")
if ($LASTEXITCODE -ne 0) {
    throw "The staged portable runtime is incomplete."
}

$startHere = Join-Path $package "START HERE - Portable Version.txt"
@"
AUSL Broadcast Stats - Portable Version

This folder already contains everything the app needs, including its own copy
of Python. Nothing has to be installed.

BEFORE YOU UNZIP (this is the step that avoids most Windows warnings)
1. Right-click the ZIP file you downloaded and choose Properties.
2. If you see an "Unblock" checkbox near the bottom, tick it and click OK.
3. Now extract the ZIP to a normal folder, such as your Desktop or Documents.

Unblocking before extraction clears the downloaded-file marker from every file
inside, so Windows does not warn again for each one.

TO START THE APP
Double-click:
  Start AUSL Broadcast Stats.bat

The first launch can take a few seconds while Windows scans the new files.

IF NOTHING APPEARS
Double-click:
  Troubleshoot AUSL Portable.bat
That runs the same app with a visible console window so any error stays on
screen. Send that text back to whoever shared this package.

NOTES
- Keep this folder together. The "runtime" folder is the bundled Python and the
  app will not start without it.
- Do not run the app from inside the ZIP viewer. Extract it first.
- Windows may still show a blue "Windows protected your PC" screen if the ZIP
  was not unblocked first. Choose "More info" and then "Run anyway" if you
  trust the sender, or unblock the ZIP and extract it again.
"@ | Set-Content -Path $startHere -Encoding UTF8

& $python (Join-Path $PSScriptRoot "tools\generate_portable_source_manifest.py") $package
if ($LASTEXITCODE -ne 0) {
    throw "Portable manifest generation failed with exit code $LASTEXITCODE."
}

$zip = Join-Path $dist "AUSL-Broadcast-Stats-Portable-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Confirm-CleanDistribution -Targets @($package)

# Deflate keeps the package near 30 MB instead of roughly 90 MB. It stays a
# plain ZIP that Defender and mail scanners can read without any extra tooling.
Write-Host "Compressing the portable package..."
& $python (Join-Path $PSScriptRoot "tools\create_portable_zip.py") `
    --source $package --output $zip --deflate
if ($LASTEXITCODE -ne 0) {
    throw "Portable ZIP creation failed with exit code $LASTEXITCODE."
}

Confirm-CleanDistribution -Targets @($zip)
Write-PortableChecksum -ArchivePath $zip

$zipSize = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "Finished. Portable no-install package:"
Write-Host $zip
Write-Host "Size: $zipSize MB"
Write-Host "Checksum:"
Write-Host "$zip.sha256.txt"
Write-Host ""
Write-Host "This package is too large for a Gmail attachment, and Gmail blocks"
Write-Host "archives that contain python.exe. Share it with a Drive/OneDrive"
Write-Host "link and send the .sha256.txt contents in the email body."
if (-not $NonInteractive) {
    Read-Host "Press Enter to close"
}
