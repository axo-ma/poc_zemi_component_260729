[CmdletBinding()]
param(
    [string]$InstancePath,
    [string]$UserDataPath,
    [string]$PythonPath,
    [switch]$Yes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Folder([string]$Path, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Name path is empty."
    }
    $Path = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Name was not found: $Path"
    }
    (Resolve-Path -LiteralPath $Path).ProviderPath
}

if ([string]::IsNullOrWhiteSpace($InstancePath)) {
    $InstancePath = Read-Host "Full path to the ZEMI Instance"
}
$InstancePath = Resolve-Folder $InstancePath "ZEMI Instance"

$markers = @(
    Get-ChildItem -LiteralPath $InstancePath -Force -File |
        Where-Object { $_.Name -in @(".zemiinst_dev", ".zemiinst_exp", ".zemiinst_prod") }
)
if ($markers.Count -ne 1) {
    throw "Expected exactly one ZEMI Instance marker in: $InstancePath"
}

if ([string]::IsNullOrWhiteSpace($UserDataPath)) {
    $UserDataPath = Join-Path $env:APPDATA "Code\User"
}
$UserDataPath = Resolve-Folder $UserDataPath "VS Code user-data User"

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $InstancePath "_pythons\WPy64-312101\python\python.exe"
}
$PythonPath = [Environment]::ExpandEnvironmentVariables($PythonPath.Trim().Trim('"'))
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "WinPython was not found: $PythonPath"
}

$openVSCode = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match '^Code($| -)'
})
if ($openVSCode.Count -gt 0) {
    throw "Close every VS Code window before running this script."
}

Write-Host ""
Write-Host "ZEMI Instance: $InstancePath"
Write-Host "VS Code data:  $UserDataPath"
Write-Warning "Python/Jupyter settings and caches will be deleted without a backup."
Write-Host ".venv, WinPython, packages, notebooks, and user kernelspecs will remain."

if (-not $Yes) {
    $answer = (Read-Host "Continue? [y/N]").Trim().ToLowerInvariant()
    if ($answer -notin @("y", "yes")) {
        Write-Host "Cancelled."
        return
    }
}

$worker = @'
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

instance = Path(sys.argv[1]).resolve()
user = Path(sys.argv[2]).resolve()
skip = {".git", ".venv", "node_modules"}


def parse_jsonc(text):
    parts = re.split(r'("(?:\\.|[^"\\])*")', text)
    for index in range(0, len(parts), 2):
        parts[index] = re.sub(r'//[^\r\n]*|/\*.*?\*/', '', parts[index], flags=re.S)
        parts[index] = re.sub(r',\s*([}\]])', r'\1', parts[index])
    return json.loads(''.join(parts))


def clean_settings(data):
    removed = 0
    for key in list(data):
        lowered = key.lower()
        if lowered.startswith(("python.", "python-envs.", "jupyter.")):
            del data[key]
            removed += 1
    for key in ("terminal.integrated.env.windows", "terminal.integrated.env.linux",
                "terminal.integrated.env.osx"):
        environment = data.get(key)
        if not isinstance(environment, dict):
            continue
        for name, value in list(environment.items()):
            upper = name.upper()
            python_path = upper == "PATH" and isinstance(value, str) and re.search(
                r"(?i)(\\\.venv\\|\\_?pythons\\|\\WPy64-|\\python(?:\\|;)|\\conda(?:\\|;))", value
            )
            if upper in {"VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH"} or python_path:
                del environment[name]
                removed += 1
        if not environment:
            del data[key]
    return removed


profile_roots = [user]
profiles = user / "profiles"
if profiles.is_dir():
    profile_roots.extend(path for path in profiles.iterdir() if path.is_dir())
settings = [root / "settings.json" for root in profile_roots]

for root, directories, files in os.walk(instance):
    root = Path(root)
    directories[:] = [name for name in directories if
                      name not in skip and not (root == instance and name.startswith("_"))
                      and not (root / name).is_symlink()]
    if root.name == ".vscode":
        directories[:] = []
        if "settings.json" in files:
            settings.append(root / "settings.json")

parsed = []
for path in dict.fromkeys(settings):
    if path.is_file():
        parsed.append((path, parse_jsonc(path.read_text(encoding="utf-8-sig"))))

settings_changed = 0
for path, data in parsed:
    if clean_settings(data):
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        settings_changed += 1

databases = []
for profile_root in profile_roots:
    for storage_name in ("workspaceStorage", "globalStorage"):
        storage = profile_root / storage_name
        if storage.is_dir():
            databases.extend(storage.rglob("state.vscdb"))
            databases.extend(storage.rglob("state.vscdb.backup"))

state_keys_removed = 0
for database in dict.fromkeys(databases):
    with sqlite3.connect(database, timeout=30) as connection:
        keys = [row[0] for row in connection.execute("""
            SELECT key FROM ItemTable
            WHERE lower(key) LIKE '%python%'
               OR lower(key) LIKE '%jupyter%'
               OR key IN ('notebook.controller2NotebookBindings', 'notebook.kernelHistory')
        """)]
        connection.executemany("DELETE FROM ItemTable WHERE key = ?", ((key,) for key in keys))
        state_keys_removed += len(keys)

storages_removed = 0
extension_names = {"ms-python.python", "ms-python.vscode-python-envs", "ms-toolsai.jupyter"}
for profile_root in profile_roots:
    for name in extension_names:
        path = profile_root / "globalStorage" / name
        if path.is_dir():
            shutil.rmtree(path)
            storages_removed += 1

prompt_flags_written = 0
prompt_state = json.dumps({"python-envs:uv:UV_INSTALL_PYTHON_DONT_ASK": True})
for profile_root in profile_roots:
    for database_name in ("state.vscdb", "state.vscdb.backup"):
        database = profile_root / "globalStorage" / database_name
        if database.is_file():
            with sqlite3.connect(database, timeout=30) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    ("ms-python.vscode-python-envs", prompt_state),
                )
            prompt_flags_written += 1

print(f"Settings files changed: {settings_changed}")
print(f"VS Code state keys removed: {state_keys_removed}")
print(f"Extension storage directories removed: {storages_removed}")
print(f"Python installer prompts disabled: {prompt_flags_written}")
'@

$payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($worker))
$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $output = (& $PythonPath -c "import base64;exec(base64.b64decode('$payload'))" `
        $InstancePath $UserDataPath 2>&1 | Out-String).Trim()
    $exitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldPreference
}
if ($exitCode -ne 0) {
    throw "VS Code reset failed before completion:`n$output"
}

Write-Host ""
Write-Host $output
Write-Host "[OK] VS Code Python/Jupyter state reset." -ForegroundColor Green
Write-Host "Open a project containing .venv; VS Code will discover it again."
