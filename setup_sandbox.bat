@echo off
chcp 65001 > nul
echo ===================================================
echo   Развертывание песочницы ZEMI (WinPython 3.12)
echo ===================================================

set "USE_UV=1"

:: 1. Проверка или скачивание uv
if not exist "uv.exe" (
    echo [1/4] Попытка скачивания менеджера uv с GitHub...
    powershell -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip -OutFile uv.zip -ErrorAction Stop; Expand-Archive uv.zip -DestinationPath . -Force; Remove-Item uv.zip -ErrorAction SilentlyContinue } catch { exit 1 }"
    if not exist "uv.exe" set "USE_UV=0"
)

:: 2. Создание виртуального окружения
if not exist ".venv" (
    echo [2/4] Создание изолированной среды .venv...
    if "%USE_UV%"=="1" (
        uv venv .venv --python 3.12
    ) else (
        python -m venv .venv
    )
) else (
    echo [2/4] Окружение .venv уже существует.
)

:: 3. Настройка команд (с защитой от компиляции C++ из исходников)
if "%USE_UV%"=="1" (
    set "PIP_CMD=uv pip install --only-binary :all:"
    set "PIP_NODEPS=uv pip install --no-deps"
) else (
    .venv\Scripts\python.exe -m pip install --upgrade pip
    set "PIP_CMD=.venv\Scripts\python.exe -m pip install --only-binary :all:"
    set "PIP_NODEPS=.venv\Scripts\python.exe -m pip install --no-deps"
)

:: 4. Послойная установка зависимостей
echo [3/4] Установка Слоя 1 (Base ETL, DuckDB, FastEmbed, UI)...
%PIP_CMD% -r reqs_base.txt

echo [3/4] Установка Слоя 2 (DSPy, BAML, Pydantic AI, Agents)...
%PIP_CMD% -r reqs_orchestration.txt
%PIP_NODEPS% llama-cpp-agent>=0.2.0

echo [3/4] Установка Слоя 3 (Outlines, Guidance, LlamaIndex)...
%PIP_CMD% -r reqs_experimental.txt

:: 5. Проверка импортов
echo [4/4] Запуск проверки доступности библиотек...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe test_imports.py
) else (
    echo [!] Ошибка: Виртуальное окружение .venv не создано.
)

echo ===================================================
echo   Сборка завершена!
echo ===================================================
pause