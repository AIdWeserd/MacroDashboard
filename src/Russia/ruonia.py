"""Официальный объем сделок RUONIA (дневной ряд Банка России).

Источник: https://www.cbr.ru/hd_base/ruonia/dynamics/
Без агрегаций, интерполяций и собственных макрорасчетов.
"""
from datetime import date
from io import StringIO
import re

import pandas as pd
import requests

URL = "https://www.cbr.ru/hd_base/ruonia/dynamics/"
COLUMNS = ["date", "country", "ruonia_volume_bln_rub", "source_url"]


def _number(value):
    value = str(value).replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    value = value.replace(",", ".").replace("−", "-")
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or not 0 < float(number) < 100000:
        raise ValueError(f"[RU RUONIA] Некорректный опубликованный объем: {value!r}")
    return float(number)


def _is_unpublished(value):
    """ЦБ обозначает отсутствующий объём прочерком, а не числом ноль."""
    if pd.isna(value):
        return True
    normalized = str(value).replace("\xa0", "").replace("\u202f", "").strip()
    return normalized in {"", "—", "–", "-", "−"}


def _parse_html(html):
    tables = pd.read_html(StringIO(html), decimal=",", thousands=" ")
    selected = []
    for table in tables:
        table.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in table.columns]
        joined = " ".join(table.columns).lower().replace("ё", "е")
        if "объем сделок ruonia" in joined and "дата ставки" in joined:
            selected.append(table)
    if len(selected) != 1:
        raise ValueError("[RU RUONIA] Невозможно однозначно определить официальную таблицу")
    table = selected[0]
    date_col = next(c for c in table if "Дата ставки" in c)
    vol_col = next(c for c in table if "Объем сделок RUONIA" in c or "Объём сделок RUONIA" in c)
    records = []
    unpublished = 0
    for _, row in table.iterrows():
        observed = pd.to_datetime(row[date_col], format="%d.%m.%Y", errors="coerce")
        if pd.isna(observed):
            continue
        volume = row[vol_col]
        if _is_unpublished(volume):
            unpublished += 1
            continue
        records.append({
            "date": observed.strftime("%Y-%m-%d"),
            "country": "RU",
            "ruonia_volume_bln_rub": _number(volume),
            "source_url": URL,
        })
    frame = pd.DataFrame(records, columns=COLUMNS)
    if frame.empty or frame.duplicated(["date"]).any():
        raise ValueError("[RU RUONIA] Нет опубликованных числовых строк или повторяются даты")
    frame.attrs["unpublished_count"] = unpublished
    return frame


def fetch_russia_ruonia():
    """История с 2020 года, по годовым окнам. При сбое не удаляет старые дни."""
    from src.storage import load_russia_ruonia

    previous = load_russia_ruonia()
    chunks = []
    for year in range(2020, date.today().year + 1):
        beginning = date(year, 1, 1)
        ending = min(date(year, 12, 31), date.today())
        if beginning > ending:
            continue
        try:
            response = requests.get(
                URL,
                params={
                    "UniDbQuery.From": beginning.strftime("%d.%m.%Y"),
                    "UniDbQuery.To": ending.strftime("%d.%m.%Y"),
                    "UniDbQuery.Posted": "True",
                },
                headers={"User-Agent": "Mozilla/5.0"}, timeout=(10, 60),
            )
            response.raise_for_status()
            frame = _parse_html(response.text)
            # Не принимаем таблицу с датами вне запрошенного периода.
            dates = pd.to_datetime(frame["date"])
            if dates.min().date() < beginning or dates.max().date() > ending:
                raise ValueError("Официальный сайт вернул даты вне запрошенного интервала")
            chunks.append(frame)
            unpublished = frame.attrs.get("unpublished_count", 0)
            print(f"[RU RUONIA] {year}: {len(frame)} опубликованных дней"
                  + (f"; пропущено прочерков: {unpublished}" if unpublished else ""))
        except (requests.RequestException, ValueError, ImportError) as exc:
            print(f"[RU RUONIA] WARNING {year}: {exc}")

    if not previous.empty:
        if not set(COLUMNS).issubset(previous.columns):
            raise ValueError("[RU RUONIA] Старые данные имеют несовместимую структуру")
        previous = previous[COLUMNS].copy()
        previous["date"] = pd.to_datetime(previous["date"]).dt.strftime("%Y-%m-%d")
        chunks.insert(0, previous)

    if not chunks:
        raise RuntimeError("[RU RUONIA] Нет ни официального ответа, ни предыдущих наблюдений")
    merged = pd.concat(chunks, ignore_index=True)
    merged = merged.drop_duplicates("date", keep="last").sort_values("date")
    if (merged["country"] != "RU").any():
        raise ValueError("[RU RUONIA] Неожиданный код страны")
    print(f"[RU RUONIA] Готово: {len(merged)} дней, последний {merged.iloc[-1]['date']}")
    return merged.reset_index(drop=True)
