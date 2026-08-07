[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("WinPython", "ProjectVenv")]
    [string]$Mode,
    [string]$WorkspacePath,
    [string]$InstancePath,
    [string]$CodePath,
    [switch]$Yes,
    [switch]$NoOpen,
    [switch]$SkipExtensionCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$instanceMarkerNames = @(".zemiinst_dev", ".zemiinst_exp", ".zemiinst_prod")
$winPythonFolderName = "WPy64-312101"
$requiredExtensions = @("ms-python.python", "ms-toolsai.jupyter")

function Resolve-ExistingDirectory {
    param(
        [string]$Path,
        [string]$Description
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Description path cannot be empty."
    }

    $expandedPath = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $expandedPath -PathType Container)) {
        throw "$Description directory was not found: $expandedPath"
    }

    return (Resolve-Path -LiteralPath $expandedPath).ProviderPath
}

function Find-ParentWithFile {
    param(
        [string]$StartPath,
        [string]$FileName
    )

    $current = Get-Item -LiteralPath $StartPath
    while ($current) {
        if (Test-Path -LiteralPath (Join-Path $current.FullName $FileName) -PathType Leaf) {
            return $current.FullName
        }
        $current = $current.Parent
    }

    return $null
}

function Find-ZemiInstanceRoot {
    param([string]$StartPath)

    $current = Get-Item -LiteralPath $StartPath
    while ($current) {
        $markers = @(
            Get-ChildItem -LiteralPath $current.FullName -Force -File |
                Where-Object { $_.Name -in $instanceMarkerNames }
        )
        if ($markers.Count -gt 0) {
            if ($markers.Count -ne 1) {
                throw "Expected exactly one ZEMI Instance marker in: $($current.FullName)"
            }
            return $current.FullName
        }
        $current = $current.Parent
    }

    return $null
}

function Confirm-ZemiInstanceRoot {
    param([string]$Path)

    $root = Resolve-ExistingDirectory -Path $Path -Description "ZEMI Instance"
    $markers = @(
        Get-ChildItem -LiteralPath $root -Force -File |
            Where-Object { $_.Name -in $instanceMarkerNames }
    )
    if ($markers.Count -ne 1) {
        throw "Expected exactly one ZEMI Instance marker in: $root"
    }

    foreach ($directoryName in @("_pythons", "_tmp")) {
        $requiredPath = Join-Path $root $directoryName
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "Required ZEMI Instance directory was not found: $requiredPath"
        }
    }

    return $root
}

function Resolve-CodeCommand {
    param([string]$RequestedPath)

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $expandedPath = [Environment]::ExpandEnvironmentVariables($RequestedPath.Trim().Trim('"'))
        if (Test-Path -LiteralPath $expandedPath -PathType Container) {
            foreach ($relativePath in @("Code.exe", "bin\code.cmd")) {
                $candidate = Join-Path $expandedPath $relativePath
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return (Resolve-Path -LiteralPath $candidate).ProviderPath
                }
            }
        }
        elseif (Test-Path -LiteralPath $expandedPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $expandedPath).ProviderPath
        }

        throw "VS Code executable was not found: $expandedPath"
    }

    foreach ($commandName in @("code.cmd", "code.exe", "code")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }

    $candidates = @()
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Programs\Microsoft VS Code\Code.exe"
    }
    if ([Environment]::GetFolderPath("ProgramFiles")) {
        $candidates += Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "Microsoft VS Code\Code.exe"
    }
    if ([Environment]::GetFolderPath("ProgramFilesX86")) {
        $candidates += Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "Microsoft VS Code\Code.exe"
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }

    $enteredPath = (Read-Host "Full path to portable Code.exe or code.cmd").Trim()
    return Resolve-CodeCommand -RequestedPath $enteredPath
}

function Invoke-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& $FilePath @ArgumentList 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [PSCustomObject]@{
        Output = $output
        ExitCode = $exitCode
    }
}

function Read-JsonObject {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return New-Object PSObject
    }

    $content = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($content)) {
        return New-Object PSObject
    }

    try {
        $value = $content | ConvertFrom-Json
    }
    catch {
        throw "Cannot update invalid JSON file: $Path`n$($_.Exception.Message)"
    }

    if ($null -eq $value -or $value -is [Array]) {
        throw "Expected a JSON object in: $Path"
    }

    return $value
}

