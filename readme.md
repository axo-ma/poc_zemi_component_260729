Below is a structured `README.md` section (or complete documentation module) covering the architecture principles, layered dependencies, and the REST-mode stub mechanism for `llama-cpp-agent`.

---

# ZEMI PoC Sandbox setup

## LlamaIndex для локального llama.cpp

Интеграция LlamaIndex с моделью из ZEMI Arsenal использует адаптер
`OpenAILike`. Обычный пакет `llama-index-llms-openai` рассчитан на модели из
каталога OpenAI и не подходит для локальных alias вроде `qwen3.5-4b` без
некорректной подмены имени модели.

Установите официальный адаптер только в виртуальное окружение компонента:

```powershell
.\.venv\Scripts\python.exe -m pip install llama-index-llms-openai-like
```

Проверьте установку:

```powershell
.\.venv\Scripts\python.exe -c "from llama_index.llms.openai_like import OpenAILike; print('OK')"
```

`Assistant.clients.llama_index` автоматически получает из конфигурации Arsenal:

- адрес OpenAI API соответствующего llama-сервера;
- реальный `model.alias`;
- размер контекстного окна `model.ctx_size`;
- признак chat-модели.

Для RAG дополнительно нужны embedding-модель и vector store. Они настраиваются
в LlamaIndex отдельно от LLM; в качестве локального хранилища можно использовать
DuckDB.

Компактная, изолированная песочница для тестирования ETL, DuckDB и взаимодействия со сторонними фреймворками через локальный `llama-server.exe` (OpenAI REST API).

---

## 🛠️ Архитектурный принцип: In-Process vs REST Mode

Для обеспечения высокой отзывчивости UI (Streamlit) и полной изоляции процессов в ZEMI **запрещено использование прямого C++ инференса внутри процесса Python** (`llama-cpp-python`). Инференс выполняется исключительно внешним бинарником `llama-server.exe`.

Поскольку фреймворки `llama-cpp-agent` и `guidance` по умолчанию ожидают наличия C-биндингов `llama_cpp`, их интеграция в REST-режиме выполняется через лёгкую виртуальную заглушку (stub) без сборки C++ исходников и установки тяжелых компиляторов (MSVC / CMake).

---

## 📦 Послойная установка зависимостей

Зависимости разделены на 3 слоя для гигиены окружения и мгновенного отката:

* **Слой 1 (`reqs_base.txt`):** Core ETL (`python-calamine`, `openpyxl`, `markitdown`), DuckDB, FastEmbed, Streamlit.
* **Слой 2 (`reqs_orchestration.txt`):** DSPy, Instructor, Pydantic AI, BAML, Smolagents, LiteLLM.
* **Слой 3 (`reqs_experimental.txt`):** Outlines, Guidance, LlamaIndex Core, Unstructured Client.

---

## 🪄 Интеграция `llama-cpp-agent` в REST-режиме

### 1. Установка пакета без C++ зависимостей

Пакет устанавливается с флагом `--no-deps`, чтобы исключить автоматическую сборку `llama-cpp-python`:

```powershell
.\uv.exe pip install llama-cpp-agent --no-deps

```

---

### 2. Создание заглушки `llama_cpp.py`

Чтобы обойти жестко зашитые импорты (`import llama_cpp`, `from llama_cpp import LlamaGrammar`) в `llama-cpp-agent` и `guidance`, в каталог `site-packages` виртуального окружения помещается stub-файл:

* **Путь:** `.venv\Lib\site-packages\llama_cpp.py`
* **Содержимое:**

```python
"""
ZEMI REST-Mode Stub for llama_cpp.
Перехватывает обращения к C++ биндингам и перенаправляет вызовы на MagicMock,
обеспечивая работу llama-cpp-agent и guidance через llama-server.exe.
"""
from unittest.mock import MagicMock

def __getattr__(name: str):
    return MagicMock()

Llama = MagicMock
LlamaGrammar = MagicMock

```

---

## 🚀 Автоматическое развертывание (`setup_sandbox.bat`)

Для автоматической сборки окружения и автосоздания заглушки используйте итоговый сценарий развертывания:


## 🧪 Проверка состояния окружения

Запустите тестовый скрипт проверки всех 17 библиотек:

```powershell
.\.venv\Scripts\python.exe test_imports.py

```

При правильной настройке все модули (включая `python-calamine`, `llama-cpp-agent` и `guidance`) вернут статус `[OK]`.

---

## Запуск Jupyter-ноутбуков в VS Code

Ноутбуки проекта необходимо запускать через виртуальное окружение компонента:

```text
@comp/.venv/Scripts/python.exe
```

Для выполнения ячейки VS Code недостаточно обычного интерпретатора Python. В выбранном окружении также должны быть установлены `pip` и `ipykernel`. Если их нет, VS Code показывает сообщение:

```text
Running cells with 'Python 3.12.10' requires the ipykernel and pip package.
```

### Восстановление `pip`

Если команда `python -m pip` завершается ошибкой `No module named pip`, восстановите `pip` встроенным модулем Python:

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
```

Проверьте, что используется `pip` именно из окружения компонента:

```powershell
.\.venv\Scripts\python.exe -m pip --version
```

В выведенном пути должен присутствовать каталог `@comp/.venv`.

### Установка Jupyter-ядра

Установите `ipykernel` и необходимые ему зависимости в то же окружение:

```powershell
.\.venv\Scripts\python.exe -m pip install ipykernel
```

Проверьте установку:

```powershell
.\.venv\Scripts\python.exe -c "import ipykernel; print(ipykernel.__version__)"
```

### Выбор ядра в VS Code

1. Откройте файл `.ipynb`.
2. Нажмите **Select Kernel** или **Change Kernel** в правом верхнем углу редактора.
3. Выберите **Python Environments**.
4. Укажите интерпретатор `@comp/.venv/Scripts/python.exe`.
5. Запустите ячейку ещё раз.

Если VS Code продолжает показывать старое состояние окружения, выполните команду **Developer: Reload Window** через палитру команд и повторно выберите ядро. Нажимать кнопку **Install** во всплывающем окне после ручной установки уже не требуется.

Установка выполняется только в `@comp/.venv`: системный Python и базовая среда WinPython при этом не изменяются.
