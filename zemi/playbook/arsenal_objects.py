"""Объектная модель дерева ZEMI Arsenal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Iterator, TypeVar, overload


__all__ = ["Assistant", "Llama", "Model", "NamedObjects"]


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
        return self.config["name"]


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
            NamedObjects([Assistant(config) for config in configs]),
        )

    @property
    def name(self) -> str:
        return self.config["name"]


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
        return self.config["name"]
