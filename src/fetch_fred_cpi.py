import requests
import pandas as pd
from config import FRED_API_KEY
import time

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Соответствие: наш код страны -> (headline series, core series | None)
# Headline — обязательно. Core — только там, где в FRED есть живая серия.
# Для GB, CA, TR, CH Core берём из национальных модулей
FRED_CPI_SERIES = {
    "US": {"headline": "CPIAUCSL", "core": "CPILFESL"},
}


def _fetch_series(series_id: str, retries: int = 3, backoff: float = 2.0) -> pd.DataFrame:
    """
    Тянет одну серию из FRED. Делает до `retries` попыток с экспоненциальной
    паузой — FRED регулярно отдаёт 502/503/504 на короткое время.
    """
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(FRED_BASE, params=params, timeout=60)
            # 502/503/504 — ретраим, остальные 4xx/5xx — сразу наружу
            if r.status_code in (502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            break
        except requests.HTTPError as e:
            last_err = e
            status = getattr(e.response, "status_code", None)
            if status not in (502, 503, 504) or attempt == retries:
                raise
            wait = backoff * attempt
            print(f"[RETRY] {series_id}: {status}, попытка {attempt}/{retries}, пауза {wait:.0f}s")
            time.sleep(wait)
    else:
        # сюда не попадём — raise выше
        raise last_err  # type: ignore

    if not obs:
        return pd.DataFrame()

    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["level"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.drop(columns=["value"]).dropna().sort_values("date").reset_index(drop=True)
    return df


def fetch_fred_cpi() -> pd.DataFrame:
    """
    Тянет CPI-индексы (headline + core, где есть) из FRED.
    Считает:
        value — YoY headline, %
        mom   — MoM headline, %
        core  — YoY core, % (NaN, если серия Core недоступна)
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY не задан")

    frames = []
    for country, ids in FRED_CPI_SERIES.items():
        try:
            headline_id = ids["headline"]
            core_id = ids["core"]

            # --- Headline ---
            hl = _fetch_series(headline_id)
            if hl.empty:
                print(f"[SKIP] FRED CPI {country} ({headline_id}): пусто")
                continue

            hl["yoy"] = hl["level"].pct_change(periods=12) * 100
            hl["mom"] = hl["level"].pct_change(periods=1) * 100

            df = hl[["date", "yoy", "mom"]].copy()
            df = df.rename(columns={"yoy": "value"})

            # --- Core (опционально) ---
            if core_id:
                cr = _fetch_series(core_id)
                if not cr.empty:
                    cr["core"] = cr["level"].pct_change(periods=12) * 100
                    cr = cr[["date", "core"]]
                    df = df.merge(cr, on="date", how="left")
                else:
                    df["core"] = pd.NA
            else:
                df["core"] = pd.NA

            df["country"] = country
            df = df[["date", "country", "value", "mom", "core"]]
            df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

            if df.empty:
                print(f"[SKIP] FRED CPI {country}: после расчёта YoY пусто")
                continue

            frames.append(df)
            last = df.iloc[-1]
            core_str = f"{last['core']:.2f}" if pd.notna(last["core"]) else "—"
            print(
                f"[OK] FRED CPI {country} ({headline_id}): {len(df)} строк, "
                f"последняя — {last['date'].date()}, "
                f"YoY={last['value']:.2f}, MoM={last['mom']:.2f}, Core={core_str}"
            )

        except Exception as e:
            print(f"[WARN] FRED CPI {country}: {e}")

    if not frames:
        return pd.DataFrame()

    full = pd.concat(frames, ignore_index=True)
    return full.sort_values(["country", "date"]).reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_fred_cpi()
    print(f"\nВсего строк: {len(df)}")
    if not df.empty:
        print("\nПоследние значения по каждой стране:")
        latest = df.sort_values("date").groupby("country").tail(1)
        print(latest.sort_values("country").to_string(index=False))
