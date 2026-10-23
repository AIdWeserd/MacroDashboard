import io
import time
import asyncio
import requests
import pandas as pd
from config import FRED_API_KEY

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
START_DATE = pd.Timestamp("2024-01-01")

# === FRED-серии: (страна, series_id) ===
FRED_SERIES = {
    "US": "DFEDTARU",  # Fed Funds Target Range, Upper
    "EU": "ECBDFR",  # ECB Deposit Facility Rate
    "KR": "IR3TIB01KRM156N",  # Korea 3-month interbank rate
    "TR": "INTDSRTRM193N",  # CBRT Policy Rate
    "JP": "INTDSRJPM193N",  # BoJ Discount Rate (fallback)
}


def _get_fred_series(series_id: str) -> pd.DataFrame:
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY не задан в .env")
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2024-01-01",
    }
    r = requests.get(FRED_BASE, params=params, timeout=60)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        return pd.DataFrame()
    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().sort_values("date").reset_index(drop=True)


def _monthly_last_known(df: pd.DataFrame) -> pd.DataFrame:
    """Для каждого месяца — последнее известное значение. Дата = конец месяца."""
    if df.empty:
        return df
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month").last().reset_index()
    monthly["date"] = monthly["month"].dt.to_timestamp("M")
    return monthly[["date", "value"]].sort_values("date").reset_index(drop=True)


