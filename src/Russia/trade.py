"""Официальная внешняя торговля РФ (методология ПБ), ЦБ России.

Исторические ряды trade.xls, лист «Ежемесячные», млн USD -> млрд USD.
Оперативная оценка bop_est.xlsx НЕ заменяет пересматриваемые ряды trade.xls.
"""
from io import BytesIO
import re
import pandas as pd
import requests

TRADE_URL = "https://www.cbr.ru/vfs/statistics/credit_statistics/trade/trade.xls"
ESTIMATE_URL = "https://www.cbr.ru/vfs/statistics/credit_statistics/bop/bop_est.xlsx"
START = pd.Timestamp("2020-01-01")
MONTHS = {"янв":1,"фев":2,"мар":3,"апр":4,"май":5,"июн":6,"июл":7,"авг":8,"сен":9,"окт":10,"ноя":11,"дек":12}


def _get(url, signature):
    response = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=120)
    response.raise_for_status()
    if not response.content.startswith(signature):
        raise ValueError(f"[RU TRADE] Некорректный формат: {url}")
    return BytesIO(response.content)


def fetch_russia_trade():
    """Опубликованная помесячная история экспорта, импорта и сальдо, млрд USD."""
    print("[RU TRADE] Загружаем историческую внешнюю торговлю ЦБ РФ...")
    try:
        frame = pd.read_excel(_get(TRADE_URL,b"\xd0\xcf\x11\xe0"), sheet_name="Ежемесячные", header=None, engine="xlrd")
    except ImportError as exc:
        raise ImportError("Для чтения официального trade.xls установи зависимость: pip install xlrd") from exc
    # Структура проверена по официальному trade.xls: год A, месяц B,
    # экспорт C, импорт I, сальдо O; исходные значения в млн USD.
    header = " ".join(str(v).lower() for v in frame.iloc[4].fillna(""))
    if "экспорт товаров" not in header or "импорт товаров" not in header or "сальдо" not in header:
        raise ValueError("[RU TRADE] Структура заголовков XLS изменилась")
    if "млн долларов" not in " ".join(str(x).lower() for x in frame.iloc[3].fillna("")):
        raise ValueError("[RU TRADE] Единицы измерения XLS изменились")
    rows=[]
    for _, r in frame.iloc[7:].iterrows():
        year=pd.to_numeric(r.iloc[0],errors="coerce")
        mon=MONTHS.get(str(r.iloc[1]).strip().lower()[:3])
        if pd.isna(year) or not float(year).is_integer() or mon is None or int(year)<2020:
            continue
        dt=pd.Timestamp(int(year),mon,1)
        if dt<START: continue
        values=[pd.to_numeric(r.iloc[c],errors="coerce") for c in (2,8,14)]
        if any(pd.isna(x) for x in values):
            raise ValueError(f"[RU TRADE] Отсутствуют опубликованные значения: {dt.date()}")
        rows.append({"date":dt,"country":"RU","exports_goods_bln_usd":float(values[0])/1000,
                     "imports_goods_bln_usd":float(values[1])/1000,"balance_goods_bln_usd":float(values[2])/1000})
    result=pd.DataFrame(rows)
    if result.empty or result["date"].duplicated().any():
        raise ValueError("[RU TRADE] Пустой ряд или дубли дат")
    result=result.sort_values("date").reset_index(drop=True)
    print(f"[RU TRADE] {len(result)} месяцев: {result.date.min().date()} — {result.date.max().date()}; млрд USD")
    return result


def fetch_russia_trade_estimates():
    """Только месяцы с явной пометкой «оценка» в оперативном файле ЦБ."""
    print("[RU TRADE EST] Проверяем оперативные оценки ЦБ...")
    book=pd.read_excel(_get(ESTIMATE_URL,b"PK"), sheet_name=0, header=None)
    if "млрд долларов" not in " ".join(str(v).lower() for v in book.iloc[2].fillna("")):
        raise ValueError("[RU TRADE EST] Изменились единицы")
    if str(book.iloc[6,0]).strip()!="Товары" or str(book.iloc[7,0]).strip()!="Экспорт" or str(book.iloc[8,0]).strip()!="Импорт":
        raise ValueError("[RU TRADE EST] Изменилась структура строк")
    result=[]
    for col in range(1,book.shape[1]):
        h=str(book.iloc[3,col]).lower().replace("\n"," ")
        if "оценка" not in h or re.search(r"январ[ья]\s*[-–]\s*август", h):continue
        m=re.search(r"(январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])\s*(?:20\d{2}\s*г)?",h)
        y=re.search(r"20\d{2}",h)
        if not m or not y:continue  # исключаем нарастающие итоги за несколько месяцев
        month=MONTHS.get(m.group(1)[:3]); year=int(y.group(0))
        if not month:continue
        exp=pd.to_numeric(book.iloc[7,col],errors="coerce")
        imp=pd.to_numeric(book.iloc[8,col],errors="coerce")
        bal=pd.to_numeric(book.iloc[6,col],errors="coerce")
        if pd.isna(exp) or pd.isna(imp) or pd.isna(bal): continue
        result.append({"date":pd.Timestamp(year,month,1),"country":"RU",
            "exports_goods_bln_usd":float(exp),"imports_goods_bln_usd":float(imp),
            "balance_goods_bln_usd":float(bal),"status":"предварительная оценка ЦБ"})
    output=pd.DataFrame(result)
    if output.empty:raise ValueError("[RU TRADE EST] Месячные оценки не распознаны; структура могла измениться")
    if output.date.duplicated().any():raise ValueError("[RU TRADE EST] Повтор дат")
    output=output.sort_values("date").reset_index(drop=True)
    print(f"[RU TRADE EST] {len(output)} месячных оценок (не заменяют исторический ряд)")
    return output
