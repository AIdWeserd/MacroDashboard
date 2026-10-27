
"""Macro Dashboard data update scheduler.

Usage:
    python scheduler.py
    python scheduler.py ppi_national
    python scheduler.py ppi_turkey
    python scheduler.py eurostat_extra
    python scheduler.py --dry-run ppi_national ppi_turkey
    python scheduler.py --list
"""

import sys
import re
from functools import partial

from src.eurostat_extra import (
    fetch_eurostat_extra,
    save_eurostat_extra,
    load_eurostat_extra,
)

from src.ppi_canada import fetch_canada_ppi
from src.ppi_uk import fetch_uk_ppi
from src.ppi_china import fetch_china_ppi
from src.ppi_turkey import fetch_turkey_ppi

from src.ppi_national import (
    BOJ_HISTORY,
    _http_get,
    _update_japan_mom,
    fetch_us_history,
    parse_boj_yoy_history,
)

from src.fetch_fred import fetch_all_macro
from src.fetch_fred_unemployment import fetch_fred_unemployment
from src.fetch_fred_gdp import fetch_fred_gdp
from src.fetch_rss import fetch_news
from src.fetch_forexfactory import fetch_calendar
from src.fetch_imf import fetch_all_imf
from src.fetch_eurostat import fetch_eurostat_hicp
from src.fetch_eurostat_unemployment import fetch_eurostat_unemployment
from src.fetch_eurostat_quarterly import fetch_eurostat_quarterly
from src.fetch_eurostat_annual import fetch_eurostat_annual
from src.fetch_singapore_mom import fetch_singapore_unemployment
from src.fetch_singapore_cpi import fetch_singapore_cpi
from src.fetch_singapore_gdp import fetch_singapore_gdp
from src.fetch_singapore_quarterly import fetch_singapore_quarterly
from src.fetch_brazil_ibge import fetch_brazil_unemployment
from src.fetch_brazil_cpi import fetch_brazil_cpi
from src.fetch_brazil_gdp import fetch_brazil_gdp
from src.fetch_brazil_quarterly import fetch_brazil_quarterly
from src.fetch_uk_quarterly import fetch_uk_quarterly
from src.fetch_japan_quarterly import fetch_japan_quarterly
from src.fetch_korea_quarterly import fetch_korea_quarterly
from src.fetch_australia_quarterly import fetch_australia_quarterly
from src.fetch_switzerland_quarterly import fetch_switzerland_quarterly
from src.fetch_canada_quarterly import fetch_canada_quarterly
from src.fetch_policy_rates import fetch_policy_rates
from src.fetch_china_unemployment import fetch_china_unemployment
from src.fetch_china_core_cpi import fetch_china_core_cpi
from src.fetch_india_unemployment import fetch_india_unemployment
from src.fetch_fred_cpi import fetch_fred_cpi
from src.fetch_china_cpi import fetch_china_cpi
from src.fetch_india_cpi import fetch_india_cpi
from src.fetch_india_gdp import fetch_india_gdp
from src.fetch_uk_ons import fetch_uk_cpi
from src.fetch_canada_cpi import fetch_canada_cpi
from src.fetch_australia_cpi import fetch_australia_cpi
from src.fetch_turkey_cpi import fetch_turkey_cpi
from src.fetch_switzerland_cpi import fetch_switzerland_cpi
from src.fetch_switzerland_unemployment import fetch_switzerland_unemployment
from src.fetch_switzerland_gdp import fetch_switzerland_gdp
from src.fetch_japan_cpi import fetch_japan_cpi
from src.fetch_korea_cpi import fetch_korea_cpi
from src.fetch_nifd_report import fetch_all_nifd_debt
from src.fetch_china_fiscal import fetch_china_fiscal
from src.fetch_china_gdp import fetch_china_gdp
from src.fetch_us import fetch_us_quarterly
from src.fetch_us_bea import fetch_us_general_gov_annual
from src.fetch_bloomberg import fetch_bloomberg
from src.snapshot import save_weekly_snapshot
from src.cleanup import cleanup_all, ensure_dirs
from src.fetch_china_debt_fred import fetch_china_debt_fred
from src.fetch_russia import fetch_russia_cpi, fetch_russia_quarterly
from src.Russia.rates import fetch_russia_rates
from src.Russia.credit import fetch_russia_credit
from src.Russia.mortgage import fetch_russia_mortgage
from src.Russia.money import fetch_russia_money
from src.Russia.trade import fetch_russia_trade, fetch_russia_trade_estimates
from src.Russia.investors import fetch_russia_investors
from src.Russia.cbr_reference import fetch_russia_cbr_reference
from src.Russia.ruonia import fetch_russia_ruonia

