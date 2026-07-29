"""Инструменты для работы с чатами в проекте ZEMI."""


def print_response(response) -> str:
    """Печатает ответ модели и статистику llama.cpp."""

    text = response.choices[0].message.content

    if text is None:
        raise RuntimeError("Модель вернула пустой ответ")

    print(text)

    usage = response.usage
    model_extra = response.model_extra or {}
    timings = model_extra.get("timings", {})

    print("\nСтатистика:")

    if usage is not None:
        print(f"Токены промпта:      {usage.prompt_tokens}")
        print(f"Токены генерации:    {usage.completion_tokens}")
        print(f"Всего токенов:       {usage.total_tokens}")
    else:
        print("Статистика токенов отсутствует")

    prompt_ms = timings.get("prompt_ms")
    prompt_per_second = timings.get("prompt_per_second")
    predicted_ms = timings.get("predicted_ms")
    predicted_per_second = timings.get("predicted_per_second")

    if prompt_ms is not None:
        print(f"Время префилла:      {prompt_ms / 1000:.2f} с")

    if prompt_per_second is not None:
        print(
            f"Скорость префилла:   "
            f"{prompt_per_second:.2f} ток/с"
        )

    if predicted_ms is not None:
        print(f"Время генерации:     {predicted_ms / 1000:.2f} с")

    if predicted_per_second is not None:
        print(
            f"Скорость генерации:  "
            f"{predicted_per_second:.2f} ток/с"
        )

    return text
