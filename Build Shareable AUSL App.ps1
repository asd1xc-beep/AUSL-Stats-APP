param([switch]$NonInteractive)

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

function Write-DistributionManifest {
    param([string]$Destination)
    & $python (Join-Path $PSScriptRoot "tools\generate_distribution_manifest.py") $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "Distribution manifest generation failed with exit code $LASTEXITCODE."
    }
}

function Copy-ShareableExports {
    param([string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($relativePath in $requiredExports) {
        $source = Join-Path $PSScriptRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required data export is missing: $relativePath"
        }
        Copy-Item -LiteralPath $source -Destination $Destination -Force
    }
    Write-DistributionManifest -Destination $Destination
}

function Confirm-CleanDistribution {
    param([string[]]$Targets)
    & $python (Join-Path $PSScriptRoot "tools\verify_distribution.py") @Targets
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

Write-Host "Installing pinned AUSL packaging requirements..."
& $python -m pip install --disable-pip-version-check -r requirements-build.txt -c constraints.txt
if ($LASTEXITCODE -ne 0) {
    throw "Pinned packaging dependency installation failed with exit code $LASTEXITCODE."
}

# Some portable Python 3.12 runtimes keep tkinter in the base interpreter's
# Lib directory, which PyInstaller does not always add to module analysis.
$tkinterLib = (& $python -c "from pathlib import Path; import tkinter; print(Path(tkinter.__file__).resolve().parents[1])").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $tkinterLib "tkinter\__init__.py") -PathType Leaf)) {
    throw "Tkinter could not be resolved from the pinned Python runtime."
}
$pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
$tclRoot = Join-Path $pythonBase "tcl"
foreach ($requiredTkData in @("tcl8.6", "tk8.6")) {
    if (-not (Test-Path -LiteralPath (Join-Path $tclRoot $requiredTkData) -PathType Container)) {
        throw "Required Tk runtime data is missing: $requiredTkData"
    }
}

Write-Host "Building the Windows AUSL application..."
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --noupx `
    --windowed `
    --name "AUSL Broadcast Stats" `
    --paths src `
    --paths $tkinterLib `
    --add-data "$tclRoot\tcl8.6;_tcl_data" `
    --add-data "$tclRoot\tk8.6;_tk_data" `
    --add-data "$tkinterLib\tkinter;tkinter" `
    --collect-all pandas `
    --collect-all certifi `
    --hidden-import tkinter `
    --hidden-import _tkinter `
    --hidden-import pypdf `
    --hidden-import openpyxl `
    --hidden-import certifi `
    src\ausl_stats_app.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$package = Join-Path $PSScriptRoot "dist\AUSL Broadcast Stats"
$tkinterCache = Join-Path $package "_internal\tkinter\__pycache__"
if (Test-Path -LiteralPath $tkinterCache -PathType Container) {
    Remove-Item -LiteralPath $tkinterCache -Recurse -Force
}
$exports = Join-Path $package "data\exports"
Copy-ShareableExports -Destination $exports
Copy-Item "README.txt" $package -Force

$zip = Join-Path $PSScriptRoot "dist\AUSL-Broadcast-Stats-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Confirm-CleanDistribution -Targets @($package)
Write-Host "Compressing the shareable app..."
& $python (Join-Path $PSScriptRoot "tools\create_portable_zip.py") --source $package --output $zip
if ($LASTEXITCODE -ne 0) {
    throw "Portable Windows ZIP creation failed with exit code $LASTEXITCODE."
}

$sourcePackage = Join-Path $PSScriptRoot "dist\AUSL Broadcast Stats Source"
if (Test-Path $sourcePackage) { Remove-Item $sourcePackage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $sourcePackage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $sourcePackage "src") | Out-Null
Copy-Item "src\*.py" (Join-Path $sourcePackage "src") -Force
Copy-Item "requirements.txt" $sourcePackage -Force
Copy-Item "constraints.txt" $sourcePackage -Force
Copy-Item "README.txt" $sourcePackage -Force
Copy-Item "Setup AUSL Environment.bat" $sourcePackage -Force
Copy-Item "Launch AUSL Stats App.bat" $sourcePackage -Force
Copy-Item "Update AUSL Database.bat" $sourcePackage -Force
Copy-ShareableExports -Destination (Join-Path $sourcePackage "data\exports")

$sourceReadme = Join-Path $sourcePackage "START HERE - Safer No-EXE Version.txt"
@"
AUSL Broadcast Stats - Safer No-EXE Version

This package does not include a bundled Windows .exe. That makes it less
convenient on first run, but it is usually less likely to be auto-quarantined
by Windows Defender than a newly built unsigned executable.

First-time setup:
1. Double-click Setup AUSL Environment.bat
2. Wait for the Python libraries to install.
3. Double-click Launch AUSL Stats App.bat

If Windows warns about running a batch file from the internet, that is expected
for an unknown downloaded file. This version should avoid the higher-risk
pattern of an unsigned, bundled executable inside a ZIP.
"@ | Set-Content -Path $sourceReadme -Encoding UTF8

& $python (Join-Path $PSScriptRoot "tools\generate_portable_source_manifest.py") $sourcePackage
if ($LASTEXITCODE -ne 0) {
    throw "Portable source manifest generation failed with exit code $LASTEXITCODE."
}

$sourceZip = Join-Path $PSScriptRoot "dist\AUSL-Broadcast-Stats-Safer-No-EXE.zip"
if (Test-Path $sourceZip) { Remove-Item $sourceZip -Force }
Confirm-CleanDistribution -Targets @($sourcePackage)
Write-Host "Compressing the safer no-EXE source package..."
& $python (Join-Path $PSScriptRoot "tools\create_portable_zip.py") --source $sourcePackage --output $sourceZip
if ($LASTEXITCODE -ne 0) {
    throw "Portable source ZIP creation failed with exit code $LASTEXITCODE."
}

Confirm-CleanDistribution -Targets @($zip, $sourceZip)
Write-PortableChecksum -ArchivePath $zip
Write-PortableChecksum -ArchivePath $sourceZip

Write-Host ""
Write-Host "Finished. Standard EXE ZIP:"
Write-Host $zip
Write-Host "Checksum:"
Write-Host "$zip.sha256.txt"
Write-Host ""
Write-Host "Finished. Lower-risk no-EXE ZIP:"
Write-Host $sourceZip
Write-Host "Checksum:"
Write-Host "$sourceZip.sha256.txt"
if (-not $NonInteractive) {
    Read-Host "Press Enter to close"
}
