"""Безопасное описание ошибок FRED без URL и API-ключей."""


def safe_source_error(exc: Exception) -> str:
    """Выводим только тип исключения и HTTP-статус, не содержимое URL."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    status_part = f" HTTP {status}" if isinstance(status, int) else ""
    return f"{type(exc).__name__}{status_part}"
