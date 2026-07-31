"""Экспериментальные инструменты ZEMI.

Код этого подмодуля рассчитан на интерактивные эксперименты и может
перезапускать общий для ZEMI Instance процесс llama-server.
"""

from . import chat, excel, llama, openai

__all__ = ["chat", "excel", "llama", "openai"]
