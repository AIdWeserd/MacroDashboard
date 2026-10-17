"""
Снимки сводной таблицы для подсветки обновившихся метрик.

Логика:
- Раз в ISO-неделю (в первый запуск после наступления понедельника)
  сохраняем снимок build_summary() в таблицу summary_snapshots.
  В течение той же ISO-недели повторные запуски НЕ перезаписывают снимок.
- При рендере app.py берём последний снимок за ПРЕДЫДУЩУЮ ISO-неделю
  (или ещё более старый, если за предыдущую неделю снимка нет —
  например, scheduler падал). Сравниваем с ним, подсвечиваем
  изменившиеся и впервые появившиеся значения.
"""

import sqlite3
import pandas as pd
from config import DB_PATH

# Метрики сводной таблицы: (ключ в build_summary, человекочитаемое имя)
SUMMARY_METRICS = [
    ("inflation", "Инфляция YoY, %"),
    ("inflation_mom", "Инфляция MoM, %"),
    ("inflation_core", "Core CPI YoY, %"),
    ("unemployment", "Безработица, %"),
    ("debt_gdp", "Долг/ВВП, %"),
    ("budget_gdp", "Бюджет/ВВП, %"),
    ("trade_gdp", "Трейд/ВВП, %"),
    ("gdp_growth", "Рост ВВП, % YoY"),
    ("policy_rate", "Ставка ЦБ, %"),
]

