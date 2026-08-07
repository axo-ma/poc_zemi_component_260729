[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstancePath,
    [switch]$Yes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$archiveName = "Winpython64-3.12.10.1slim.7z"
$downloadUrl = "https://github.com/winpython/winpython/releases/download/16.6.20250620final/$archiveName"
$expectedSha256 = "a320f799843712b0c3aa5bcb0fb472cd36dc74615a1436c976c4bf6e8a4ac29f"
$expectedSize = 630560365L
$winPythonFolderName = "WPy64-312101"
$instanceMarkerNames = @(".zemiinst_dev", ".zemiinst_exp", ".zemiinst_prod")

function Show-SevenZipInstructions {
    param(
        [string]$ArchivePath,
        [string]$DestinationPath
    )

    $sevenZipExecutable = $null
    $sevenZipCommand = Get-Command "7z.exe" -ErrorAction SilentlyContinue
    if ($sevenZipCommand) {
        $sevenZipExecutable = $sevenZipCommand.Source
    }

    if (-not $sevenZipExecutable) {
        $sevenZipCandidates = @(
            (Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "7-Zip\7z.exe"),
            (Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "7-Zip\7z.exe")
        )
        $sevenZipExecutable = $sevenZipCandidates |
            Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
            Select-Object -First 1
    }

    Write-Host "Extract it with 7-Zip into:"
    Write-Host "  $DestinationPath" -ForegroundColor Cyan
    Write-Host ""

    if ($sevenZipExecutable) {
        Write-Host "PowerShell command:"
        Write-Host ('  & "{0}" x "{1}" "-o{2}"' -f $sevenZipExecutable, $ArchivePath, $DestinationPath)
    }
    else {
        Write-Host "7-Zip was not found automatically. Use the 7-Zip GUI or its full executable path."
        Write-Host "Archive: $ArchivePath"
    }
}

function Invoke-DownloadWithProgress {
    param(
        [string]$Url,
        [string]$DestinationPath,
        [long]$TotalBytes
    )

    Add-Type -AssemblyName System.Net.Http

    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $true
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [Threading.Timeout]::InfiniteTimeSpan
    $client.DefaultRequestHeaders.UserAgent.ParseAdd("ZEMI-WinPython-Bootstrap/1.0")

    $response = $null
    $inputStream = $null
    $outputStream = $null
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()

    try {
        Write-Host "Connecting to the download server..."
        $response = $client.GetAsync(
            $Url,
            [Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        [void]$response.EnsureSuccessStatusCode()

        $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $outputStream = New-Object IO.FileStream(
            $DestinationPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )

        $buffer = New-Object byte[] (1024 * 1024)
        $downloadedBytes = 0L
        $lastUpdate = [DateTime]::MinValue

        while (($bytesRead = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $outputStream.Write($buffer, 0, $bytesRead)
            $downloadedBytes += $bytesRead

            if (([DateTime]::UtcNow - $lastUpdate).TotalMilliseconds -ge 250) {
                $elapsedSeconds = [Math]::Max($stopwatch.Elapsed.TotalSeconds, 0.001)
                $speedMiB = ($downloadedBytes / 1MB) / $elapsedSeconds
                $percent = [Math]::Min(100, ($downloadedBytes / $TotalBytes) * 100)
                $remainingSeconds = if ($speedMiB -gt 0) {
                    (($TotalBytes - $downloadedBytes) / 1MB) / $speedMiB
                }
                else {
                    0
                }
                $eta = [TimeSpan]::FromSeconds([Math]::Max(0, $remainingSeconds)).ToString("hh\:mm\:ss")
                $status = "Download: {0,5:N1}% | {1:N1}/{2:N1} MiB | {3:N1} MiB/s | ETA {4}" -f `
                    $percent,
                    ($downloadedBytes / 1MB),
                    ($TotalBytes / 1MB),
                    $speedMiB,
                    $eta
                Write-Host ("`r" + $status.PadRight(78)) -NoNewline
                $lastUpdate = [DateTime]::UtcNow
            }
        }

        $outputStream.Flush()
        $elapsed = $stopwatch.Elapsed.ToString("hh\:mm\:ss")
        $completeStatus = "Downloaded: {0:N1} MiB in {1}" -f ($downloadedBytes / 1MB), $elapsed
        Write-Host ("`r" + $completeStatus.PadRight(78))
    }
    finally {
        $stopwatch.Stop()
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
        $client.Dispose()
        $handler.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($InstancePath)) {
    $InstancePath = (Read-Host "Full path to the ZEMI Instance").Trim().Trim('"')
}

if (-not (Test-Path -LiteralPath $InstancePath -PathType Container)) {
    throw "ZEMI Instance directory was not found: $InstancePath"
}

$instanceRoot = (Resolve-Path -LiteralPath $InstancePath).ProviderPath
$instanceMarkers = @(
    Get-ChildItem -LiteralPath $instanceRoot -Force -File |
        Where-Object { $_.Name -in $instanceMarkerNames }
)

if ($instanceMarkers.Count -ne 1) {
    throw "Expected exactly one ZEMI Instance marker in: $instanceRoot"
}

$pythonsRoot = Join-Path $instanceRoot "_pythons"
$temporaryRoot = Join-Path $instanceRoot "_tmp"

foreach ($requiredDirectory in @($pythonsRoot, $temporaryRoot)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Required ZEMI Instance directory was not found: $requiredDirectory"
    }
}

$winPythonRoot = Join-Path $pythonsRoot $winPythonFolderName
$winPythonExecutable = Join-Path $winPythonRoot "python\python.exe"
$archivePath = Join-Path $temporaryRoot $archiveName
$partialPath = "$archivePath.partial"

if (Test-Path -LiteralPath $winPythonExecutable -PathType Leaf) {
    Write-Host "[OK] WinPython is already available:" -ForegroundColor Green
    Write-Host "  $winPythonExecutable"
    return
}

if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    $existingHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($existingHash -eq $expectedSha256) {
        Write-Host "[OK] The verified WinPython archive is already downloaded." -ForegroundColor Green
        Write-Host "Archive: $archivePath"
        Write-Host ""
        Show-SevenZipInstructions -ArchivePath $archivePath -DestinationPath $pythonsRoot
        return
    }

    throw "An archive with an unexpected SHA-256 already exists: $archivePath"
}

Write-Host ""
Write-Host "WinPython archive: $archiveName"
Write-Host "Download size: 630,560,365 bytes (about 601 MiB)"
Write-Host "Destination: $archivePath"
Write-Host ""

if (-not $Yes) {
    $answer = (Read-Host "Download the official WinPython archive? [Y/n]").Trim()
    if ($answer -and $answer -notin @("y", "yes")) {
        Write-Host "Cancelled."
        return
    }
}

if (-not $PSCmdlet.ShouldProcess($archivePath, "Download WinPython 3.12.10.1 slim")) {
    return
}

if (Test-Path -LiteralPath $partialPath -PathType Leaf) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Move-Item -LiteralPath $partialPath -Destination "$partialPath.incomplete-$timestamp"
}

[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

try {
    Invoke-DownloadWithProgress `
        -Url $downloadUrl `
        -DestinationPath $partialPath `
        -TotalBytes $expectedSize
}
catch {
    throw "WinPython download failed. Partial file, if any: $partialPath`n$($_.Exception.Message)"
}

$downloadedFile = Get-Item -LiteralPath $partialPath
if ($downloadedFile.Length -ne $expectedSize) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $failedPath = "$partialPath.invalid-size-$timestamp"
    Move-Item -LiteralPath $partialPath -Destination $failedPath
    throw "Unexpected archive size. The downloaded file was preserved at: $failedPath"
}

$downloadedHash = (Get-FileHash -LiteralPath $partialPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($downloadedHash -ne $expectedSha256) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $failedPath = "$partialPath.sha256-mismatch-$timestamp"
    Move-Item -LiteralPath $partialPath -Destination $failedPath
    throw "SHA-256 verification failed. The downloaded file was preserved at: $failedPath"
}

Move-Item -LiteralPath $partialPath -Destination $archivePath

Write-Host ""
Write-Host "[OK] WinPython archive downloaded and verified." -ForegroundColor Green
Write-Host "Archive: $archivePath"
Write-Host "SHA-256: $expectedSha256"
Write-Host ""
Show-SevenZipInstructions -ArchivePath $archivePath -DestinationPath $pythonsRoot
Write-Host ""
Write-Host "After extraction, verify:"
Write-Host "  $winPythonExecutable"
