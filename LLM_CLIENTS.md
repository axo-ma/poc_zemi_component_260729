# LLM-клиенты для llama.cpp

В проекте используется внешний `llama-server.exe`. Python-код не выполняет
инференс через `llama-cpp-python`, а обращается к серверу по HTTP.

## Список клиентов

| № | Клиент / библиотека | Интерфейс | Адрес | Назначение |
|---:|---|---|---|---|
| 1 | `openai` (Python SDK) | OpenAI REST API | `http://localhost:8080/v1` | Базовый OpenAI-совместимый HTTP-клиент |
| 2 | `litellm` | OpenAI REST API | `http://localhost:8080/v1` | Унифицированный клиент и маршрутизатор LLM |
| 3 | `dspy-ai` (импорт `dspy`) | OpenAI REST API | `http://localhost:8080/v1` | Клиент через `dspy.LM` |
| 4 | `instructor` | OpenAI REST API | `http://localhost:8080/v1` | Структурированный вывод через Pydantic поверх OpenAI-клиента |
| 5 | `pydantic-ai` | OpenAI REST API | `http://localhost:8080/v1` | Подключение через `OpenAIProvider` |
| 6 | `baml-py` | OpenAI REST API | `http://localhost:8080/v1` | Типизированные LLM-вызовы через OpenAI-совместимый провайдер |
| 7 | `smolagents` | OpenAI REST API | `http://localhost:8080/v1` | Подключение агентов через `OpenAIServerModel` |
| 8 | `llama-index-core` | OpenAI REST API | `http://localhost:8080/v1` | LLM-интеграция LlamaIndex; для класса OpenAI может потребоваться пакет `llama-index-llms-openai` |
| 9 | Native GBNF (`httpx` / `requests`) | Native llama-server REST API | `http://localhost:8080/completion` | Прямой HTTP POST с нативными параметрами llama.cpp и GBNF-грамматикой |
| 10 | `llama-cpp-agent` | Native llama-server REST API | `http://localhost:8080/completion` | Нативное подключение через `LlamaServerProvider` |
| 11 | `outlines` | OpenAI REST API | `http://localhost:8080/v1` | Подключение через `outlines.models.openai` |
| 12 | `guidance` | OpenAI REST API | `http://localhost:8080/v1` | Подключение через `guidance.models.OpenAI` |

## Примечания

- Клиенты OpenAI REST используют OpenAI-совместимый API, предоставляемый
  `llama-server.exe`. Они не зависят исключительно от llama.cpp и могут работать
  с другими совместимыми провайдерами.
- Native GBNF — не самостоятельная библиотека, а прямой способ обращения к
  нативному endpoint llama.cpp. В зависимостях проекта объявлен `httpx`, но не
  `requests`.
- `llama-cpp-agent>=0.2.0` устанавливается отдельно в `setup_sandbox.bat` с
  параметром `--no-deps`, чтобы не устанавливать `llama-cpp-python` и не
  выполнять C++-инференс внутри процесса Python.
- Для `llama-cpp-agent` и `guidance` проект предусматривает REST-режим с
  заглушкой модуля `llama_cpp`, описанной в `readme.md`.
