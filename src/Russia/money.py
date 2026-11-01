"""Официальные месячные денежные агрегаты ЦБ РФ (уровни, млрд рублей)."""
from io import BytesIO
from datetime import datetime, date

import pandas as pd
import requests
from openpyxl import load_workbook

SOURCE = "https://www.cbr.ru/vfs/statistics/credit_statistics/monetary_agg.xlsx"
SHEET = "Денежные агрегаты"
LABELS = {
    "Денежный агрегат М0": "m0",
    "Денежный агрегат М1": "m1",
    "Денежный агрегат М2": "m2",
    "Денежный агрегат M2X (широкая денежная масса)": "m2x",
}


def parse_russia_money_xlsx(content: bytes) -> pd.DataFrame:
    """Извлечь только опубликованные уровни четырёх агрегатов, без расчётов."""
    wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        if SHEET not in wb.sheetnames:
            raise ValueError(f"[RU MONEY] Нет листа {SHEET!r}")
        ws = wb[SHEET]
        rows = ws.iter_rows(values_only=True)
        header = next(rows)
        if "млрд руб" not in str(header[0]).lower():
            raise ValueError("[RU MONEY] Неверные единицы измерения в книге")
        dates = [pd.Timestamp(x) if isinstance(x, (datetime, date)) else pd.NaT for x in header[1:]]
        found = {}
        for cells in rows:
            name = " ".join(str(cells[0]).split()) if cells[0] is not None else ""
            if name not in LABELS:
                continue
            key = LABELS[name]
            if key in found:
                raise ValueError(f"[RU MONEY] Дублированный агрегат {key}")
            found[key] = cells[1:]
        if set(found) != set(LABELS.values()):
            raise ValueError(f"[RU MONEY] Не найдены агрегаты: {sorted(set(LABELS.values()) - set(found))}")
        records = []
        for i, dt in enumerate(dates):
            if pd.isna(dt) or dt < pd.Timestamp("2020-01-01"):
                continue
            if dt.day != 1:
                raise ValueError(f"[RU MONEY] Дата не на первое число месяца: {dt}")
            item = {"date": dt, "country": "RU"}
            for key, values in found.items():
                val = values[i] if i < len(values) else None
                item[key] = pd.to_numeric(val, errors="coerce")
            if all(pd.isna(item[k]) for k in found):
                continue
            records.append(item)
        df = pd.DataFrame(records, columns=["date", "country", "m0", "m1", "m2", "m2x"])
        if df.empty or df["date"].duplicated().any() or df["date"].min() != pd.Timestamp("2020-01-01"):
            raise ValueError("[RU MONEY] Пустая, неполная или неоднозначная история")
        if df[["m0", "m1", "m2", "m2x"]].isna().any().any():
            raise ValueError("[RU MONEY] Пропущены опубликованные месячные уровни")
        if (df[["m0", "m1", "m2", "m2x"]] <= 0).any().any():
            raise ValueError("[RU MONEY] Недопустимое значение агрегата")
        df = df.sort_values("date").reset_index(drop=True)
        print(f"[RU MONEY] {len(df)} месяцев, {df.date.min():%Y-%m-%d} — {df.date.max():%Y-%m-%d}; млрд руб.")
        for key in ("m0", "m1", "m2", "m2x"):
            print(f"[RU MONEY] {key.upper()}: {df[key].iloc[-1]:,.1f} млрд руб.")
        return df
    finally:
        wb.close()


def fetch_russia_money() -> pd.DataFrame:
    """Скачать официальную обновляемую таблицу ЦБ РФ."""
    print("[RU MONEY] Загружаем денежные агрегаты ЦБ РФ...")
    response = requests.get(SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=120, verify=True)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError("[RU MONEY] Источник вернул не XLSX")
    return parse_russia_money_xlsx(response.content)
