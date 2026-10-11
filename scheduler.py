"""
Планировщик обновления данных.

Использование:
    python scheduler.py            — обновить всё
    python scheduler.py china      — обновить только Китай
    python scheduler.py china us   — обновить Китай и США
    python scheduler.py --list     — показать список стран
    python scheduler.py --help     — эта справка
"""

import sys
import traceback

# === Импорты фетчеров ===
from src.fetch_fred import fetch_all_macro
from src.fetch_fred_unemployment import fetch_fred_unemployment
from src.fetch_fred_gdp import fetch_fred_gdp
from src.fetch_rss import fetch_news
from src.fetch_forexfactory import fetch_calendar
from src.fetch_imf import fetch_all_imf
from src.fetch_eurostat import fetch_eurostat_hicp
from src.fetch_eurostat_unemployment import fetch_eurostat_unemployment
from src.fetch_eurostat_quarterly import fetch_eurostat_quarterly
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
from src.snapshot import save_weekly_snapshot

# === Импорты storage ===
from src.storage import (
    save_fred, save_rss, save_forexfactory, save_imf,
    save_eurostat, save_eurostat_unemployment, save_eurostat_quarterly,
    save_fred_unemployment, save_fred_gdp,
    save_singapore_unemployment, save_singapore_cpi, save_singapore_gdp,
    save_singapore_quarterly,
    save_brazil_unemployment, save_brazil_cpi, save_brazil_gdp,
    save_brazil_quarterly,
    save_uk_quarterly,
    save_japan_quarterly,
    save_korea_quarterly,
    save_australia_quarterly,
    save_switzerland_quarterly,
    save_canada_quarterly,
    save_policy_rates,
    save_china_unemployment, save_india_unemployment, save_india_gdp,
    save_fred_cpi, save_china_cpi, save_india_cpi, save_uk_cpi, save_canada_cpi, save_australia_cpi,
    save_turkey_cpi, save_switzerland_cpi, save_switzerland_unemployment, save_japan_cpi, save_korea_cpi,
    save_china_debt, save_china_fiscal, save_china_gdp, save_switzerland_gdp,
    save_us_quarterly,
)


# ============================================================
# Хелпер: обёртка для одного шага
# ============================================================
def _step(name: str, fetch_fn, save_fn):
    """Выполняет один шаг обновления: fetch -> save с обработкой ошибок."""
    print(f"\n--- {name} ---")
    try:
        df = fetch_fn()
        if df is not None and not df.empty:
            save_fn(df)
        else:
            print(f"[WARN] {name}: нет данных")
    except Exception as e:
        print(f"[ERROR] {name}: {e}")
        traceback.print_exc()


# ============================================================
# Группы по странам / источникам
# ============================================================
GROUPS = {
    "rates": [
        ("Ставки ЦБ (все страны)", fetch_policy_rates, save_policy_rates),
    ],
    "us": [
        ("США: квартальные метрики (Treasury + BEA)", fetch_us_quarterly, save_us_quarterly),
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
        ("Китай: квартальный долг (NIFD)", fetch_all_nifd_debt, save_china_debt),
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
    ],
    "extra": [
        ("ForexFactory: календарь", fetch_calendar, save_forexfactory),
        ("RSS: новости", fetch_news, save_rss),
    ],
}


# ============================================================
# Вывод справки
# ============================================================
def print_help():
    print(__doc__)
    print("Доступные группы:")
    for key in GROUPS:
        count = len(GROUPS[key])
        print(f"  {key:10s} — {count} шаг(ов)")


def print_list():
    print("Доступные группы для выборочного запуска:")
    print()
    for key, steps in GROUPS.items():
        print(f"  {key}:")
        for name, _, _ in steps:
            print(f"    - {name}")
        print()


# ============================================================
# Главный запуск
# ============================================================
def run(groups: list[str] | None = None):
    print("=" * 50)
    print("ОБНОВЛЕНИЕ ДАННЫХ")
    print("=" * 50)

    if groups is None:
        selected = list(GROUPS.keys())
    else:
        selected = groups

    unknown = [g for g in selected if g not in GROUPS]
    if unknown:
        print(f"[ERROR] Неизвестные группы: {unknown}")
        print_help()
        sys.exit(1)

    for group in selected:
        print(f"\n{'=' * 50}")
        print(f"ГРУППА: {group}")
        print("=" * 50)
        for name, fetch_fn, save_fn in GROUPS[group]:
            _step(name, fetch_fn, save_fn)

    if groups is None:
        print("\n--- Снимок сводной таблицы (для подсветки) ---")
        try:
            save_weekly_snapshot()
        except Exception as e:
            print(f"[ERROR] snapshot: {e}")

    print("\n" + "=" * 50)
    print("ГОТОВО")
    print("=" * 50)


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        run()
    elif args[0] in ("--help", "-h"):
        print_help()
    elif args[0] == "--list":
        print_list()
    else:
        run(groups=args)