from src.storage import (
    save_fred,
    save_rss,
    save_forexfactory,
    save_imf,
    save_eurostat,
    save_eurostat_unemployment,
    save_eurostat_quarterly,
    save_eurostat_annual,
    save_fred_unemployment,
    save_fred_gdp,
    save_singapore_unemployment,
    save_singapore_cpi,
    save_singapore_gdp,
    save_singapore_quarterly,
    save_brazil_unemployment,
    save_brazil_cpi,
    save_brazil_gdp,
    save_brazil_quarterly,
    save_uk_quarterly,
    save_japan_quarterly,
    save_korea_quarterly,
    save_australia_quarterly,
    save_switzerland_quarterly,
    save_canada_quarterly,
    save_policy_rates,
    save_china_unemployment,
    save_china_core_cpi,
    save_india_unemployment,
    save_india_gdp,
    save_fred_cpi,
    save_china_cpi,
    save_india_cpi,
    save_uk_cpi,
    save_canada_cpi,
    save_australia_cpi,
    save_turkey_cpi,
    save_switzerland_cpi,
    save_switzerland_unemployment,
    save_japan_cpi,
    save_korea_cpi,
    save_china_debt,
    save_china_fiscal,
    save_china_gdp,
    save_switzerland_gdp,
    save_us_quarterly,
    save_us_annual_bea,
    save_bloomberg,
    save_china_debt_fred,
    save_russia_cpi,
    save_russia_quarterly,
    save_russia_rates,
    save_russia_credit,
    save_russia_mortgage,
    save_russia_money,
    save_russia_trade,
    save_russia_trade_estimates,
    save_russia_investors,
    save_russia_cbr_reference,
    save_russia_ruonia,
)


def _safe_error(exc: Exception) -> str:
    """Redact common credential parameters from error messages."""

    message = str(exc)

    message = re.sub(
        r"(?i)([?&\s](?:api[_-]?key|apikey|access[_-]?token|"
        r"auth[_-]?token|token|client[_-]?secret|password|secret|key)"
        r"\s*[:=]\s*)[^&\s,;]+",
        r"\1[REDACTED]",
        message,
    )

    return f"{type(exc).__name__}: {message}"


def _step(name: str, fetch_fn, save_fn) -> str:
    """Run one independent update step."""

    print(f"\n--- {name} ---")

    try:
        data = fetch_fn()

        if data is None or data.empty:
            print(
                f"[WARN] {name}: источник не вернул данных; "
                "сохранение пропущено"
            )
            return "empty"

        issues = tuple(
            data.attrs.get("source_issues", ())
        )

        save_fn(data)

        if issues:
            print(
                f"[WARN] {name}: частичная загрузка; "
                + ", ".join(map(str, issues))
            )
            return "partial"

        print(
            f"[OK] {name}: загрузка и сохранение завершены"
        )
        return "ok"

    except Exception as exc:
        print(
            f"[ERROR] {name}: {_safe_error(exc)}"
        )
        return "error"


def _fetch_japan_ppi_yoy():
    return parse_boj_yoy_history(
        _http_get(BOJ_HISTORY).text
    )


def _fetch_japan_ppi_mom():
    """BoJ archive already saves each individual month."""

    complete = _update_japan_mom()

    data = load_eurostat_extra()

    data = data.loc[
        (data.country == "JP")
        & (data.metric == "ppi_mom")
    ].copy()

    if data.empty:
        raise ValueError(
            "BoJ CGPI MoM: no stored observations"
        )

    if not complete:
        data.attrs["source_issues"] = (
            "BoJ CGPI MoM: incomplete archive",
        )

    return data


def _already_saved(_data):
    """BoJ PDF months were saved by the fetcher."""
    return None


