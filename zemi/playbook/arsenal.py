"""Загрузка ресурсов Arsenal из конфигурации ZEMI Playbook."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Iterator, TypeVar, overload
from urllib.error import URLError
from urllib.request import urlopen

from .. import env, toml
from .llamas import DownloadError, download_llama, download_model


__all__ = ["Arsenal", "Assistant", "Llama", "Model", "NamedObjects", "download"]


_T = TypeVar("_T")


class _ConfigObject:
    """Предметный объект с доступом к значениям исходной конфигурации."""

    config: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.config[name]
        except KeyError:
            raise AttributeError(name) from None


class NamedObjects(Generic[_T]):
    """Упорядоченная коллекция объектов с доступом по индексу и имени."""

    def __init__(self, items: list[_T]) -> None:
        self._items = tuple(items)
        self._by_name = {item.name: item for item in items}

    @overload
    def __getitem__(self, key: int) -> _T: ...

    @overload
    def __getitem__(self, key: str) -> _T: ...

    def __getitem__(self, key: int | str) -> _T:
        return self._items[key] if isinstance(key, int) else self._by_name[key]

    def __getattr__(self, name: str) -> _T:
        try:
            return self._by_name[name]
        except KeyError:
            raise AttributeError(name) from None

    def __iter__(self) -> Iterator[_T]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def keys(self):
        return self._by_name.keys()

    def values(self):
        return self._by_name.values()

    def items(self):
        return self._by_name.items()


@dataclass(frozen=True)
class Assistant(_ConfigObject):
    """Ассистент модели и его исходная TOML-конфигурация."""

    config: dict[str, Any]

    @property
    def name(self) -> str:
        return self.config.name


@dataclass(frozen=True)
class Model(_ConfigObject):
    """Модель llama-сервера, её ассистенты и TOML-конфигурация."""

    config: dict[str, Any]
    assistants: NamedObjects[Assistant] = field(init=False)

    def __post_init__(self) -> None:
        configs = self.config.get("assistants", [])
        object.__setattr__(
            self,
            "assistants",
            NamedObjects([
                Assistant(config)
                for config in configs
            ]),
        )

    @property
    def name(self) -> str:
        return self.config.name


@dataclass(frozen=True)
class Llama(_ConfigObject):
    """Llama-сервер, его модели и исходная TOML-конфигурация."""

    config: dict[str, Any]
    models: NamedObjects[Model] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "models",
            NamedObjects([Model(config) for config in self.config["models"]]),
        )

    @property
    def name(self) -> str:
        return self.config.name


@dataclass
class Arsenal:
    """Загруженная конфигурация и ресурсы Arsenal."""

    config: dict[str, Any]
    llamas: NamedObjects[Llama] = field(init=False)
    _llama_paths: dict[str, Path] = field(default_factory=dict, repr=False)
    _model_paths: dict[str, Path] = field(default_factory=dict, repr=False)
    _processes: dict[str, subprocess.Popen] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        try:
            configs = self.config["arsenal"]["llamas"]
        except (KeyError, TypeError) as error:
            raise ValueError(
                "TOML должен содержать массив таблиц [[arsenal.llamas]]"
            ) from error
        if not isinstance(configs, list):
            raise ValueError("arsenal.llamas должен быть массивом таблиц")
        self.llamas = NamedObjects([Llama(config) for config in configs])

    def begin_playbook(
        self,
        stop_arsenal_before_begin: bool,
        llama_router_mode: bool = False,
    ) -> None:
        """Начинает работу playbook."""
        if stop_arsenal_before_begin:
            self._stop_arsenal()

        if llama_router_mode:
            self._begin_playbook_with_router_mode()
        else:
            self._begin_playbook_without_router_mode()

    def end_playbook(self, stop_arsenal_after_end: bool) -> None:
        """Завершает работу playbook."""
        if stop_arsenal_after_end:
            self._stop_arsenal()

    def _begin_playbook_with_router_mode(self) -> None:
        """Начинает работу playbook в режиме llama router."""
        llama_items = list(self.llamas)
        self._print_operation_header(
            "ЗАПУСК ARSENAL · ROUTER MODE",
            len(llama_items),
        )

        for number, llama in enumerate(llama_items, start=1):
            preset_path = self._write_router_preset(llama)
            command = [
                str(self._server_path(llama)),
                "--models-preset", str(preset_path),
                "--host", llama.host,
                "--port", str(llama.port),
            ]
            self._start_server(llama, command, number, len(llama_items))

        self._print_operation_result("✓ Все llama-серверы готовы")

    def _begin_playbook_without_router_mode(self) -> None:
        """Начинает работу playbook без режима llama router."""
        llama_items = list(self.llamas)
        self._print_operation_header(
            "ЗАПУСК ARSENAL · MODEL MODE",
            len(llama_items),
        )
        invalid = [
            f"{llama.name} ({len(llama.models)} моделей)"
            for llama in llama_items
            if len(llama.models) != 1
        ]
        if invalid:
            details = ", ".join(invalid)
            print(f"✗ Проверка конфигурации не пройдена: {details}")
            print("═" * 78)
            raise ValueError(
                "Без Router Mode каждый llama-сервер должен содержать ровно "
                f"одну модель. Нарушение: {details}"
            )

        for number, llama in enumerate(llama_items, start=1):
            model = next(iter(llama.models))
            command = [
                str(self._server_path(llama)),
                "--model", str(self._model_path(llama, model)),
                "--alias", model.alias,
                "--host", llama.host,
                "--port", str(llama.port),
                "--ctx-size", str(model.ctx_size),
                "--threads", str(model.threads),
                "--threads-batch", str(model.threads_batch),
                "--reasoning", model.reasoning,
            ]
            self._start_server(llama, command, number, len(llama_items))

        self._print_operation_result("✓ Все llama-серверы готовы")

    def _stop_arsenal(self) -> None:
        """Останавливает работающие ресурсы Arsenal."""
        llama_items = list(self.llamas)
        self._print_operation_header("ОСТАНОВКА ARSENAL", len(llama_items))

        for number, llama in enumerate(llama_items, start=1):
            print(
                f"[{number}/{len(llama_items)}] {llama.name} · "
                f"{llama.host}:{llama.port}"
            )
            process = self._processes.pop(llama.name, None)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                print(f"    ✓ остановлен · PID {process.pid}")
            elif self._stop_server_on_port(llama.port):
                print("    ✓ найден и остановлен")
            else:
                print("    · не запущен")

        self._print_operation_result("✓ Arsenal остановлен")

    @staticmethod
    def _print_operation_header(title: str, server_count: int) -> None:
        print()
        print("═" * 78)
        print(f"ZEMI Playbook · {title}")
        print(f"Llama-серверов: {server_count}")
        print("═" * 78)

    @staticmethod
    def _print_operation_result(message: str) -> None:
        print("═" * 78)
        print(message)
        print("═" * 78)

    def _server_path(self, llama: Llama) -> Path:
        directory = self._llama_paths.get(
            llama.name, env.path.llama(llama.llama_build)
        )
        path = directory / "llama-server.exe"
        if not path.is_file():
            raise FileNotFoundError(f"llama-server.exe не найден: {path.resolve()}")
        return path

    def _model_path(self, llama: Llama, model: Model) -> Path:
        key = f"{llama.name}/{model.name}"
        path = self._model_paths.get(key)
        if path is None:
            path = env.path.model(
                model.owner,
                model.repository,
                model.filename,
                source=model.source,
            ) / model.filename
        if not path.is_file():
            raise FileNotFoundError(f"Файл модели не найден: {path.resolve()}")
        return path

    def _start_server(
        self,
        llama: Llama,
        command: list[str],
        number: int,
        total: int,
    ) -> None:
        print()
        print(
            f"[{number}/{total}] Запускаю {llama.name} · "
            f"{llama.host}:{llama.port}"
        )
        if self._is_server_ready(llama.host, llama.port):
            raise RuntimeError(
                f"На {llama.host}:{llama.port} уже работает HTTP-сервер. "
                "Используйте stop_arsenal_before_begin=True для остановки Arsenal."
            )

        process = subprocess.Popen(command)
        self._processes[llama.name] = process
        deadline = time.monotonic() + float(llama.startup_timeout)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._processes.pop(llama.name, None)
                raise RuntimeError(
                    f"llama-server {llama.name!r} завершился с кодом "
                    f"{process.returncode}"
                )
            if self._is_server_ready(llama.host, llama.port):
                print(f"    ✓ готов · PID {process.pid}")
                return
            time.sleep(0.5)

        process.terminate()
        self._processes.pop(llama.name, None)
        raise TimeoutError(
            f"llama-server {llama.name!r} не запустился за "
            f"{float(llama.startup_timeout):.1f} секунд"
        )

    def _write_router_preset(self, llama: Llama) -> Path:
        preset_path = env.path.tmp / f"zemi-arsenal-{llama.name}.ini"
        lines = ["version = 1", ""]
        for model in llama.models:
            lines.extend([
                f"[{model.alias}]",
                f"model = {self._model_path(llama, model)}",
                f"ctx-size = {model.ctx_size}",
                f"threads = {model.threads}",
                f"threads-batch = {model.threads_batch}",
                f"reasoning = {model.reasoning}",
                "",
            ])
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        preset_path.write_text("\n".join(lines), encoding="utf-8")
        print(
            f"    Пресет {llama.name}: {len(llama.models)} моделей · "
            f"{preset_path}"
        )
        return preset_path

    @staticmethod
    def _is_server_ready(host: str, port: int, timeout: float = 0.5) -> bool:
        try:
            with urlopen(f"http://{host}:{port}/health", timeout=timeout):
                return True
        except (URLError, TimeoutError):
            return False

    @staticmethod
    def _stop_server_on_port(port: int) -> bool:
        command = f"""
        $connection = Get-NetTCPConnection -LocalPort {port} -State Listen `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $connection) {{ Write-Output 'NOT_FOUND'; exit }}
        $process = Get-Process -Id $connection.OwningProcess `
            -ErrorAction SilentlyContinue
        if (-not $process) {{ Write-Output 'NOT_FOUND'; exit }}
        if ($process.ProcessName -ne 'llama-server') {{
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
            return True
        if output == "NOT_FOUND":
            return False
        if output.startswith("WRONG_PROCESS:"):
            _, process_name, pid = output.split(":", 2)
            raise RuntimeError(
                f"Порт {port} занят другим процессом: {process_name}, PID {pid}"
            )
        error = result.stderr.strip() or output or "неизвестная ошибка"
        raise RuntimeError(f"Не удалось остановить сервер на порту {port}: {error}")


def _resolve_zemi_path(value: str | Path) -> Path:
    """Преобразует путь с маркером ZEMI в файловый путь."""
    path = str(value).replace("\\", "/")
    for prefix, root in (("@comp/", env.path.comp), ("@inst/", env.path.inst)):
        if path.startswith(prefix):
            return root / path.removeprefix(prefix)
    raise ValueError("Путь должен начинаться с @comp/ или @inst/")


def download(config_path: str | Path) -> Arsenal:
    """Загружает все сборки llama.cpp и модели из ``arsenal.llamas`` TOML-файла.

    Возвращает объект :class:`Arsenal` с загруженной TOML-конфигурацией и двумя
    словарями путей: ``llamas`` с ключами-именами серверов и ``models`` с ключами
    вида ``server/model``. При ожидаемой ошибке загрузки печатает понятное
    сообщение и возвращает уже загруженную часть Arsenal.
    """
    path = _resolve_zemi_path(config_path)
    config_label = str(config_path).replace("\\", "/")

    print("═" * 78)
    print("ZEMI Playbook · загрузка Arsenal")
    print(f"Конфигурация: {config_label}")
    print("═" * 78)

    config = toml.load(path)
    result = Arsenal(config=config)
    llama_items = list(result.llamas)
    model_count = sum(len(llama.models) for llama in llama_items)
    print(
        f"Найдено серверов: {len(llama_items)} · "
        f"моделей: {model_count}"
    )

    def stop_with_error(error: DownloadError) -> Arsenal:
        print()
        print("!" * 78)
        print("ЗАГРУЗКА ОСТАНОВЛЕНА")
        print("!" * 78)
        print(error)
        print()
        print(
            f"Успешно обработано серверов: {len(result._llama_paths)} · "
            f"моделей: {len(result._model_paths)}"
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
            result._llama_paths[llama_name] = download_llama(llama.llama_build)
        except DownloadError as error:
            return stop_with_error(DownloadError(
                f"Не удалось загрузить llama-server {llama_name!r} "
                f"({llama.llama_build}).\n\n{error}"
            ))

        for model in llama.models:
            model_number += 1
            model_name = model.name
            model_key = f"{llama_name}/{model_name}"
            print()
            print(
                f"  МОДЕЛЬ [{model_number}/{model_count}] · {model_key}\n"
                f"  {model.owner}/{model.repository}/{model.filename}"
            )

            try:
                result._model_paths[model_key] = download_model(
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
        f"✓ Arsenal готов · серверов: {len(result._llama_paths)} · "
        f"моделей: {len(result._model_paths)}"
    )
    print("═" * 78)
    return result
