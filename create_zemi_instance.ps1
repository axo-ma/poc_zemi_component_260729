[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstanceName,
    [Alias("DocumentsPath")]
    [string]$ParentPath,
    [string]$TargetPath,
    [switch]$Yes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-ZemiInstanceName {
    param([string]$Name)

    if ([string]::IsNullOrWhiteSpace($Name)) {
        return $false
    }

    if ($Name -in @(".", "..") -or [IO.Path]::IsPathRooted($Name)) {
        return $false
    }

    return $Name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -lt 0
}

function Resolve-ZemiTargetPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "The target directory path cannot be empty."
    }

    $expandedPath = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    $fullPath = [IO.Path]::GetFullPath($expandedPath)
    $parentDirectory = Split-Path -Parent $fullPath

    if (-not $parentDirectory -or -not (Test-Path -LiteralPath $parentDirectory -PathType Container)) {
        throw "The parent directory was not found: $parentDirectory"
    }

    return $fullPath
}

if ($ParentPath -and $TargetPath) {
    throw "Use either -ParentPath or -TargetPath, not both."
}

while (-not (Test-ZemiInstanceName -Name $InstanceName)) {
    if (-not [string]::IsNullOrWhiteSpace($InstanceName)) {
        Write-Warning "Use a single valid folder name without path separators."
    }
    $InstanceName = (Read-Host "ZEMI Instance folder name").Trim()
}

$documentsPath = [Environment]::GetFolderPath("MyDocuments")
if ($TargetPath) {
    $instanceRoot = Resolve-ZemiTargetPath -Path $TargetPath
}
else {
    $selectedParentPath = if ($ParentPath) { $ParentPath } else { $documentsPath }
    $selectedParentPath = [Environment]::ExpandEnvironmentVariables($selectedParentPath.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $selectedParentPath -PathType Container)) {
        throw "The parent directory was not found: $selectedParentPath"
    }

    $resolvedParentPath = (Resolve-Path -LiteralPath $selectedParentPath).ProviderPath
    $instanceRoot = Resolve-ZemiTargetPath -Path (Join-Path $resolvedParentPath $InstanceName)
}

$markerName = ".zemiinst_exp"
$requiredDirectories = @("_pythons", "_models", "_llamas", "_tmp")

if (-not $Yes) {
    $targetConfirmed = $false
    while (-not $targetConfirmed) {
        Write-Host ""
        Write-Host "Proposed ZEMI Instance path:"
        Write-Host "  $instanceRoot" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "[1] Create the Instance at this path (default)"
        Write-Host "[2] Replace the target directory"
        Write-Host "[3] Cancel"
        $choice = (Read-Host "Select an option [1]").Trim()

        if (-not $choice -or $choice -eq "1") {
            $targetConfirmed = $true
        }
        elseif ($choice -eq "2") {
            $replacementPath = (Read-Host "Full target directory for the ZEMI Instance").Trim()
            try {
                $instanceRoot = Resolve-ZemiTargetPath -Path $replacementPath
            }
            catch {
                Write-Warning $_.Exception.Message
            }
        }
        elseif ($choice -eq "3") {
            Write-Host "Cancelled."
            return
        }
        else {
            Write-Warning "Select 1, 2, or 3."
        }
    }
}
else {
    Write-Host ""
    Write-Host "ZEMI experimental Instance will be created at:"
    Write-Host "  $instanceRoot" -ForegroundColor Cyan
    Write-Host ""
}

if (Test-Path -LiteralPath $instanceRoot) {
    if (-not (Test-Path -LiteralPath $instanceRoot -PathType Container)) {
        throw "The target exists and is not a directory: $instanceRoot"
    }

    $existingEntries = @(Get-ChildItem -LiteralPath $instanceRoot -Force)
    if ($existingEntries.Count -gt 0) {
        throw "The target directory is not empty; refusing to modify it: $instanceRoot"
    }
}

if (-not $PSCmdlet.ShouldProcess($instanceRoot, "Create experimental ZEMI Instance")) {
    return
}

[void](New-Item -ItemType Directory -Path $instanceRoot -Force)
foreach ($directoryName in $requiredDirectories) {
    [void](New-Item -ItemType Directory -Path (Join-Path $instanceRoot $directoryName))
}
[void](New-Item -ItemType File -Path (Join-Path $instanceRoot $markerName))

$instanceMarkers = @(
    Get-ChildItem -LiteralPath $instanceRoot -Force -File |
        Where-Object { $_.Name -in @(".zemiinst_dev", ".zemiinst_exp", ".zemiinst_prod") }
)

if ($instanceMarkers.Count -ne 1 -or $instanceMarkers[0].Name -ne $markerName) {
    throw "ZEMI Instance marker verification failed: $instanceRoot"
}

Write-Host ""
Write-Host "[OK] Experimental ZEMI Instance created." -ForegroundColor Green
Write-Host "Root: $instanceRoot"
Write-Host "Marker: $markerName"
Write-Host ""
Write-Host "Next: download WinPython into this Instance with download_winpython.ps1."