function Set-JsonProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($property) {
        $property.Value = $Value
    }
    else {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
}

function Remove-JsonProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($Object.PSObject.Properties[$Name]) {
        $Object.PSObject.Properties.Remove($Name)
    }
}

function Save-JsonObject {
    param(
        [object]$Object,
        [string]$TargetPath,
        [string]$TemporaryRoot,
        [string]$BackupRoot
    )

    $targetDirectory = Split-Path -Parent $TargetPath
    if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
        [void](New-Item -ItemType Directory -Path $targetDirectory)
    }

    if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
        if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) {
            [void](New-Item -ItemType Directory -Path $BackupRoot -Force)
        }
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
        $backupName = "{0}.{1}.bak" -f (Split-Path -Leaf $TargetPath), $timestamp
        Copy-Item -LiteralPath $TargetPath -Destination (Join-Path $BackupRoot $backupName)
    }

    $stagingPath = Join-Path $TemporaryRoot ("vscode-{0}.json" -f [Guid]::NewGuid().ToString("N"))
    try {
        $json = $Object | ConvertTo-Json -Depth 20
        [IO.File]::WriteAllText($stagingPath, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $stagingPath -Destination $TargetPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $stagingPath -PathType Leaf) {
            Remove-Item -LiteralPath $stagingPath -Force
        }
    }
}

function Test-ProjectVenvBase {
    param(
        [string]$VenvRoot,
        [string]$ExpectedBaseRoot
    )

    $configurationPath = Join-Path $VenvRoot "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $configurationPath -PathType Leaf)) {
        throw "Virtual environment configuration was not found: $configurationPath"
    }

    $configuration = [IO.File]::ReadAllText($configurationPath, [Text.Encoding]::UTF8)
    $homeMatch = [regex]::Match($configuration, "(?im)^home\s*=\s*(.+?)\s*$")
    if (-not $homeMatch.Success) {
        throw "The virtual environment does not specify its base Python: $configurationPath"
    }

    $actualBaseRoot = [IO.Path]::GetFullPath($homeMatch.Groups[1].Value.Trim())
    $expectedRoot = [IO.Path]::GetFullPath($ExpectedBaseRoot)
    if (-not $actualBaseRoot.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The project .venv was not created from the expected WinPython.`nExpected: $expectedRoot`nActual:   $actualBaseRoot"
    }

    $sitePackagesMatch = [regex]::Match(
        $configuration,
        "(?im)^include-system-site-packages\s*=\s*(true|false)\s*$"
    )
    if (-not $sitePackagesMatch.Success -or $sitePackagesMatch.Groups[1].Value -ne "true") {
        Write-Warning "This .venv does not inherit the released WinPython packages. Recreate it with --system-site-packages if that is required for the experiment."
    }
}

if ([string]::IsNullOrWhiteSpace($WorkspacePath)) {
    $WorkspacePath = (Get-Location).ProviderPath
}
$workspaceRoot = Resolve-ExistingDirectory -Path $WorkspacePath -Description "VS Code workspace"

if ([string]::IsNullOrWhiteSpace($Mode)) {
    Write-Host ""
    Write-Host "Python for VS Code:"
    Write-Host "[1] Project @comp/.venv (default)"
    Write-Host "[2] Base WinPython"
    $modeChoice = (Read-Host "Select an option [1]").Trim()
    if (-not $modeChoice -or $modeChoice -eq "1") {
        $Mode = "ProjectVenv"
    }
    elseif ($modeChoice -eq "2") {
        $Mode = "WinPython"
    }
    else {
        throw "Select 1 or 2."
    }
}

if ($Mode -eq "ProjectVenv") {
    $componentRoot = Find-ParentWithFile -StartPath $workspaceRoot -FileName ".zemicomp"
    if (-not $componentRoot) {
        throw "ZEMI Component marker .zemicomp was not found at or above: $workspaceRoot"
    }
    $workspaceRoot = $componentRoot
}

if ([string]::IsNullOrWhiteSpace($InstancePath)) {
    $InstancePath = Find-ZemiInstanceRoot -StartPath $workspaceRoot
    if (-not $InstancePath) {
        $InstancePath = (Read-Host "Full path to the ZEMI Instance").Trim()
    }
}
$instanceRoot = Confirm-ZemiInstanceRoot -Path $InstancePath