TABLE = "summary_snapshots"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _ensure_table(con: sqlite3.Connection):
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            snapshot_date TEXT NOT NULL,
            country       TEXT NOT NULL,
            metric        TEXT NOT NULL,
            value         REAL,
            date_label    TEXT,
            PRIMARY KEY (snapshot_date, country, metric)
        )
    """)
    con.commit()


def _current_week_label() -> str:
    """ISO-метка текущей недели, например '2026-W41'."""
    iso_year, iso_week, _ = pd.Timestamp.now().isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _week_label_to_monday(label: str) -> pd.Timestamp | None:
    """'2026-W41' -> Timestamp понедельника этой ISO-недели."""
    try:
        year_str, week_str = label.split("-W")
        return pd.Timestamp.fromisocalendar(int(year_str), int(week_str), 1)
    except Exception:
        return None


def _week_label_of(ts: pd.Timestamp) -> str:
    """Timestamp -> ISO-метка недели, например '2026-W41'."""
    iso_year, iso_week, _ = ts.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _summary_to_long(summary: pd.DataFrame) -> pd.DataFrame:
    """Превращает wide-таблицу build_summary() в long-формат для снапшота."""
    rows = []
    for _, r in summary.iterrows():
        country = r["country"]
        for metric_key, _ in SUMMARY_METRICS:
            value = r.get(metric_key)
            date_label = r.get(f"{metric_key}_date")
            rows.append({
                "country": country,
                "metric": metric_key,
                "value": None if pd.isna(value) else float(value),
                "date_label": None if pd.isna(date_label) else str(date_label),
            })
    return pd.DataFrame(rows)


def save_weekly_snapshot(force: bool = False) -> str | None:
    """
    Сохраняет снимок build_summary() раз в ISO-неделю.

    Поведение:
    - Определяем текущую ISO-неделю (например, '2026-W41').
    - Если снимок за эту неделю уже есть и force=False — не перезаписываем.
      Это гарантирует, что сколько бы раз в течение недели ни запускался
      scheduler, снимок недели не меняется.
    - При наступлении понедельника следующей недели метка недели меняется,
      и первый же запуск сохранит новый снимок.
    - force=True — принудительная перезапись (для отладки).
    """
    from src.build_summary import build_summary

    week_label = _current_week_label()

    with _connect() as con:
        _ensure_table(con)

        if not force:
            exists = con.execute(
                f"SELECT 1 FROM {TABLE} WHERE snapshot_date = ? LIMIT 1",
                (week_label,),
            ).fetchone()
            if exists:
                print(f"[SKIP] snapshot {week_label}: уже сохранён на этой неделе")
                return week_label

        summary = build_summary()
        if summary.empty:
            print("[SKIP] snapshot: build_summary() пуст")
            return None

        long_df = _summary_to_long(summary)
        long_df.insert(0, "snapshot_date", week_label)

        # force=True или новая неделя — на всякий случай чистим старую запись
        con.execute(f"DELETE FROM {TABLE} WHERE snapshot_date = ?", (week_label,))
        long_df.to_sql(TABLE, con, if_exists="append", index=False)
        con.commit()

    print(f"[SAVE] snapshot {week_label}: {len(long_df)} строк")
    return week_label


def load_previous_snapshot() -> pd.DataFrame:
    """
    Читает последний снимок за ПРЕДЫДУЩУЮ ISO-неделю.

    Логика:
    - Берём текущую ISO-неделю (например, '2026-W41').
    - Ищем снимки, чья ISO-неделя СТРОГО меньше текущей.
    - Из них берём самый свежий.
    - Если за предыдущую неделю снимка нет (scheduler падал) —
      автоматически откатываемся на ещё более старую.

    Возвращает long-DataFrame: snapshot_date, country, metric, value, date_label.
    Если снимков за прошлые недели нет — пустой DataFrame.
    """
    current_label = _current_week_label()
    current_monday = _week_label_to_monday(current_label)

    with _connect() as con:
        _ensure_table(con)
        try:
            df = pd.read_sql(
                f"SELECT DISTINCT snapshot_date FROM {TABLE}",
                con,
            )
        except Exception:
            return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Оставляем только те недели, что строго раньше текущей
    candidates: list[tuple[str, pd.Timestamp]] = []
    for s in df["snapshot_date"]:
        monday = _week_label_to_monday(s)
        if monday is None:
            continue
        if current_monday is not None and monday < current_monday:
            candidates.append((s, monday))

    if not candidates:
        return pd.DataFrame()

    # Самый свежий из подходящих
    candidates.sort(key=lambda x: x[1], reverse=True)
    chosen = candidates[0][0]

    with _connect() as con:
        snap = pd.read_sql(
            f"SELECT * FROM {TABLE} WHERE snapshot_date = ?",
            con,
            params=(chosen,),
        )

    if snap.empty:
        return pd.DataFrame()

    print(f"[LOAD] snapshot {chosen}: {len(snap)} строк (предыдущая неделя)")
    return snap


def compare_with_previous(summary: pd.DataFrame,
                          previous: pd.DataFrame) -> set[tuple[str, str]]:
    """
    Сравнивает текущий build_summary() с прошлым снимком.

    Возвращает множество (country, metric), которые надо подсветить:
    - значение изменилось (в любую сторону, на любую величину);
    - значение появилось впервые (было None, стало число).

    Если previous пуст — возвращает пустое множество (ничего не подсвечиваем).
    """
    if previous.empty or summary.empty:
        return set()

    prev_map: dict[tuple[str, str], float | None] = {}
    for _, r in previous.iterrows():
        prev_map[(r["country"], r["metric"])] = (
            None if pd.isna(r["value"]) else float(r["value"])
        )

    changed: set[tuple[str, str]] = set()
    for _, r in summary.iterrows():
        country = r["country"]
        for metric_key, _ in SUMMARY_METRICS:
            new_val = r.get(metric_key)
            new_val = None if pd.isna(new_val) else float(new_val)

            old_val = prev_map.get((country, metric_key), None)

            # Появилось впервые
            if old_val is None and new_val is not None:
                changed.add((country, metric_key))
                continue

            # Оба None — не подсвечиваем
            if old_val is None and new_val is None:
                continue

            # Оба числа — сравниваем
            if old_val is not None and new_val is not None:
                if abs(old_val - new_val) > 1e-9:
                    changed.add((country, metric_key))

            # old_val число, new_val None — не подсвечиваем
            # (метрика пропала, не обновилась)

    return changed
