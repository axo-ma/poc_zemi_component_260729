"""Загрузка ресурсов Arsenal из конфигурации ZEMI Playbook."""

from __future__ import annotations

from pathlib import Path

from .. import env, toml
from .llamas import DownloadError, download_llama, download_model


__all__ = ["download"]


def _resolve_zemi_path(value: str | Path) -> Path:
    """Преобразует путь с маркером ZEMI в файловый путь."""
    path = str(value).replace("\\", "/")
    for prefix, root in (("@comp/", env.path.comp), ("@inst/", env.path.inst)):
        if path.startswith(prefix):
            return root / path.removeprefix(prefix)
    raise ValueError("Путь должен начинаться с @comp/ или @inst/")


def download(config_path: str | Path) -> dict[str, dict[str, Path]]:
    """Загружает все сборки llama.cpp и модели из ``arsenal.llamas`` TOML-файла.

    Возвращает два словаря путей: ``llamas`` с ключами-именами серверов и
    ``models`` с ключами вида ``server/model``. При ожидаемой ошибке загрузки
    печатает понятное сообщение и возвращает уже загруженную часть Arsenal.
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
