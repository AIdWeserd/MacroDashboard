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
    "US": "DFEDTARU",           # Fed Funds Target Range, Upper
    "EU": "ECBDFR",              # ECB Deposit Facility Rate
    "KR": "IR3TIB01KRM156N",     # Korea 3-month interbank rate
    "TR": "INTDSRTRM193N",       # CBRT Policy Rate
    "JP": "INTDSRJPM193N",       # BoJ Discount Rate (fallback)
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
def fetch_policy_rates_fred() -> pd.DataFrame:
    rows = []
    for country, series_id in FRED_SERIES.items():
        try:
            df = _get_fred_series(series_id)
            if df.empty:
                print(f"[WARN] FRED {country}/{series_id}: пусто")
                continue
            df = _monthly_last_known(df)
            df["country"] = country
            rows.append(df)
            print(f"[OK] FRED {country}/{series_id}: {len(df)} месяцев")
        except Exception as e:
            print(f"[ERR] FRED {country}/{series_id}: {e}")
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    result = result[result["date"] >= START_DATE].reset_index(drop=True)
    return result[["date", "country", "value"]].rename(columns={"value": "rate"})


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
        "endDate": "202612",
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
# AU — через rba-mcp (локальный MCP-сервер)
# ============================================================
def fetch_policy_rate_au() -> pd.DataFrame:
    """RBA Cash Rate Target через rba-mcp (F1.1, monthly)."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    async def _fetch():
        transport = StdioTransport(command="rba-mcp", args=[])
        client = Client(transport)
        async with client:
            result = await client.call_tool(
                "get_data",
                {"table_id": "F1.1", "start_date": "2024-01-01",
                 "end_date": "2030-12-31"},
            )
            return result

    try:
        result = asyncio.run(_fetch())
    except Exception as e:
        print(f"[ERR] AU/rba-mcp: {e}")
        return pd.DataFrame()

    sc = getattr(result, "structured_content", None) or {}
    records = sc.get("records", [])
    if not records:
        try:
            text = result.content[0].text
            import json
            data = json.loads(text)
            records = data.get("records", [])
        except Exception:
            records = []

    rows = []
    for rec in records:
        d = rec.get("period")
        v = rec.get("value")
        dims = rec.get("dimensions", {})
        series_name = dims.get("series", "")
        if "Cash Rate Target" not in series_name:
            continue
        if not d or v is None:
            continue
        try:
            ts = pd.Timestamp(d)
            rows.append({"date": ts, "value": float(v)})
        except (ValueError, TypeError):
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    df["country"] = "AU"
    return df[["date", "country", "value"]].rename(columns={"value": "rate"})


# ============================================================
# BR — Banco Central do Brasil (BCB SGS 432 — Selic)
# ============================================================
def fetch_policy_rate_br() -> pd.DataFrame:
    """Brazil Selic Target Rate через BCB SGS 432."""
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados"
    params = {
        "formato": "json",
        "dataInicial": "01/01/2024",
        "dataFinal": "31/12/2030",
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
# Объединение: все страны
# ============================================================
def fetch_policy_rates() -> pd.DataFrame:
    """
    Собирает ставки из всех источников.
    Возвращает DataFrame [date, country, rate].
    """
    frames = []

    # FRED: US, EU, KR, TR, JP
    fred = fetch_policy_rates_fred()
    if not fred.empty:
        frames.append(fred)

    # GB
    try:
        gb = fetch_policy_rate_gb()
        if not gb.empty:
            frames.append(gb)
            print(f"[OK] GB/BoE: {len(gb)} месяцев")
    except Exception as e:
        print(f"[ERR] GB/BoE: {e}")

    # JP — BoJ приоритетнее FRED
    try:
        jp = fetch_policy_rate_jp()
        if not jp.empty:
            frames = [f for f in frames if "JP" not in f["country"].values]
            frames.append(jp)
            print(f"[OK] JP/BoJ: {len(jp)} месяцев")
    except Exception as e:
        print(f"[ERR] JP/BoJ: {e}")

    # CA
    try:
        ca = fetch_policy_rate_ca()
        if not ca.empty:
            frames.append(ca)
            print(f"[OK] CA/BoC: {len(ca)} месяцев")
    except Exception as e:
        print(f"[ERR] CA/BoC: {e}")

    # CH
    try:
        ch = fetch_policy_rate_ch()
        if not ch.empty:
            frames.append(ch)
            print(f"[OK] CH/SNB: {len(ch)} месяцев")
    except Exception as e:
        print(f"[ERR] CH/SNB: {e}")

    # AU
    try:
        au = fetch_policy_rate_au()
        if not au.empty:
            frames.append(au)
            print(f"[OK] AU/rba-mcp: {len(au)} месяцев")
    except Exception as e:
        print(f"[ERR] AU/rba-mcp: {e}")

    # BR
    try:
        br = fetch_policy_rate_br()
        if not br.empty:
            frames.append(br)
            print(f"[OK] BR/BCB SGS 432: {len(br)} месяцев")
    except Exception as e:
        print(f"[ERR] BR/BCB SGS 432: {e}")

    # CN
    try:
        cn = fetch_policy_rate_cn()
        if not cn.empty:
            frames.append(cn)
            print(f"[OK] CN/LPR: {len(cn)} месяцев")
    except Exception as e:
        print(f"[ERR] CN/LPR: {e}")

    # IN
    try:
        ind = fetch_policy_rate_in()
        if not ind.empty:
            frames.append(ind)
            print(f"[OK] IN/FRED: {len(ind)} месяцев")
    except Exception as e:
        print(f"[ERR] IN/FRED: {e}")

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["date", "country"], keep="last")
    result = result.sort_values(["country", "date"]).reset_index(drop=True)
    return result
