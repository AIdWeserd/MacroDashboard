import pandas as pd
from imf_reader import weo

# Наш код -> код IMF WEO
COUNTRY_TO_WEO = {
    "US": "USA",
    "CN": "CHN",
    "EU": "G163",  # Euro Area
    "JP": "JPN",
    "DE": "DEU",
    "GB": "GBR",
    "FR": "FRA",
    "IT": "ITA",
    "ES": "ESP",
    "CA": "CAN",
    "AU": "AUS",
    "KR": "KOR",
    "SG": "SGP",
    "BR": "BRA",
    "IN": "IND",
    "TR": "TUR",
    "CH": "CHE",
    "KZ": "KAZ",
}

# Наш код метрики -> код концепта IMF WEO
IMF_CONCEPTS = {
    "DEBT_GDP": "GGXWDG_NGDP",
    "BUDGET_GDP": "GGXCNL_NGDP",
    "TRADE_GDP": "BCA_NGDPD",
    "GDP_GROWTH": "NGDP_RPCH",
    "INFLATION": "PCPIPCH",
}


def fetch_all_imf() -> pd.DataFrame:
    """
    Тянет WEO через imf-reader, фильтрует по нужным странам и метрикам.
    Возвращает DataFrame с колонками: country, year, metric, value.
    """
    try:
        df = weo.fetch_data()
    except Exception as e:
        print(f"[ERROR] IMF WEO: {e}")
        return pd.DataFrame()

    # Фильтр по странам
    weo_codes = list(COUNTRY_TO_WEO.values())
    df = df[df["REF_AREA_CODE"].isin(weo_codes)].copy()

    # Фильтр по индикаторам
    concepts = list(IMF_CONCEPTS.values())
    df = df[df["CONCEPT_CODE"].isin(concepts)].copy()

    if df.empty:
        return pd.DataFrame()

    # Переименование колонок
    df = df.rename(columns={
        "REF_AREA_CODE": "country_weo",
        "CONCEPT_CODE": "metric_weo",
        "TIME_PERIOD": "year",
        "OBS_VALUE": "value",
    })

    # Обратный маппинг кодов
    weo_to_country = {v: k for k, v in COUNTRY_TO_WEO.items()}
    concept_to_metric = {v: k for k, v in IMF_CONCEPTS.items()}

    df["country"] = df["country_weo"].map(weo_to_country)
    df["metric"] = df["metric_weo"].map(concept_to_metric)

    # Числа
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df = df.dropna(subset=["country", "metric", "year", "value"])

    # Оставляем нужные годы
    df = df[(df["year"] >= 2015) & (df["year"] <= 2030)]

    return df[["country", "year", "metric", "value"]].sort_values(
        ["metric", "country", "year"]
    ).reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_all_imf()
    print(f"Всего строк: {len(df)}")
    print(f"Стран: {df['country'].nunique() if not df.empty else 0}")
    if not df.empty:
        print(f"Годы: {df['year'].min()} – {df['year'].max()}")
        print("\nДанные за 2026:")
        latest = df[df["year"] == 2026]
        print(latest.to_string())