GROUPS = {
    "bbg": [
        ("Bloomberg: ручные выгрузки", fetch_bloomberg, save_bloomberg),
    ],
    "rates": [
        ("Ставки ЦБ (все страны)", fetch_policy_rates, save_policy_rates),
    ],
    "us": [
        ("США: квартальные метрики (Treasury + BEA)", fetch_us_quarterly, save_us_quarterly),
        ("США: годовые General Gov (BEA + FRED)", fetch_us_general_gov_annual, save_us_annual_bea),
    ],
    "sg": [
        ("Сингапур: безработица", fetch_singapore_unemployment, save_singapore_unemployment),
        ("Сингапур: CPI", fetch_singapore_cpi, save_singapore_cpi),
        ("Сингапур: квартальный рост ВВП", fetch_singapore_gdp, save_singapore_gdp),
        ("Сингапур: квартальные метрики (Debt + Budget + CA)", fetch_singapore_quarterly, save_singapore_quarterly),
    ],
    "br": [
        ("Бразилия: безработица", fetch_brazil_unemployment, save_brazil_unemployment),
        ("Бразилия: CPI", fetch_brazil_cpi, save_brazil_cpi),
        ("Бразилия: квартальный рост ВВП (SIDRA)", fetch_brazil_gdp, save_brazil_gdp),
        ("Бразилия: квартальные метрики (BCB SGS)", fetch_brazil_quarterly, save_brazil_quarterly),
    ],
    "gb": [
        ("Великобритания: квартальные метрики (ONS)", fetch_uk_quarterly, save_uk_quarterly),
        ("Великобритания: CPI", fetch_uk_cpi, save_uk_cpi),
    ],
    "jp": [
        ("Япония: квартальные метрики (MOF + e-Stat)", fetch_japan_quarterly, save_japan_quarterly),
        ("Япония: CPI", fetch_japan_cpi, save_japan_cpi),
    ],
    "kr": [
        ("Южная Корея: квартальные метрики (IMF DSBB)", fetch_korea_quarterly, save_korea_quarterly),
        ("Южная Корея: CPI", fetch_korea_cpi, save_korea_cpi),
    ],
    "au": [
        ("Австралия: квартальный Трейд/ВВП (ABS)", fetch_australia_quarterly, save_australia_quarterly),
        ("Австралия: CPI", fetch_australia_cpi, save_australia_cpi),
    ],
    "ca": [
        ("Канада: квартальные метрики (StatCan WDS)", fetch_canada_quarterly, save_canada_quarterly),
        ("Канада: CPI", fetch_canada_cpi, save_canada_cpi),
    ],
    "ch": [
        ("Швейцария: квартальный Трейд/ВВП (SNB + SECO)", fetch_switzerland_quarterly, save_switzerland_quarterly),
        ("Швейцария: CPI", fetch_switzerland_cpi, save_switzerland_cpi),
        ("Швейцария: безработица", fetch_switzerland_unemployment, save_switzerland_unemployment),
        ("Швейцария: квартальный рост ВВП (SECO)", fetch_switzerland_gdp, save_switzerland_gdp),
    ],
    "cn": [
        ("Китай: безработица", fetch_china_unemployment, save_china_unemployment),
        ("Китай: Core CPI (NBS)", fetch_china_core_cpi, save_china_core_cpi),
        ("Китай: квартальный долг (NIFD)", fetch_all_nifd_debt, save_china_debt),
        ("Китай: годовой долг (FRED/IMF)", fetch_china_debt_fred, save_china_debt_fred),
        ("Китай: квартальный бюджет и трейд (Минфин + SAFE)", fetch_china_fiscal, save_china_fiscal),
        ("Китай: квартальный рост ВВП (Tonghuashun)", fetch_china_gdp, save_china_gdp),
        ("Китай: CPI", fetch_china_cpi, save_china_cpi),
    ],
    "in": [
        ("Индия: безработица", fetch_india_unemployment, save_india_unemployment),
        ("Индия: CPI", fetch_india_cpi, save_india_cpi),
        ("Индия: квартальный рост ВВП (MoSPI)", fetch_india_gdp, save_india_gdp),
    ],
    "tr": [
        ("Турция: CPI", fetch_turkey_cpi, save_turkey_cpi),
    ],
    "ru": [
        (
            "Россия: CPI YoY + MoM + Core (ЦБ РФ)",
            fetch_russia_cpi,
            save_russia_cpi,
        ),
        (
            "Россия: долг, бюджет, текущий счёт (Казначейство + Росстат + ЦБ)",
            fetch_russia_quarterly,
            save_russia_quarterly,
        ),
        (
            "Россия: процентные ставки по кредитам и депозитам (ЦБ РФ)",
            fetch_russia_rates,
            save_russia_rates,
        ),
        (
            "Россия: задолженность физлиц, компаний и МСП (ЦБ РФ)",
            fetch_russia_credit,
            save_russia_credit,
        ),
        (
            "Россия: ипотечные показатели (ЦБ РФ)",
            fetch_russia_mortgage,
            save_russia_mortgage,
        ),
        (
            "Россия: денежная масса M0, M1, M2, M2X (ЦБ РФ)",
            fetch_russia_money,
            save_russia_money,
        ),
        (
            "Россия: экспорт, импорт и торговое сальдо (ЦБ РФ)",
            fetch_russia_trade,
            save_russia_trade,
        ),
        (
            "Россия: оперативные оценки экспорта/импорта (ЦБ РФ)",
            fetch_russia_trade_estimates,
            save_russia_trade_estimates,
        ),
        (
            "Россия: частные инвесторы (официальные релизы Московской биржи)",
            fetch_russia_investors,
            save_russia_investors,
        ),
        (
            "Россия: статистика брокеров, ИИС и ПИФ (ЦБ РФ)",
            fetch_russia_cbr_reference,
            save_russia_cbr_reference,
        ),
        (
            "Россия: объем сделок RUONIA (ЦБ РФ, дневной ряд)",
            fetch_russia_ruonia,
            save_russia_ruonia,
        ),
    ],
    "fred": [
        ("FRED: макро-ряды", fetch_all_macro, save_fred),
        ("FRED: квартальный GDP", fetch_fred_gdp, save_fred_gdp),
        ("FRED: безработица (не-ЕС)", fetch_fred_unemployment, save_fred_unemployment),
        ("FRED: CPI (месячная)", fetch_fred_cpi, save_fred_cpi),
    ],
    "imf": [
        ("IMF: страновые метрики", fetch_all_imf, save_imf),
    ],
    "eurostat": [
        ("Eurostat: HICP (инфляция ЕС)", fetch_eurostat_hicp, save_eurostat),
        ("Eurostat: безработица", fetch_eurostat_unemployment, save_eurostat_unemployment),
        ("Eurostat: квартальные макро-метрики", fetch_eurostat_quarterly, save_eurostat_quarterly),
        ("Eurostat: годовые General Gov", fetch_eurostat_annual, save_eurostat_annual),
    ],
    "ppi_national": [
        ("США: история PPI YoY NSA + MoM SA (BLS API)", fetch_us_history, save_eurostat_extra),
        ("Япония: история CGPI YoY NSA (BoJ)", _fetch_japan_ppi_yoy, save_eurostat_extra),
        ("Япония: история CGPI MoM NSA (BoJ PDF)", _fetch_japan_ppi_mom, _already_saved),
        ("Канада: история IPPI YoY + MoM NSA (StatCan)", fetch_canada_ppi, save_eurostat_extra),
        ("Великобритания: история Output PPI YoY + MoM NSA (ONS)", fetch_uk_ppi, save_eurostat_extra),
        ("Китай: история PPI YoY + MoM NSA (NBS)", fetch_china_ppi, save_eurostat_extra),
    ],
    "ppi_turkey": [
        (
            "Турция: история D-PPI YoY + MoM NSA (TCMB / TURKSTAT)",
            fetch_turkey_ppi,
            save_eurostat_extra,
        ),
    ],
    "eurostat_extra": [
        ("Eurostat: PPI YoY (domestic, NSA)", partial(fetch_eurostat_extra, "ppi_yoy"), save_eurostat_extra),
        ("Eurostat: PPI MoM (domestic, NSA)", partial(fetch_eurostat_extra, "ppi_mom"), save_eurostat_extra),
        ("Eurostat: реальный ВВП QoQ (SCA)", partial(fetch_eurostat_extra, "gdp_qoq"), save_eurostat_extra),
    ],
    "extra": [
        ("ForexFactory: календарь", fetch_calendar, save_forexfactory),
        ("RSS: новости", fetch_news, save_rss),
    ],
}


