from __future__ import annotations

from pathlib import Path


INSTANCE_MARKERS = frozenset(
    {".zemiinst_dev", ".zemiinst_exp", ".zemiinst_prod"}
)
COMPONENT_MARKER = ".zemicomp"


def _start_directory(start_path: str | Path | None) -> Path:
    path = Path.cwd() if start_path is None else Path(start_path)
    return path.resolve() if path.is_dir() else path.resolve().parent


class _Paths:
    """Динамические пути текущих ZEMI Instance и Component."""

    @property
    def comp(self) -> Path:
        """Корень текущего ZEMI Component по маркеру .zemicomp."""
        for directory in (_start_directory(None), *_start_directory(None).parents):
            if (directory / COMPONENT_MARKER).is_file():
                return directory
        raise FileNotFoundError("Не найден корень ZEMI Component с маркером .zemicomp")

    @property
    def inst(self) -> Path:
        """Корень текущего ZEMI Instance по маркеру .zemiinst_*."""
        for directory in (_start_directory(None), *_start_directory(None).parents):
            if any((directory / marker).is_file() for marker in INSTANCE_MARKERS):
                return directory
        raise FileNotFoundError("Не найден корень ZEMI Instance с маркером .zemiinst_*")

    @property
    def tmp(self) -> Path:
        """Служебная папка _tmp текущего ZEMI Instance."""
        return self.inst / "_tmp"

    @property
    def llamas(self) -> Path:
        """Папка _llamas текущего ZEMI Instance."""
        return self.inst / "_llamas"

    @property
    def models(self) -> Path:
        """Папка _models текущего ZEMI Instance."""
        return self.inst / "_models"

    @property
    def pythons(self) -> Path:
        """Папка pythons текущего ZEMI Instance."""
        return self.inst / "pythons"


path = _Paths()
