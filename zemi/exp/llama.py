"""Экспериментальное управление общим процессом llama-server."""

from __future__ import annotations

import subprocess
import shutil
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .. import env


HOST = "127.0.0.1"
PORT = 8080
HEALTH_URL = f"http://{HOST}:{PORT}/health"

_server: subprocess.Popen | None = None

__all__ = [
    "load_llama",
    "load_model",
    "download",
    "is_ready",
    "start",
    "stop",
    "restart",
]


def _format_size(size: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            return f"{size:.1f} {unit}" if unit != "Б" else f"{size:.0f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


class _Progress:
    """Одинаково обновляет одну строку в терминале и одну область в Jupyter."""

    def __init__(self, label: str, total: int | None) -> None:
        self.label = label
        self.total = total
        self.started_at = time.monotonic()
        self.last_update = 0.0
        self.display_handle = None

        try:
            from IPython import get_ipython
            from IPython.display import display

            shell = get_ipython()
            if shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell":
                self.display_handle = display("", display_id=True)
        except ImportError:
            pass

    def update(self, loaded: int, *, done: bool = False) -> None:
        now = time.monotonic()
        if not done and now - self.last_update < 0.1:
            return
        self.last_update = now

        elapsed = max(now - self.started_at, 0.001)
        speed = f"{_format_size(loaded / elapsed)}/с"
        if self.total:
            percent = min(loaded / self.total * 100, 100.0)
            amount = f"{_format_size(loaded)} / {_format_size(self.total)}"
            message = f"{self.label}: {percent:5.1f}% · {amount} · {speed}"
        else:
            message = f"{self.label}: {_format_size(loaded)} · {speed}"

        if done:
            message += " · готово"

        if self.display_handle is not None:
            self.display_handle.update(message)
        else:
            print(f"\r{message}", end="\n" if done else "", flush=True)


def _download(url: str, destination: Path, *, label: str) -> None:
    """Потоково скачивает URL с прогрессом и атомарно переносит файл на место."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    request = Request(url, headers={"User-Agent": "ZEMI"})

    try:
        with urlopen(request) as response, temporary.open("wb") as output:
            header = response.headers.get("Content-Length")
            total = int(header) if header and header.isdigit() else None
            progress = _Progress(label, total)
            loaded = 0

            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                loaded += len(chunk)
                progress.update(loaded)

            progress.update(loaded, done=True)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_llama(build: str, *, url: str | None = None) -> Path:
    """Скачивает и распаковывает Windows CPU-сборку llama.cpp в ZEMI Instance."""
    normalized_build = build.removeprefix("llama:")
    target = env.path.llama(normalized_build)
    server = target / "llama-server.exe"

    if server.is_file():
        print(f"llama.cpp {normalized_build} уже загружен: {target.resolve()}")
        return target

    archive_url = url or (
        "https://github.com/ggml-org/llama.cpp/releases/download/"
        f"{normalized_build}/llama-{normalized_build}-bin-win-cpu-x64.zip"
    )
    archive = env.path.tmp / f"llama-{normalized_build}-{uuid4().hex}.zip"
    extract_to = env.path.tmp / f"llama-{normalized_build}-{uuid4().hex}"

    print(f"Скачиваю llama.cpp {normalized_build}...")
    try:
        _download(
            archive_url,
            archive,
            label=f"llama.cpp {normalized_build}",
        )
        extract_to.mkdir(parents=True)
        with zipfile.ZipFile(archive) as package:
            package.extractall(extract_to)

        extracted_server = next(extract_to.rglob("llama-server.exe"), None)
        if extracted_server is None:
            raise FileNotFoundError("В архиве llama.cpp нет llama-server.exe")

        source = extracted_server.parent
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(
                f"Каталог llama.cpp существует, но не содержит llama-server.exe: {target.resolve()}"
            )
        source.replace(target)
    finally:
        archive.unlink(missing_ok=True)
        if extract_to.exists():
            shutil.rmtree(extract_to)

    print(f"llama.cpp {normalized_build} загружен: {target.resolve()}")
    return target


def load_model(
    owner: str,
    repository: str,
    filename: str,
    *,
    source: str = "hf",
    url: str | None = None,
) -> Path:
    """Скачивает GGUF-модель в каталог текущего ZEMI Instance."""
    target_directory = env.path.model(owner, repository, filename, source=source)
    target = target_directory / filename

    if target.is_file():
        print(f"Модель уже загружена: {target.resolve()}")
        return target

    if url is None:
        if source.removesuffix(":") != "hf":
            raise ValueError("Для источника, отличного от hf, необходимо передать url")
        url = f"https://huggingface.co/{owner}/{repository}/resolve/main/{filename}"

    print(f"Скачиваю модель {owner}/{repository}/{filename}...")
    _download(
        url,
        target,
        label=f"Модель {owner}/{repository}/{filename}",
    )
    print(f"Модель загружена: {target.resolve()}")
    return target


def download(
    *,
    llama_build: str,
    model_owner: str,
    model_repository: str,
    model_filename: str,
    model_source: str = "hf",
) -> tuple[Path, Path]:
    """Загружает отсутствующие llama.cpp и модель."""
    llama_path = load_llama(llama_build)
    model_path = load_model(
        model_owner,
        model_repository,
        model_filename,
        source=model_source,
    )
    return llama_path, model_path


def is_ready(timeout: float = 1.0) -> bool:
    """Проверяет, отвечает ли llama-server на /health."""
    try:
        with urlopen(HEALTH_URL, timeout=timeout):
            return True
    except (URLError, TimeoutError):
        return False


def _find_and_stop_process_on_port() -> bool:
    """Находит и останавливает llama-server, слушающий PORT."""
    command = f"""
    $connection = Get-NetTCPConnection `
        -LocalPort {PORT} `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if (-not $connection) {{
        Write-Output "NOT_FOUND"
        exit
    }}

    $process = Get-Process `
        -Id $connection.OwningProcess `
        -ErrorAction SilentlyContinue

    if (-not $process) {{
        Write-Output "NOT_FOUND"
        exit
    }}

    if ($process.ProcessName -ne "llama-server") {{
        Write-Output "WRONG_PROCESS:$($process.ProcessName):$($process.Id)"
        exit
    }}

    Stop-Process -Id $process.Id -Force
    Write-Output "STOPPED:$($process.Id)"
    """

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout.strip()

    if output.startswith("STOPPED:"):
        pid = output.split(":", 1)[1]
        print(f"llama-server остановлен, PID: {pid}")
        return True

    if output == "NOT_FOUND":
        return False

    if output.startswith("WRONG_PROCESS:"):
        _, process_name, pid = output.split(":", 2)
        raise RuntimeError(
            f"Порт {PORT} занят другим процессом: "
            f"{process_name}, PID: {pid}"
        )

    error = result.stderr.strip() or output or "неизвестная ошибка"
    raise RuntimeError(
        f"Не удалось проверить процесс на порту {PORT}: {error}"
    )


def _wait_until_stopped(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not is_ready():
            return
        time.sleep(0.2)

    raise TimeoutError(
        f"llama-server не остановился за {timeout:.1f} секунд"
    )


def stop(timeout: float = 10.0) -> bool:
    """Останавливает llama-server независимо от того, кем он был запущен."""
    global _server

    stopped = False

    if _server is not None and _server.poll() is None:
        _server.terminate()

        try:
            _server.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _server.kill()
            _server.wait()

        print(f"llama-server остановлен, PID: {_server.pid}")
        stopped = True

    _server = None

    if is_ready():
        stopped = _find_and_stop_process_on_port() or stopped

    if stopped:
        _wait_until_stopped(timeout)
    else:
        print("Работающий llama-server не найден")

    return stopped


def start(
    *,
    llama_build: str,
    model_owner: str,
    model_repository: str,
    model_filename: str,
    model_source: str = "hf",
    alias: str | None = None,
    ctx_size: int = 4096,
    threads: int = 4,
    threads_batch: int = 4,
    reasoning: str = "off",
    startup_timeout: float = 120.0,
) -> subprocess.Popen:
    """Запускает llama-server для модели из текущего ZEMI Instance."""
    global _server

    if is_ready():
        raise RuntimeError(
            f"llama-server уже работает на {HOST}:{PORT}. "
            "Для перезапуска используй exp.llama.restart()."
        )

    server_path = env.path.llama(llama_build) / "llama-server.exe"
    model_path = env.path.model(
        model_owner,
        model_repository,
        model_filename,
        source=model_source,
    ) / model_filename
    alias = alias or model_filename[:-len(".gguf")]

    if not server_path.is_file():
        raise FileNotFoundError(
            f"llama-server.exe не найден: {server_path.resolve()}"
        )

    if not model_path.is_file():
        raise FileNotFoundError(
            f"Файл модели не найден: {model_path.resolve()}"
        )

    _server = subprocess.Popen([
        str(server_path),
        "--model", str(model_path),
        "--alias", alias,
        "--host", HOST,
        "--port", str(PORT),
        "--ctx-size", str(ctx_size),
        "--threads", str(threads),
        "--threads-batch", str(threads_batch),
        "--reasoning", reasoning,
    ])

    deadline = time.monotonic() + startup_timeout

    while time.monotonic() < deadline:
        if _server.poll() is not None:
            return_code = _server.returncode
            _server = None
            raise RuntimeError(
                f"llama-server завершился с кодом {return_code}"
            )

        if is_ready():
            print(f"llama-server запущен и готов, PID: {_server.pid}")
            return _server

        time.sleep(1)

    process = _server
    _server = None

    if process.poll() is None:
        process.terminate()

    raise TimeoutError(
        f"llama-server не запустился за {startup_timeout:.1f} секунд"
    )


def restart(**kwargs) -> subprocess.Popen:
    """Останавливает текущий llama-server и запускает новый."""
    stop()
    return start(**kwargs)
