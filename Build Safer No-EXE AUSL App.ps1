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
    "data\exports\update_manifest.json"
)

function Write-DistributionManifest {
    param([string]$Destination)
    $updateManifestPath = Join-Path $Destination "update_manifest.json"
    try {
        $updateManifest = Get-Content -LiteralPath $updateManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Required update manifest could not be read: $($_.Exception.Message)"
    }
    $snapshotUpdatedAt = [string]$updateManifest.updated_at
    if ([string]::IsNullOrWhiteSpace($snapshotUpdatedAt)) {
        throw "Required update manifest has no updated_at timestamp."
    }

    $manifestFiles = @()
    foreach ($relativePath in $requiredExports) {
        $name = Split-Path -Leaf $relativePath
        $path = Join-Path $Destination $name
        $manifestFiles += [ordered]@{
            name = $name
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
            bytes = (Get-Item -LiteralPath $path).Length
            validation = "validated_phase_1_core"
        }
    }
    [ordered]@{
        schema_version = 1
        snapshot_updated_at = $snapshotUpdatedAt
        files = $manifestFiles
        purpose = "Phase 1 distributable core snapshot; unverified enrichment is intentionally omitted."
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Destination "distribution_manifest.json") -Encoding UTF8
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

$dist = Join-Path $PSScriptRoot "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null

$sourcePackage = Join-Path $dist "AUSL Broadcast Stats Source"
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

$sourceZip = Join-Path $dist "AUSL-Broadcast-Stats-Safer-No-EXE.zip"
if (Test-Path $sourceZip) { Remove-Item $sourceZip -Force }

Confirm-CleanDistribution -Targets @($sourcePackage)
Write-Host "Compressing the safer no-EXE package..."
& $python (Join-Path $PSScriptRoot "tools\create_portable_zip.py") --source $sourcePackage --output $sourceZip
if ($LASTEXITCODE -ne 0) {
    throw "Portable ZIP creation failed with exit code $LASTEXITCODE."
}

Confirm-CleanDistribution -Targets @($sourceZip)
Write-PortableChecksum -ArchivePath $sourceZip

Write-Host ""
Write-Host "Finished. Lower-risk no-EXE ZIP:"
Write-Host $sourceZip
Write-Host "Checksum:"
Write-Host "$sourceZip.sha256.txt"
if (-not $NonInteractive) {
    Read-Host "Press Enter to close"
}
