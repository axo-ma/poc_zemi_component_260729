# Минимальный пример использования модели

* bartowski/Qwen_Qwen3.5-4B-GGUF File: Qwen3.5-4B-Q4_K_M.gguf
* с использованием llama.cpp и openai Python client

## Вводные

Bartowski использовал llama.cpp b9222 для конвертации и квантования GGUF-файлов.

* <https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF>
* <https://github.com/ggml-org/llama.cpp/releases?page=3#release-b9992>

## Подготовка проекта

Структура каталогов

```text
.\ZEMI\
├── llama.cpp\
│   ├── llama-server.exe
│   ├── ggml-base.dll
│   ├── ggml-cpu.dll
│   └── ...
├── models\
│   └── Qwen3.5-4B-Q4_K_M.gguf 
└── minimal_chat.py
```

Разархивируйте в папку llama.cpp архив <https://github.com/ggml-org/llama.cpp/releases?page=3#release-b9992>

Cкачайте в папку models <https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/tree/main>

Откройте PowerShell:

```text
cd .\ZEMI
```

Запустите сервер:

```text
.\llama.cpp\llama-server.exe `
  --model ".\models\Qwen_Qwen3.5-4B-Q4_K_M.gguf" `
  --alias "qwen3.5-4b" `
  --host 127.0.0.1 `
  --port 8080 `
  --ctx-size 4096 `
  --threads 4 `
  --threads-batch 4 `
  --reasoning off
```

Проверьте работоспособность сервера:

```text
Invoke-RestMethod http://127.0.0.1:8080/v1/models |
    ConvertTo-Json -Depth 10
```

Ожидаемый фрагмент:

```text
{
  "data": [
    {
      "id": "qwen3.5-4b",
      "object": "model",
      "owned_by": "llamacpp"
    ...
```

Для чистого первого эксперимента оставляем:

```text
llama.cpp: b9222
openai:    1.82.0 в составе portable WinPython 3.12
```

Запускаем runme.ipynb