# ============================================================
# US, EU, KR, TR, JP (fallback) — FRED
# ============================================================
def _source_error(label: str, exc: Exception) -> None:
    """Не выводить URL, токены и ключи из исключений HTTP."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    suffix = f" HTTP {status}" if status is not None else ""
    print(f"[ERR] {label}: {type(exc).__name__}{suffix}")


def fetch_policy_rates_fred() -> pd.DataFrame:
    """Данные FRED + метаданные о неудавшихся сериях.

    JP/FRED — резерв: ошибка этой серии не влияет на статус, если
    официальный BoJ успешно вернул JP.
    """
    rows = []
    failures = []
    for country, series_id in FRED_SERIES.items():
        label = f"FRED {country}/{series_id}"
        try:
            df = _get_fred_series(series_id)
            if df is None or df.empty:
                print(f"[WARN] {label}: пусто")
                failures.append(country)
                continue
            df = _monthly_last_known(df)
            df["country"] = country
            rows.append(df)
            print(f"[OK] {label}: {len(df)} месяцев")
        except Exception as exc:
            _source_error(label, exc)
            failures.append(country)
    if not rows:
        empty = pd.DataFrame(columns=["date", "country", "rate"])
        empty.attrs["fred_failures"] = tuple(failures)
        return empty
    result = pd.concat(rows, ignore_index=True)
    result = result[result["date"] >= START_DATE].reset_index(drop=True)
    result = result[["date", "country", "value"]].rename(columns={"value": "rate"})
    result.attrs["fred_failures"] = tuple(failures)
    return result


# ============================================================
# GB — Bank of England
# ============================================================
def fetch_policy_rate_gb() -> pd.DataFrame:
    url = ("https://www.bankofengland.co.uk/boeapps/database/"
           "_iadb-fromshowcolumns.asp"
           "?csv.x=yes"
           "&Datefrom=01/Jan/2024&Dateto=now"
           "&SeriesCodes=IUDBEDR"
           "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    }
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    if "DATE" not in df.columns or "IUDBEDR" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["DATE"], format="%d %b %Y", errors="coerce")
    df["value"] = pd.to_numeric(df["IUDBEDR"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    df = _monthly_last_known(df[["date", "value"]])
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "GB"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# JP — Bank of Japan API
# ============================================================
def fetch_policy_rate_jp() -> pd.DataFrame:
    url = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
    params = {
        "format": "json",
        "lang": "en",
        "db": "IR01",
        "code": "MADR1M",
        "startDate": "202401",
        "endDate": pd.Timestamp.now().strftime("%Y%m"),
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    resultset = data.get("RESULTSET", [])
    if not resultset:
        return pd.DataFrame()
    series = resultset[0].get("VALUES", {})
    dates = series.get("SURVEY_DATES", [])
    values = series.get("VALUES", [])
    rows = []
    for d, v in zip(dates, values):
        if v is None:
            continue
        try:
            year = int(str(d)[:4])
            month = int(str(d)[4:6])
            rows.append({"date": pd.Timestamp(year=year, month=month, day=1), "value": float(v)})
        except (ValueError, TypeError):
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["date"] = df["date"] + pd.offsets.MonthEnd(0)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "JP"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# CA — Bank of Canada Valet API
# ============================================================
def fetch_policy_rate_ca() -> pd.DataFrame:
    url = "https://www.bankofcanada.ca/valet/observations/V39079/json"
    params = {"start_date": "2024-01-01"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    obs = data.get("observations", [])
    if not obs:
        return pd.DataFrame()
    rows = []
    for o in obs:
        d = o.get("d")
        v = o.get("V39079", {}).get("v")
        if not d or v is None:
            continue
        try:
            rows.append({"date": pd.Timestamp(d), "value": float(v)})
        except (ValueError, TypeError):
            continue
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = _monthly_last_known(df)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "CA"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# CH — SNB Data Portal (JSON)
# ============================================================
def fetch_policy_rate_ch() -> pd.DataFrame:
    url = "https://data.snb.ch/api/cube/snboffzisa/data/json/en"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()

    timeseries = data.get("timeseries", [])
    if not timeseries:
        return pd.DataFrame()

    values = timeseries[0].get("values", [])
    rows = []
    for v in values:
        d = v.get("date")
        val = v.get("value")
        if not d or val is None:
            continue
        try:
            ts = pd.Timestamp(d + "-01") + pd.offsets.MonthEnd(0)
            rows.append({"date": ts, "value": float(val)})
        except (ValueError, TypeError):
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "CH"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# AU — RBA Cash Rate Target через rba-mcp
# ============================================================
def _parse_rba_cash_rate(result) -> pd.DataFrame:
    """Нормализует старый и новый формат ответа rba-mcp (F1.1).

    Запрос ограничен единственной серией cash_rate_target; не выбираем
    другие денежные ставки из таблицы F1.1.
    """
    import json

    payload = getattr(result, "structured_content", None)
    records = payload.get("records") if isinstance(payload, dict) else None

    if not isinstance(records, list):
        records = None
        for part in getattr(result, "content", ()) or ():
            content_text = getattr(part, "text", None)
            if not isinstance(content_text, str):
                continue
            try:
                decoded = json.loads(content_text)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict) and isinstance(decoded.get("records"), list):
                records = decoded["records"]
                break

    if not records:
        return pd.DataFrame(columns=["date", "country", "rate"])

    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        dimensions = record.get("dimensions") or {}
        if not isinstance(dimensions, dict):
            dimensions = {}

        series_label = record.get("series") or dimensions.get("series") or ""
        normalized = str(series_label).lower().replace("_", " ").strip()
        if normalized and not (
            "cash rate target" in normalized
            or normalized in {"firmmcrt", "firmmcrtd"}
        ):
            continue

        period = record.get("period") or record.get("date")
        value = record.get("value")
        if period is None or value is None:
            continue
        try:
            date = pd.to_datetime(period, errors="raise")
            rate = float(value)
        except (ValueError, TypeError, OverflowError):
            continue
        if pd.isna(date) or pd.isna(rate):
            continue
        rows.append({"date": date, "value": rate})

    if not rows:
        return pd.DataFrame(columns=["date", "country", "rate"])

    frame = pd.DataFrame(rows).sort_values("date")
    frame = _monthly_last_known(frame)
    current_month = pd.Timestamp.now().to_period("M")
    frame = frame[
        (frame["date"] >= START_DATE)
        & (frame["date"].dt.to_period("M") <= current_month)
    ].copy()
    frame["country"] = "AU"
    return frame[["date", "country", "value"]].rename(
        columns={"value": "rate"}
    ).reset_index(drop=True)


def fetch_policy_rate_au() -> pd.DataFrame:
    """Официальная RBA Cash Rate Target из rba-mcp, F1.1.

    Две попытки чтения защищают от временного сбоя локального MCP-процесса.
    При окончательной ошибке возвращает пустую таблицу; общий загрузчик
    фиксирует AU в source_issues, а scheduler завершится частично.
    """

    async def _fetch():
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        transport = StdioTransport(command="rba-mcp", args=[])
        async with Client(transport) as client:
            return await client.call_tool(
                "get_data",
                {
                    "table_id": "F1.1",
                    "series": "cash_rate_target",
                    "start_period": START_DATE.strftime("%Y-%m"),
                    "end_period": pd.Timestamp.now().strftime("%Y-%m"),
                    "format": "records",
                },
            )

    last_error = None
    for attempt in range(2):
        try:
            response = asyncio.run(_fetch())
            if getattr(response, "is_error", False):
                raise RuntimeError("Инструмент rba-mcp вернул is_error")
            parsed = _parse_rba_cash_rate(response)
            if not parsed.empty:
                return parsed
            last_error = ValueError("Нет валидных наблюдений Cash Rate Target")
        except Exception as exc:
            last_error = exc
        if attempt == 0:
            time.sleep(0.5)

    if last_error is not None:
        _source_error("AU/rba-mcp", last_error)
    return pd.DataFrame(columns=["date", "country", "rate"])


# ============================================================
# BR — Banco Central do Brasil (BCB SGS 432 — Selic)
# ============================================================
def fetch_policy_rate_br() -> pd.DataFrame:
    """Brazil Selic Target Rate через BCB SGS 432."""
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados"
    params = {
        "formato": "json",
        "dataInicial": "01/01/2024",
        "dataFinal": pd.Timestamp.now().strftime("%d/%m/%Y"),
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()

    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        try:
            d = pd.to_datetime(item["data"], format="%d/%m/%Y")
            v = float(item["valor"])
            rows.append({"date": d, "value": v})
        except (ValueError, TypeError, KeyError):
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = _monthly_last_known(df)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "BR"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# CN — Loan Prime Rate (LPR) через chinamoney.com.cn
# ============================================================
def fetch_policy_rate_cn() -> pd.DataFrame:
    """Китай: 1-year Loan Prime Rate (LPR) через chinamoney.com.cn."""
    url = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis"
    params = {"lang": "EN"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.chinamoney.com.cn/chinese/bkccpr/",
    }
    r = requests.get(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()

    records = data.get("records", [])
    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:
        try:
            d = pd.to_datetime(rec["showDateCN"], errors="coerce")
            v = float(rec["1Y"])
            if pd.isna(d):
                continue
            rows.append({"date": d, "value": v})
        except (ValueError, TypeError, KeyError):
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = _monthly_last_known(df)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "CN"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# IN — India (FRED, OECD на основе данных RBI)
# ============================================================
def fetch_policy_rate_in() -> pd.DataFrame:
    """
    India: 3-Month Interbank Rate через FRED (OECD на основе данных RBI).
    Серия INDIR3TIB01STM — месячная, с 2024 года.
    Задержка ~2 месяца (RBI → OECD → FRED).
    """
    df = _get_fred_series("INDIR3TIB01STM")
    if df.empty:
        return pd.DataFrame()
    df = _monthly_last_known(df)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "IN"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# RU — Банк России, ключевая ставка
# ============================================================
def fetch_policy_rate_ru() -> pd.DataFrame:
    """Ключевая ставка Банка России, месячные значения с 2024 года."""
    url = "https://www.cbr.ru/hd_base/KeyRate/"
    params = {
        "UniDbQuery.Posted": "True",
        "UniDbQuery.From": "01.01.2024",
        "UniDbQuery.To": pd.Timestamp.today().strftime("%d.%m.%Y"),
    }

    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
    )
    response.raise_for_status()

    tables = pd.read_html(
        io.StringIO(response.text),
        decimal=",",
        thousands=" ",
    )
    if not tables:
        return pd.DataFrame()

    df = tables[0].rename(
        columns={"Дата": "date", "Ставка": "value"}
    )

    if not {"date", "value"}.issubset(df.columns):
        raise ValueError("ЦБ РФ: изменился формат таблицы ставки")

    df["date"] = pd.to_datetime(
        df["date"], format="%d.%m.%Y", errors="coerce"
    )
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = (
    df.dropna(subset=["date", "value"])
    .sort_values("date")
    .reset_index(drop=True)
)

    if df.empty:
        return pd.DataFrame()

    if not df["value"].between(0, 100).all():
        raise ValueError("ЦБ РФ: некорректный масштаб ставки")

    df = _monthly_last_known(df[["date", "value"]])
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "RU"

    return df[["date", "country", "value"]].rename(
        columns={"value": "rate"}
    )


# ============================================================
# Объединение: все страны
# ============================================================
def fetch_policy_rates() -> pd.DataFrame:
    """Собирает ставки и сообщает о частичных отказах через df.attrs.

    Атрибут `source_issues` читается scheduler после сохранения успешных
    стран. Нельзя считать весь запуск успешным при пропущенном источнике.
    Метаданные не добавляют новых колонок к данным ставок.
    """
    frames = []
    issues = []
    expected = set(FRED_SERIES) | {"GB", "CA", "CH", "AU", "BR", "CN", "IN", "RU"}

    try:
        fred = fetch_policy_rates_fred()
    except Exception as exc:
        _source_error("FRED (общий запрос)", exc)
        fred = pd.DataFrame(columns=["date", "country", "rate"])
        fred.attrs["fred_failures"] = tuple(FRED_SERIES)

    fred_failures = set(fred.attrs.get("fred_failures", ()))
    if not fred.empty:
        frames.append(fred)

    def add(country: str, label: str, loader):
        try:
            frame = loader()
            if frame is None or frame.empty:
                print(f"[WARN] {label}: пусто")
                issues.append(label)
                return False
            if not {"date", "country", "rate"}.issubset(frame.columns):
                print(f"[WARN] {label}: некорректные колонки")
                issues.append(label)
                return False
            frames.append(frame)
            print(f"[OK] {label}: {len(frame)} месяцев")
            return True
        except Exception as exc:
            _source_error(label, exc)
            issues.append(label)
            return False

    add("GB", "GB/BoE", fetch_policy_rate_gb)
    boj_ok = add("JP", "JP/BoJ", fetch_policy_rate_jp)
    add("CA", "CA/BoC", fetch_policy_rate_ca)
    add("CH", "CH/SNB", fetch_policy_rate_ch)
    add("AU", "AU/rba-mcp", fetch_policy_rate_au)
    add("BR", "BR/BCB SGS 432", fetch_policy_rate_br)
    add("CN", "CN/LPR", fetch_policy_rate_cn)
    add("IN", "IN/FRED", fetch_policy_rate_in)
    add("RU", "RU/CBR", fetch_policy_rate_ru)

    # JP/FRED не обязателен, если источник BoJ вернул данные.
    # Но если BoJ недоступен, помечаем деградацию даже при наличии FRED.
    for country in sorted(fred_failures):
        if country == "JP" and boj_ok:
            continue
        issues.append(f"FRED {country}")

    if not frames:
        result = pd.DataFrame(columns=["date", "country", "rate"])
        result.attrs["source_issues"] = tuple(sorted(set(issues)))
        return result

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["date", "country"], keep="last")
    result = result.sort_values(["country", "date"]).reset_index(drop=True)

    actual = set(result["country"].dropna().astype(str))
    for country in sorted(expected - actual):
        issues.append(f"нет данных {country}")

    result.attrs["source_issues"] = tuple(sorted(set(issues)))
    return result
