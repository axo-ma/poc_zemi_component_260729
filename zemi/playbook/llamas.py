"""Загрузка llama.cpp и GGUF-моделей для ZEMI Playbook."""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .. import env, toml


__all__ = [
    "DownloadError",
    "download_arsenal",
    "download_llama",
    "download_model",
]


class DownloadError(RuntimeError):
    """Ожидаемая ошибка загрузки внешнего ресурса."""


def _resolve_zemi_path(value: str | Path) -> Path:
    """Преобразует путь с маркером ZEMI в файловый путь."""
    path = str(value).replace("\\", "/")
    for prefix, root in (("@comp/", env.path.comp), ("@inst/", env.path.inst)):
        if path.startswith(prefix):
            return root / path.removeprefix(prefix)
    raise ValueError("Путь должен начинаться с @comp/ или @inst/")


def _display_zemi_path(path: Path) -> str:
    """Представляет файловый путь через маркер ZEMI."""
    path = path.resolve()
    for marker, root in (("@comp", env.path.comp), ("@inst", env.path.inst)):
        try:
            relative = path.relative_to(root.resolve())
        except ValueError:
            continue
        return f"{marker}/{relative.as_posix()}"
    raise ValueError(f"Путь находится вне ZEMI Instance: {path.name}")


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

            if total is not None and loaded != total:
                raise DownloadError(
                    "Загрузка завершилась раньше времени.\n"
                    f"Получено: {_format_size(loaded)}\n"
                    f"Ожидалось: {_format_size(total)}\n"
                    f"Адрес: {url}\n"
                    "Временный файл будет удалён; запустите загрузку повторно."
                )

            progress.update(loaded, done=True)
        temporary.replace(destination)
    except HTTPError as error:
        temporary.unlink(missing_ok=True)
        reason = error.reason or "без пояснения"
        raise DownloadError(
            "Сервер не отдал запрошенный файл.\n"
            f"HTTP-статус: {error.code} {reason}\n"
            f"Адрес: {url}\n"
            "Проверьте имя репозитория, имя файла и доступность релиза."
        ) from None
    except URLError as error:
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            "Не удалось подключиться к серверу загрузки.\n"
            f"Причина: {error.reason}\n"
            f"Адрес: {url}\n"
            "Проверьте подключение к интернету и доступность сайта."
        ) from None
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            "Не удалось сохранить загружаемый файл.\n"
            f"Назначение: {_display_zemi_path(destination)}\n"
            f"Причина: {error}"
        ) from None
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _remote_size(url: str) -> int | None:
    """Получает полный размер удалённого файла, не скачивая его содержимое."""
    request = Request(
        url,
        headers={"User-Agent": "ZEMI", "Range": "bytes=0-0"},
    )
    try:
        with urlopen(request) as response:
            content_range = response.headers.get("Content-Range")
            if content_range and "/" in content_range:
                total = content_range.rsplit("/", 1)[1]
                if total.isdigit():
                    return int(total)

            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit():
                return int(content_length)
            return None
    except HTTPError as error:
        reason = error.reason or "без пояснения"
        raise DownloadError(
            "Не удалось проверить существующий файл на сервере.\n"
            f"HTTP-статус: {error.code} {reason}\n"
            f"Адрес: {url}"
        ) from None
    except URLError as error:
        raise DownloadError(
            "Не удалось проверить существующий файл: нет соединения с сервером.\n"
            f"Причина: {error.reason}\n"
            f"Адрес: {url}"
        ) from None


def _is_complete_file(path: Path, url: str) -> bool:
    """Сравнивает размер существующего файла с размером на сервере."""
    remote_size = _remote_size(url)
    if remote_size is None:
        raise DownloadError(
            "Сервер не сообщил размер файла; проверить целостность невозможно.\n"
            f"Файл: {_display_zemi_path(path)}\n"
            f"Адрес: {url}"
        )

    local_size = path.stat().st_size
    if local_size == remote_size:
        return True

    print(
        "Обнаружен неполный файл модели:\n"
        f"  файл: {_display_zemi_path(path)}\n"
        f"  загружено: {_format_size(local_size)}\n"
        f"  полный размер: {_format_size(remote_size)}\n"
        "Модель будет загружена заново."
    )
    return False


