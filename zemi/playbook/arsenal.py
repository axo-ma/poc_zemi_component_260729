"""Загрузка ресурсов Arsenal из конфигурации ZEMI Playbook."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .. import env, toml
from .llamas import DownloadError, download_llama, download_model


__all__ = ["Arsenal", "download"]


@dataclass
class Arsenal:
    """Загруженная конфигурация и ресурсы Arsenal."""

    config: toml.Table
    llamas: dict[str, Path] = field(default_factory=dict)
    models: dict[str, Path] = field(default_factory=dict)
    _processes: dict[str, subprocess.Popen] = field(
        default_factory=dict, init=False, repr=False
    )

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
        llama_items = list(self.config.arsenal.llamas.values())
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
        llama_items = list(self.config.arsenal.llamas.values())
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
            model = next(iter(llama.models.values()))
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
        llama_items = list(self.config.arsenal.llamas.values())
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

    def _server_path(self, llama: toml.Table) -> Path:
        directory = self.llamas.get(llama.name, env.path.llama(llama.llama_build))
        path = directory / "llama-server.exe"
        if not path.is_file():
            raise FileNotFoundError(f"llama-server.exe не найден: {path.resolve()}")
        return path

    def _model_path(self, llama: toml.Table, model: toml.Table) -> Path:
        key = f"{llama.name}/{model.name}"
        path = self.models.get(key)
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
        llama: toml.Table,
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

    def _write_router_preset(self, llama: toml.Table) -> Path:
        preset_path = env.path.tmp / f"zemi-arsenal-{llama.name}.ini"
        lines = ["version = 1", ""]
        for model in llama.models.values():
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

    result = Arsenal(config=config)

    def stop_with_error(error: DownloadError) -> Arsenal:
        print()
        print("!" * 78)
        print("ЗАГРУЗКА ОСТАНОВЛЕНА")
        print("!" * 78)
        print(error)
        print()
        print(
            f"Успешно обработано серверов: {len(result.llamas)} · "
            f"моделей: {len(result.models)}"
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
            result.llamas[llama_name] = download_llama(llama.llama_build)
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
                result.models[model_key] = download_model(
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
        f"✓ Arsenal готов · серверов: {len(result.llamas)} · "
        f"моделей: {len(result.models)}"
    )
    print("═" * 78)
    return result