RU_REFERENCE_GROUP = "ru_reference"
RU_RUONIA_GROUP = "ru_ruonia"

SELECTIVE_RU_GROUPS = {
    RU_REFERENCE_GROUP,
    RU_RUONIA_GROUP,
}

GROUPS[RU_REFERENCE_GROUP] = [
    step
    for step in GROUPS["ru"]
    if step[1] is fetch_russia_cbr_reference
]

GROUPS[RU_RUONIA_GROUP] = [
    step
    for step in GROUPS["ru"]
    if step[1] is fetch_russia_ruonia
]

# Narrow RU groups must not duplicate RU jobs
# in the default full update.
DEFAULT_GROUPS = tuple(
    group
    for group in GROUPS
    if group not in SELECTIVE_RU_GROUPS
)


def print_help():
    print(__doc__)
    print("Доступные группы:")

    for name, steps in GROUPS.items():
        print(
            f"  {name:16s} — {len(steps)} шаг(ов)"
        )


def print_list():
    print(
        "Доступные группы для выборочного запуска:"
    )

    for group, steps in GROUPS.items():
        print(f"\n{group}:")

        for title, _, _ in steps:
            print(f"  - {title}")


def run(
    groups: list[str] | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """Exit codes: 0 success, 1 partial, 2 errors."""

    selected = (
        list(DEFAULT_GROUPS)
        if groups is None
        else list(groups)
    )

    unknown = [
        group
        for group in selected
        if group not in GROUPS
    ]

    if unknown or not selected:
        print(
            f"[ERROR] Неверные группы: "
            f"{unknown or selected}"
        )
        print_help()
        return 2

    print("=" * 50)
    print(
        "ПЛАН ОБНОВЛЕНИЯ"
        if dry_run
        else "ОБНОВЛЕНИЕ ДАННЫХ"
    )
    print("=" * 50)

    plan = []
    seen = set()

    for group in selected:
        for title, fetch, save in GROUPS[group]:
            key = (fetch, save)

            if key in seen:
                continue

            seen.add(key)

            plan.append(
                (group, title, fetch, save)
            )

    if dry_run:
        for i, (
            group, title, _, _
        ) in enumerate(plan, 1):
            print(
                f"{i:02d}. [{group}] {title}"
            )

        print(
            f"[DRY RUN] Шагов: {len(plan)}; "
            "запросов и записей не было"
        )
        return 0

    try:
        ensure_dirs()

    except Exception as exc:
        print(
            "[ERROR] Не удалось подготовить папки: "
            f"{_safe_error(exc)}"
        )
        return 2

    stats = {
        "ok": 0,
        "empty": 0,
        "partial": 0,
        "error": 0,
    }

    problems = []

    for group, title, fetch, save in plan:
        print(
            f"\n[GROUP] {group}"
        )

        status = _step(
            title,
            fetch,
            save,
        )

        stats[status] += 1

        if status != "ok":
            problems.append(
                (status, title)
            )

    # Preserve weekly snapshots even when
    # an unrelated external source fails.
    if groups is None and stats["ok"] > 0:
        print(
            "\n--- Снимок сводной таблицы ---"
        )

        try:
            save_weekly_snapshot()
            print(
                "[OK] Снимок сохранён"
            )

        except Exception as exc:
            problems.append(
                ("error", "snapshot")
            )
            stats["error"] += 1
            print(
                f"[ERROR] snapshot: {_safe_error(exc)}"
            )

    # Cleanup only on a fully successful
    # unrestricted run.
    if groups is None and not problems:
        try:
            cleanup_all()

        except Exception as exc:
            problems.append(
                ("error", "cleanup")
            )
            stats["error"] += 1
            print(
                f"[ERROR] cleanup: {_safe_error(exc)}"
            )

    print(
        "\n" + "=" * 50
    )

    print(
        f"[SUMMARY] Успешно: {stats['ok']}; "
        f"пустых: {stats['empty']}; "
        f"частичных: {stats['partial']}; "
        f"ошибок: {stats['error']}"
    )

    for status, title in problems:
        print(
            f"[{status.upper()}] {title}"
        )

    if stats["error"]:
        print(
            "[FINISH] ОБНОВЛЕНИЕ "
            "С ОШИБКАМИ (код 2)"
        )
        return 2

    if (
        stats["empty"]
        or stats["partial"]
    ):
        print(
            "[FINISH] НЕПОЛНОЕ "
            "ОБНОВЛЕНИЕ (код 1)"
        )
        return 1

    print(
        "[FINISH] ГОТОВО (код 0)"
    )
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] in (
        "--help",
        "-h",
    ):
        print_help()

    elif args and args[0] == "--list":
        print_list()

    else:
        dry_run = (
            "--dry-run" in args
        )

        groups = [
            arg for arg in args
            if arg != "--dry-run"
        ]

        sys.exit(
            run(
                groups=groups or None,
                dry_run=dry_run,
            )
        )
