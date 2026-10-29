
"""Исправление подписей PPI. Запуск: python test.py."""

import ast
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "eurostat_extra.py"

NEW_SOURCE_SHORT = dedent('''
def _source_short(source: str) -> str:
    """Короткое имя источника для сводной таблицы."""
    raw = str(source or "").strip()
    key = raw.casefold()

    for beginning, label in (
        ("eurostat/", "Eurostat"),
        ("росстат", "Росстат"),
        ("oea/dpiit", "OEA"),
        ("abs 6427", "ABS"),
        ("bls/", "BLS"),
        ("boj/", "BoJ"),
        ("nbs china/", "NBS"),
        ("ons/", "ONS"),
        ("ibge/", "IBGE"),
        ("statistics canada", "StatCan"),
        ("tcmb/", "TCMB"),
        ("un statistics division/", "UN MBS"),
        ("singstat dos", "SingStat"),
    ):
        if key.startswith(beginning):
            return label

    return raw or "источник не указан"
''').lstrip()

NEW_ENRICH_SUMMARY = dedent('''
def enrich_summary(
    summary: pd.DataFrame,
    extra: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Добавить официальные показатели с короткими подписями."""
    result = summary.copy()

    cutoff = pd.Period(
        f"{year}-{month:02d}", freq="M"
    ).end_time.normalize()

    for metric in DISPLAY_METRICS:
        result[metric] = None
        result[f"{metric}_date"] = None

    if extra is None or extra.empty:
        return result

    eligible = extra.loc[
        pd.to_datetime(extra["date"]).le(cutoff)
    ].sort_values("date")

    latest = eligible.drop_duplicates(
        ["country", "metric"],
        keep="last",
    )

    for obs in latest.itertuples(index=False):
        if obs.metric not in DISPLAY_METRICS:
            continue

        mask = result["country"].eq(obs.country)
        if not mask.any():
            continue

        date = pd.Timestamp(obs.date)
        source = str(obs.source)
        adjustment = str(obs.adjustment)

        quarterly = (
            obs.metric in ("gdp_qoq", "ppi_qoq")
            or (
                obs.country == "AU"
                and obs.metric == "ppi_yoy"
                and (
                    source.casefold().startswith("abs 6427")
                    or "quarterly" in adjustment.casefold()
                )
            )
        )

        period = (
            f"Q{date.quarter} {date.year}"
            if quarterly
            else f"{MONTHS[date.month]} {date.year}"
        )

        publisher = _source_short(source)

        provenance = (
            publisher
            if obs.metric.startswith("ppi_")
            else f"{publisher}, {adjustment}"
        )

        result.loc[mask, obs.metric] = round(
            float(obs.value), 2
        )

        result.loc[mask, f"{obs.metric}_date"] = (
            f"{period} ({provenance})"
        )

    return result
''').lstrip()


def main():
    if not TARGET.is_file():
        raise SystemExit(
            f"[FAIL] Файл не найден: {TARGET}"
        )

    original = TARGET.read_text(encoding="utf-8-sig")
    tree = ast.parse(original, filename=str(TARGET))

    functions = {}

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.setdefault(node.name, []).append(node)

    changes = {
        "_source_short": NEW_SOURCE_SHORT,
        "enrich_summary": NEW_ENRICH_SUMMARY,
    }

    for name in changes:
        if len(functions.get(name, [])) != 1:
            raise SystemExit(
                f"[FAIL] Ожидалась одна функция {name}"
            )

    if "DISPLAY_METRICS" not in original:
        raise SystemExit(
            "[FAIL] Интеграция PPI QoQ не обнаружена"
        )

    lines = original.splitlines(keepends=True)

    replacements = sorted(
        (
            (
                functions[name][0].lineno,
                functions[name][0].end_lineno,
                code,
            )
            for name, code in changes.items()
        ),
        reverse=True,
    )

    for start, end, code in replacements:
        lines[start - 1:end] = [code + "\n"]

    updated = "".join(lines)

    # Сначала проверяем синтаксис, затем заменяем файл.
    compile(updated, str(TARGET), "exec")
    TARGET.write_text(updated, encoding="utf-8")

    print("[FIX] Две функции заменены")
    print("[CHECK] Проверка нового процесса Python", flush=True)

    command = (
        "from src import eurostat_extra as e; "
        "from src.build_summary import build_summary; "
        "print('SHORT:', e._source_short('BLS/Final Demand')); "
        "s=build_summary(2026, 9).set_index('country'); "
        "print('RU:', s.loc['RU', 'ppi_yoy_date']); "
        "print('AU:', s.loc['AU', 'ppi_yoy_date'])"
    )

    subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        check=True,
    )

    print("[READ-ONLY] SQLite unchanged")


if __name__ == "__main__":
    main()
