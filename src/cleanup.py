"""
Очистка временных файлов.

- Bloomberg-выгрузки старше N дней удаляются.
- Файлы NIFD-отчётов (PDF) старше N дней удаляются.
- Папка data/bloomberg/ создаётся автоматически, если её нет.
"""

from datetime import datetime, timedelta
from pathlib import Path
from config import DATA_DIR

BLOOMBERG_DIR = DATA_DIR / "bloomberg"
NIFD_DIR = DATA_DIR / "nifd_reports"

# Сколько дней хранить
BLOOMBERG_KEEP_DAYS = 180
NIFD_KEEP_DAYS = 90


def _cleanup_dir(directory: Path, keep_days: int, pattern: str = "*") -> int:
    """
    Удаляет файлы старше keep_days в указанной папке.
    Возвращает число удалённых файлов.
    """
    if not directory.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0

    for f in directory.glob(pattern):
        if not f.is_file():
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            try:
                f.unlink()
                removed += 1
                print(f"[CLEANUP] Удалён: {f.name} (mtime={mtime.date()})")
            except Exception as e:
                print(f"[CLEANUP] Не удалось удалить {f.name}: {e}")

    return removed


def cleanup_bloomberg():
    """Удаляет старые xlsx-выгрузки Bloomberg."""
    n = _cleanup_dir(BLOOMBERG_DIR, BLOOMBERG_KEEP_DAYS, pattern="*.xlsx")
    print(f"[CLEANUP] Bloomberg: удалено {n} файлов старше {BLOOMBERG_KEEP_DAYS} дней")


def cleanup_nifd():
    """Удаляет старые PDF-отчёты NIFD."""
    n = _cleanup_dir(NIFD_DIR, NIFD_KEEP_DAYS, pattern="*.pdf")
    print(f"[CLEANUP] NIFD: удалено {n} файлов старше {NIFD_KEEP_DAYS} дней")


def cleanup_all():
    """Запускает все очистки."""
    print("\n--- Очистка временных файлов ---")
    cleanup_bloomberg()
    cleanup_nifd()


def ensure_dirs():
    """Создаёт все рабочие папки, если их нет."""
    for d in (BLOOMBERG_DIR, NIFD_DIR):
        d.mkdir(parents=True, exist_ok=True)
