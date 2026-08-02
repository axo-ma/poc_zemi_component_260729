"""Расширенное чтение TOML-конфигураций ZEMI.

По сравнению со стандартным :mod:`tomllib` модуль выполняет дополнительную
обработку результата:

* строки ``@inst/...`` и ``@comp/...`` рекурсивно заменяются содержимым
  соответствующих UTF-8-файлов относительно корня ZEMI Instance или текущего
  ZEMI-компонента;
* TOML-таблицы возвращаются как :class:`Table`: их поля доступны и по ключу
  (``config["servers"]``), и через точку (``config.servers``);
* непустые массивы таблиц превращаются в :class:`NamedArray`; каждый их элемент
  доступен по позиции, включая отрицательные индексы, а элемент с непустым
  строковым ``name`` — также по имени;
* непустые имена внутри одного массива обязаны быть уникальными; отсутствие или
  пустое значение ``name`` разрешено и оставляет только доступ по индексу;
* обычные массивы значений и пустые массивы остаются Python-списками, а прочие
  TOML-типы сохраняют стандартное представление :mod:`tomllib`.

Основная точка входа — :func:`load`. Она принимает путь к TOML-файлу и
возвращает корневую :class:`Table` со всеми преобразованиями выше.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from . import env


_PATH_PREFIXES = {
    "@inst/": "inst",
    "@comp/": "comp",
}


class Table(dict[str, Any]):
    """TOML-таблица с доступом к ключам как к атрибутам."""

    def __getattribute__(self, name: str) -> Any:
        if not name.startswith("_") and dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        return super().__getattribute__(name)


class NamedArray(Table):
    """Массив именованных TOML-таблиц с доступом по имени и индексу."""

    def __getitem__(self, key: str | int) -> dict[str, Any]:
        if isinstance(key, int) and not isinstance(key, bool):
            values = tuple(dict.values(self))
            try:
                return values[key]
            except IndexError:
                raise IndexError(f"индекс именованного массива вне диапазона: {key}") from None
        return super().__getitem__(key)


def _read_reference(value: str) -> str:
    """Заменяет ссылку ZEMI содержимым указанного файла."""
    for prefix, root_name in _PATH_PREFIXES.items():
        if value.startswith(prefix):
            relative_path = value.removeprefix(prefix)
            file_path = getattr(env.path, root_name) / relative_path
            return file_path.read_text(encoding="utf-8")
    return value


def _prepare(value: Any, location: str = "root") -> Any:
    """Раскрывает ссылки и преобразует массивы таблиц в ``NamedArray``."""
    if isinstance(value, str):
        return _read_reference(value)
    if isinstance(value, dict):
        return Table({
            key: _prepare(item, f"{location}.{key}")
            for key, item in value.items()
        })
    if isinstance(value, list):
        items = [
            _prepare(item, f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
        if items and all(isinstance(item, dict) for item in items):
            named_items = NamedArray()
            for index, item in enumerate(items):
                name = dict.get(item, "name")
                if name is None or name == "":
                    named_items[index] = item
                    continue
                if not isinstance(name, str):
                    raise ValueError(
                        f"{location}[{index}].name должен быть строкой"
                    )
                if name in named_items:
                    raise ValueError(
                        f"повторяющееся имя {name!r} в массиве {location}"
                    )
                named_items[name] = item
            return named_items
        return items
    return value


def load(path: str | Path) -> dict[str, Any]:
    """Читает TOML, раскрывает ссылки и индексирует массивы таблиц по ``name``.

    Ссылкой считается строковое значение, начинающееся с одного из этих
    префиксов. Файл по ссылке читается как UTF-8, а его текст подставляется
    вместо исходной строки. Значения ``name`` внутри массива таблиц должны быть
    уникальны. Результирующий ``NamedArray`` поддерживает доступ по индексу ко
    всем элементам, а по имени — только к элементам с непустым ``name``.
    """
    with Path(path).open("rb") as file:
        data = tomllib.load(file)
    return _prepare(data)


__all__ = ["NamedArray", "Table", "load"]
