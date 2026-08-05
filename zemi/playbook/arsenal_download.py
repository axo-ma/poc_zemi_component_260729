"""Загрузка ресурсов и создание готового ZEMI Arsenal."""

from __future__ import annotations

from pathlib import Path

from .. import env, toml
from .arsenal import Arsenal
from .llamas import DownloadError, download_llama, download_model


__all__ = ["download"]


def _resolve_zemi_path(value: str | Path) -> Path:
    """Преобразует путь с маркером ZEMI в файловый путь."""
    path = str(value).replace("\\", "/")
    for prefix, root in (("@comp/", env.path.comp), ("@inst/", env.path.inst)):
        if path.startswith(prefix):
            return root / path.removeprefix(prefix)
    raise ValueError("Путь должен начинаться с @comp/ или @inst/")


def download(config_path: str | Path) -> Arsenal:
    """Загружает все сборки llama.cpp и модели из конфигурации Arsenal."""
    path = _resolve_zemi_path(config_path)
    config_label = str(config_path).replace("\\", "/")

    print("═" * 78)
    print("ZEMI Playbook · загрузка Arsenal")
    print(f"Конфигурация: {config_label}")
    print("═" * 78)

    result = Arsenal(config=toml.load(path))
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