def download_llama(build: str, *, url: str | None = None) -> Path:
    """Скачивает и распаковывает Windows CPU-сборку llama.cpp в ZEMI Instance."""
    normalized_build = build.removeprefix("llama:")
    target = env.path.llama(normalized_build)
    server = target / "llama-server.exe"

    if server.is_file():
        print(
            f"llama.cpp {normalized_build} уже загружен: "
            f"{_display_zemi_path(target)}"
        )
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
                "Каталог llama.cpp существует, но не содержит "
                f"llama-server.exe: {_display_zemi_path(target)}"
            )
        source.replace(target)
    finally:
        archive.unlink(missing_ok=True)
        if extract_to.exists():
            shutil.rmtree(extract_to)

    print(
        f"llama.cpp {normalized_build} загружен: "
        f"{_display_zemi_path(target)}"
    )
    return target


def download_model(
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

    if url is None:
        if source.removesuffix(":") != "hf":
            raise ValueError("Для источника, отличного от hf, необходимо передать url")
        url = f"https://huggingface.co/{owner}/{repository}/resolve/main/{filename}"

    if target.is_file() and _is_complete_file(target, url):
        print(f"Модель уже загружена: {_display_zemi_path(target)}")
        return target

    print(f"Скачиваю модель {owner}/{repository}/{filename}...")
    _download(
        url,
        target,
        label=f"Модель {owner}/{repository}/{filename}",
    )
    print(f"Модель загружена: {_display_zemi_path(target)}")
    return target


def download_arsenal(config_path: str | Path) -> dict[str, dict[str, Path]]:
    """Загружает все сборки llama.cpp и модели из ``arsenal.llamas`` TOML-файла.

    Возвращает два словаря путей: ``llamas`` с ключами-именами серверов и
    ``models`` с ключами вида ``server/model``. При ожидаемой ошибке загрузки
    печатает понятное сообщение и возвращает уже загруженную часть Arsenal.
    """
    path = _resolve_zemi_path(config_path)

    print("═" * 78)
    print("ZEMI Playbook · загрузка Arsenal")
    print(f"Конфигурация: {_display_zemi_path(path)}")
    print("═" * 78)

    config = toml.load(path)
    try:
        llamas = config.arsenal.llamas
    except AttributeError as error:
        raise ValueError(
            "TOML должен содержать массив таблиц [[arsenal.llamas]]"
        ) from error

    llama_items = list(llamas.values())
    model_count = sum(len(llama.models) for llama in llama_items)
    print(
        f"Найдено серверов: {len(llama_items)} · "
        f"моделей: {model_count}"
    )

    result: dict[str, dict[str, Path]] = {
        "llamas": {},
        "models": {},
    }

    def stop_with_error(error: DownloadError) -> dict[str, dict[str, Path]]:
        print()
        print("!" * 78)
        print("ЗАГРУЗКА ОСТАНОВЛЕНА")
        print("!" * 78)
        print(error)
        print()
        print(
            f"Успешно обработано серверов: {len(result['llamas'])} · "
            f"моделей: {len(result['models'])}"
        )
        print("!" * 78)
        return result

    model_number = 0

    for llama_number, llama in enumerate(llama_items, start=1):
        llama_name = llama.name
        print()
        print("─" * 78)
        print(
            f"LLAMA-SERVER [{llama_number}/{len(llama_items)}] · "
            f"{llama_name} · {llama.llama_build}"
        )
        print("─" * 78)

        try:
            result["llamas"][llama_name] = download_llama(llama.llama_build)
        except DownloadError as error:
            return stop_with_error(DownloadError(
                f"Не удалось загрузить llama-server {llama_name!r} "
                f"({llama.llama_build}).\n\n{error}"
            ))

        for model in llama.models.values():
            model_number += 1
            model_name = model.name
            model_key = f"{llama_name}/{model_name}"
            print()
            print(
                f"  МОДЕЛЬ [{model_number}/{model_count}] · {model_key}\n"
                f"  {model.owner}/{model.repository}/{model.filename}"
            )

            try:
                result["models"][model_key] = download_model(
                    model.owner,
                    model.repository,
                    model.filename,
                    source=model.source,
                )
            except DownloadError as error:
                return stop_with_error(DownloadError(
                    f"Не удалось загрузить модель {model_key!r}.\n"
                    f"Модель: {model.owner}/{model.repository}/{model.filename}"
                    f"\n\n{error}"
                ))

    print()
    print("═" * 78)
    print(
        f"✓ Arsenal готов · серверов: {len(result['llamas'])} · "
        f"моделей: {len(result['models'])}"
    )
    print("═" * 78)
    return result
