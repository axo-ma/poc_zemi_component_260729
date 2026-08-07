# Путь разработчика: начало работы с ZEMI

## Prerequisites

До создания ZEMI Instance разработчик подготавливает рабочее место:

1. **Git** — обычная установка или portable-версия, на усмотрение разработчика.
2. **Visual Studio Code** — обычная установка или portable-версия.
3. Стандартные расширения VS Code:
   - Microsoft Python (`ms-python.python`);
   - Microsoft Jupyter (`ms-toolsai.jupyter`).
4. **7-Zip** — требуется для распаковки архива WinPython.
5. Доступ в интернет — для загрузки WinPython и клонирования репозитория.



## 1. Создание экспериментального ZEMI Instance

Чтобы создать папку для Zemi Instance запуcтите:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File .\create_zemi_instance.ps1
```

## 2. Загрузка WinPython 3.12

Чтобы скачать WinPython, запустите:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File .\download_winpython.ps1
```

Укажите путь к созданному ZEMI Instance. Его также можно передать параметром:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File .\download_winpython.ps1 `
    -InstancePath "<путь-к-ZEMI-Instance>"
```

Скрипт можно не запускать: скачайте
[Winpython64-3.12.10.1slim.7z](https://github.com/winpython/winpython/releases/download/16.6.20250620final/Winpython64-3.12.10.1slim.7z)
самостоятельно.

Архив сохранится в `@inst/_tmp`. Распакуйте его с помощью 7-Zip в:

```text
@inst/_pythons
```

Проверьте интерпретатор:

```text
@inst/_pythons/WPy64-312101/python/python.exe --version
```

Ожидаемая версия: `Python 3.12.10`.

## 3. Настройка VS Code

Клонируйте ZEMI Component в корень Instance. Для проектного окружения создайте
`@comp/.venv` поверх WinPython с параметром `--system-site-packages`.

Из корня компонента запустите:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File .\configure_vscode_python.ps1
```

Выберите `@comp/.venv` или базовый WinPython. Скрипт настроит VS Code и откроет
компонент. Дополнительные зависимости устанавливайте только в `@comp/.venv`.
Для новых терминалов `PATH` и `VIRTUAL_ENV` задаются только внутри workspace;
системный `PATH` Windows не изменяется.

Если portable VS Code не найден автоматически, укажите путь к `Code.exe` в
появившемся запросе или передайте его через `-CodePath`.

## 4. Сброс Python и Jupyter в VS Code

Полностью закройте VS Code. Из внешнего PowerShell запустите одной строкой:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\reset_vscode_python.ps1 -InstancePath "<ZEMI Instance>"
```

Для portable VS Code добавьте `-UserDataPath "<VS Code>\data\user-data\User"`.

Скрипт очищает Python/Jupyter-настройки профиля VS Code и `.vscode` в деревьях
компонентов. Непосредственные служебные каталоги Instance с именем `_...` не
сканируются. `.venv`, WinPython, пакеты, ноутбуки и пользовательские kernelspec
не удаляются. Резервная копия не создаётся. После открытия проекта VS Code заново
обнаружит локальную `.venv`. Предложение установить Python через `uv` отключается.
