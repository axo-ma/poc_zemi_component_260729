import os
import sys

# Отключаем обязательную сетевую валидацию стоимости LiteLLM при импорте
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

def check_import(module_name: str, display_name: str = None) -> bool:
    name = display_name or module_name
    try:
        __import__(module_name)
        print(f"  [OK] {name:<25} — Успешно")
        return True
    except Exception as e:
        print(f"  [FAIL] {name:<23} — Ошибка: {e}")
        return False

def main():
    print(f"\n--- Проверка окружения Python {sys.version.split()[0]} ---")
    
    print("\nСлой 1: Base ETL & Data Engine")
    check_import("python_calamine", "python-calamine")
    check_import("openpyxl")
    check_import("markitdown")
    check_import("pandas")
    check_import("duckdb")
    check_import("fastembed")
    check_import("streamlit")

    print("\nСлой 2: Orchestration & Tool Calling")
    check_import("dspy")
    check_import("instructor")
    check_import("pydantic_ai", "pydantic-ai")
    check_import("baml_py", "baml-py")
    check_import("smolagents")
    check_import("litellm")

    print("\nСлой 3: Logit Masking & RAG Core")
    check_import("outlines")
    check_import("guidance")
    check_import("llama_index.core", "llama-index-core")
    check_import("unstructured_client", "unstructured-client")

    print("\n--- Тест завершен ---\n")

if __name__ == "__main__":
    main()