$winPythonRoot = Join-Path $instanceRoot "_pythons\$winPythonFolderName\python"
$winPythonExecutable = Join-Path $winPythonRoot "python.exe"
if (-not (Test-Path -LiteralPath $winPythonExecutable -PathType Leaf)) {
    throw "WinPython interpreter was not found: $winPythonExecutable"
}

if ($Mode -eq "ProjectVenv") {
    $venvRoot = Join-Path $workspaceRoot ".venv"
    $pythonExecutable = Join-Path $venvRoot "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        throw "Project interpreter was not found: $pythonExecutable`nCreate @comp/.venv from @inst/_pythons/$winPythonFolderName/python/python.exe first."
    }
    Test-ProjectVenvBase -VenvRoot $venvRoot -ExpectedBaseRoot $winPythonRoot
}
else {
    $pythonExecutable = $winPythonExecutable
}

$versionResult = Invoke-NativeCommand -FilePath $pythonExecutable -ArgumentList @("--version")
if ($versionResult.ExitCode -ne 0) {
    throw "Selected Python failed to start: $pythonExecutable"
}
$versionOutput = $versionResult.Output

$jupyterReady = $false
$ipykernelResult = Invoke-NativeCommand `
    -FilePath $pythonExecutable `
    -ArgumentList @("-c", "import ipykernel; print(ipykernel.__version__)")
$ipykernelOutput = $ipykernelResult.Output
if ($ipykernelResult.ExitCode -eq 0) {
    $jupyterReady = $true
}

$vscodeRoot = Join-Path $workspaceRoot ".vscode"
$settingsPath = Join-Path $vscodeRoot "settings.json"
$extensionsPath = Join-Path $vscodeRoot "extensions.json"
$temporaryRoot = Join-Path $instanceRoot "_tmp"
$backupRoot = Join-Path $temporaryRoot "vscode-settings-backups"

$settings = Read-JsonObject -Path $settingsPath
foreach ($conflictingSetting in @("python-envs.defaultEnvManager", "python-envs.pythonProjects")) {
    Remove-JsonProperty -Object $settings -Name $conflictingSetting
}
Set-JsonProperty -Object $settings -Name "python.defaultInterpreterPath" -Value $pythonExecutable
Set-JsonProperty -Object $settings -Name "python-envs.terminal.autoActivationType" -Value "command"
Set-JsonProperty -Object $settings -Name "python.terminal.activateEnvironment" -Value $true

$terminalEnvironment = New-Object PSObject
if (
    $settings.PSObject.Properties["terminal.integrated.env.windows"] -and
    $settings."terminal.integrated.env.windows"
) {
    $terminalEnvironment = $settings."terminal.integrated.env.windows"
}

Set-JsonProperty -Object $terminalEnvironment -Name "PYTHONHOME" -Value $null

if ($Mode -eq "ProjectVenv") {
    Set-JsonProperty -Object $settings -Name "python-envs.workspaceSearchPaths" -Value @("./.venv")
    $venvScripts = Join-Path $venvRoot "Scripts"
    $terminalPath = $venvScripts + ';${env:PATH}'
    Set-JsonProperty -Object $terminalEnvironment -Name "PATH" -Value $terminalPath
    Set-JsonProperty -Object $terminalEnvironment -Name "VIRTUAL_ENV" -Value $venvRoot
}
else {
    Remove-JsonProperty -Object $settings -Name "python-envs.workspaceSearchPaths"
    $winPythonScripts = Join-Path $winPythonRoot "Scripts"
    $terminalPath = $winPythonRoot + ";" + $winPythonScripts + ';${env:PATH}'
    Set-JsonProperty -Object $terminalEnvironment -Name "PATH" -Value $terminalPath
    Set-JsonProperty -Object $terminalEnvironment -Name "VIRTUAL_ENV" -Value $null
}

Set-JsonProperty `
    -Object $settings `
    -Name "terminal.integrated.env.windows" `
    -Value $terminalEnvironment

$extensions = Read-JsonObject -Path $extensionsPath
$recommendations = @()
if ($extensions.PSObject.Properties["recommendations"] -and $extensions.recommendations) {
    $recommendations += @($extensions.recommendations)
}
foreach ($extensionId in $requiredExtensions) {
    if ($extensionId -notin $recommendations) {
        $recommendations += $extensionId
    }
}
Set-JsonProperty -Object $extensions -Name "recommendations" -Value $recommendations

if (-not $PSCmdlet.ShouldProcess($vscodeRoot, "Configure VS Code for $pythonExecutable")) {
    return
}

Save-JsonObject -Object $settings -TargetPath $settingsPath -TemporaryRoot $temporaryRoot -BackupRoot $backupRoot
Save-JsonObject -Object $extensions -TargetPath $extensionsPath -TemporaryRoot $temporaryRoot -BackupRoot $backupRoot

$codeCommand = $null
$installedExtensions = @()
if (-not $SkipExtensionCheck -or -not $NoOpen) {
    $codeCommand = Resolve-CodeCommand -RequestedPath $CodePath
}

if (-not $SkipExtensionCheck) {
    $extensionResult = Invoke-NativeCommand -FilePath $codeCommand -ArgumentList @("--list-extensions")
    if ($extensionResult.ExitCode -ne 0) {
        Write-Warning "VS Code extension check failed: $($extensionResult.Output)"
    }
    else {
        $installedExtensions = @(
            $extensionResult.Output -split "\r?\n" |
                ForEach-Object { $_.Trim().ToLowerInvariant() }
        )
        $missingExtensions = @($requiredExtensions | Where-Object { $_ -notin $installedExtensions })
        if ($missingExtensions.Count -gt 0) {
            Write-Host ""
            Write-Host "Missing VS Code extensions:"
            $missingExtensions | ForEach-Object { Write-Host "  $_" }

            $installExtensions = $Yes
            if (-not $Yes) {
                $answer = (Read-Host "Install the missing extensions? [Y/n]").Trim().ToLowerInvariant()
                $installExtensions = -not $answer -or $answer -in @("y", "yes")
            }

            if ($installExtensions) {
                foreach ($extensionId in $missingExtensions) {
                    $installResult = Invoke-NativeCommand `
                        -FilePath $codeCommand `
                        -ArgumentList @("--install-extension", $extensionId)
                    if ($installResult.Output) {
                        Write-Host $installResult.Output
                    }
                    if ($installResult.ExitCode -ne 0) {
                        throw "VS Code extension installation failed: $extensionId"
                    }
                }
            }
        }
    }
}

Write-Host ""
Write-Host "[OK] VS Code workspace configured." -ForegroundColor Green
Write-Host "Workspace: $workspaceRoot"
Write-Host "Mode:      $Mode"
Write-Host "Python:    $pythonExecutable"
Write-Host "Version:   $versionOutput"
Write-Host "Settings:  $settingsPath"
Write-Host "Terminal:  new terminals will use the selected Python"

if ($jupyterReady) {
    Write-Host "Jupyter:   ipykernel $ipykernelOutput" -ForegroundColor Green
}
else {
    Write-Warning "ipykernel is not available in the selected Python. Notebooks cannot run with this interpreter yet."
    if ($Mode -eq "ProjectVenv") {
        Write-Host "Install it only into @comp/.venv:"
        Write-Host ('  & "{0}" -m pip install ipykernel' -f $pythonExecutable)
    }
    else {
        Write-Host "Keep the released WinPython unchanged; use a project .venv for additional packages."
    }
}

Write-Host "For an .ipynb file, select this Python once if VS Code asks for a kernel:"
Write-Host "  $pythonExecutable"
Write-Host "Close all existing terminals and create a new one after this switch."

if (-not $NoOpen) {
    $openWorkspace = $Yes
    if (-not $Yes) {
        $answer = (Read-Host "Open the workspace in VS Code now? [Y/n]").Trim().ToLowerInvariant()
        $openWorkspace = -not $answer -or $answer -in @("y", "yes")
    }

    if ($openWorkspace) {
        $openResult = Invoke-NativeCommand -FilePath $codeCommand -ArgumentList @("-r", $workspaceRoot)
        if ($openResult.ExitCode -ne 0) {
            throw "VS Code failed to open the workspace: $workspaceRoot"
        }
    }
}
