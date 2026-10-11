import pandas as pd
from src.storage import (
    load_imf, load_eurostat, load_eurostat_unemployment, load_eurostat_quarterly,
    load_fred_unemployment, load_fred_gdp,
    load_singapore_unemployment, load_singapore_gdp, load_singapore_quarterly,
    load_brazil_unemployment, load_brazil_gdp, load_brazil_quarterly,
    load_uk_quarterly,
    load_japan_quarterly,
    load_korea_quarterly,
    load_australia_quarterly,
    load_switzerland_quarterly,
    load_canada_quarterly,
    load_policy_rates,
    load_china_unemployment, load_china_debt, load_china_fiscal, load_china_gdp,
    load_india_unemployment, load_india_gdp,
    load_fred_cpi, load_china_cpi, load_brazil_cpi, load_india_cpi, load_uk_cpi,
    load_canada_cpi, load_australia_cpi, load_turkey_cpi, load_switzerland_cpi,
    load_switzerland_unemployment,
    load_japan_cpi, load_korea_cpi, load_singapore_cpi, load_switzerland_gdp,
    load_us_quarterly,
)

COUNTRY_ORDER = [
    "US", "CN", "EU", "JP", "DE", "GB", "FR", "IT", "ES",
    "CA", "AU", "KR", "SG", "BR", "IN", "TR", "CH",
]

COUNTRY_NAMES = {
    "US": "США", "CN": "Китай", "EU": "Еврозона", "JP": "Япония",
    "DE": "Германия", "GB": "Великобритания", "FR": "Франция",
    "IT": "Италия", "ES": "Испания", "CA": "Канада",
    "AU": "Австралия", "KR": "Южная Корея", "SG": "Сингапур",
    "BR": "Бразилия", "IN": "Индия", "TR": "Турция",
    "CH": "Швейцария",
}

MONTH_NAMES = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр",
    5: "май", 6: "июн", 7: "июл", 8: "авг",
    9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}

EUROSTAT_QUARTERLY_COUNTRIES = {"EU", "DE", "FR", "IT", "ES"}

FRED_GDP_COUNTRIES = {"US", "JP", "GB", "CA", "AU", "KR", "TR"}

EUROZONE_COUNTRIES = {"DE", "FR", "IT", "ES"}


def _month_end(year: int, month: int) -> pd.Timestamp:
    if month == 12:
        return pd.Timestamp(year=year, month=12, day=31)
    first_next = pd.Timestamp(year=year, month=month + 1, day=1)
    return first_next - pd.DateOffset(days=1)


def _last_inflation_row(df: pd.DataFrame, country: str, cutoff: pd.Timestamp):
    if df.empty:
        return None
    sub = df[
        (df["country"] == country) &
        (df["date"] <= cutoff)
        ].sort_values("date")
    if sub.empty:
        return None
    return sub.iloc[-1]


def _last_quarterly_value(df: pd.DataFrame, country: str, column: str, cutoff: pd.Timestamp):
    if df.empty or column not in df.columns:
        return None, None
    sub = df[
        (df["country"] == country) &
        (df["date"] <= cutoff) &
        (df[column].notna())
        ].sort_values("date")
    if sub.empty:
        return None, None
    last = sub.iloc[-1]
    return last[column], last["date"]


def _date_label(ts: pd.Timestamp) -> str:
    return f"{MONTH_NAMES[ts.month]} {ts.year}"


def _quarter_label(ts: pd.Timestamp) -> str:
    q = (ts.month - 1) // 3 + 1
    return f"Q{q} {ts.year}"


def build_summary(year: int | None = None, month: int | None = None) -> pd.DataFrame:
    imf = load_imf()
    eurostat = load_eurostat()
    eurostat_q = load_eurostat_quarterly()
    fred_gdp = load_fred_gdp()
    china_debt = load_china_debt()
    china_fiscal = load_china_fiscal()
    china_gdp = load_china_gdp()
    us_quarterly = load_us_quarterly()
    singapore_quarterly = load_singapore_quarterly()
    brazil_quarterly = load_brazil_quarterly()
    uk_quarterly = load_uk_quarterly()
    japan_quarterly = load_japan_quarterly()
    korea_quarterly = load_korea_quarterly()
    australia_quarterly = load_australia_quarterly()
    switzerland_quarterly = load_switzerland_quarterly()
    canada_quarterly = load_canada_quarterly()
    policy_rates = load_policy_rates()
    unemp_eu = load_eurostat_unemployment()
    unemp_fred = load_fred_unemployment()
    unemp_sg = load_singapore_unemployment()
    sg_gdp = load_singapore_gdp()
    unemp_br = load_brazil_unemployment()
    br_gdp = load_brazil_gdp()
    unemp_cn = load_china_unemployment()
    india_gdp = load_india_gdp()
    unemp_in = load_india_unemployment()
    cpi_fred = load_fred_cpi()
    cpi_cn = load_china_cpi()
    cpi_br = load_brazil_cpi()
    cpi_in = load_india_cpi()
    cpi_uk = load_uk_cpi()
    cpi_ca = load_canada_cpi()
    cpi_au = load_australia_cpi()
    cpi_tr = load_turkey_cpi()
    cpi_ch = load_switzerland_cpi()
    unemp_ch = load_switzerland_unemployment()
    cpi_jp = load_japan_cpi()
    cpi_kr = load_korea_cpi()
    cpi_sg = load_singapore_cpi()
    switzerland_gdp = load_switzerland_gdp()

    now = pd.Timestamp.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    cutoff = _month_end(year, month)

    rows = []
    for country in COUNTRY_ORDER:
        row = {
            "country": country,
            "country_name": COUNTRY_NAMES.get(country, country),
        }

        # IMF — базовые значения (годовые). Используется как fallback.
        imf_date = None
        if not imf.empty:
            imf_c = imf[(imf["country"] == country) & (imf["year"] == year)]
            for metric_key, col_name in [
                ("DEBT_GDP", "debt_gdp"),
                ("BUDGET_GDP", "budget_gdp"),
                ("TRADE_GDP", "trade_gdp"),
                ("GDP_GROWTH", "gdp_growth"),
                ("INFLATION", "inflation_imf"),
            ]:
                val = imf_c[imf_c["metric"] == metric_key]["value"]
                row[col_name] = round(val.iloc[0], 2) if not val.empty else None

            if year in imf["year"].values:
                imf_date = f"{year} (IMF, год)"

        row["imf_date"] = imf_date
        row["debt_gdp_date"] = imf_date
        row["budget_gdp_date"] = imf_date
        row["trade_gdp_date"] = imf_date
        row["gdp_growth_date"] = imf_date

        # Eurostat quarterly (EU, DE, FR, IT, ES)
        if country in EUROSTAT_QUARTERLY_COUNTRIES and not eurostat_q.empty:
            for col, date_col in [
                ("debt_gdp", "debt_gdp_date"),
                ("budget_gdp", "budget_gdp_date"),
                ("trade_gdp", "trade_gdp_date"),
                ("gdp_growth", "gdp_growth_date"),
            ]:
                val, dt = _last_quarterly_value(eurostat_q, country, col, cutoff)
                if val is not None:
                    row[col] = round(val, 2)
                    row[date_col] = _quarter_label(dt)

        # FRED GDP (US, JP, GB, CA, AU, KR, TR)
        if country in FRED_GDP_COUNTRIES and not fred_gdp.empty:
            val, dt = _last_quarterly_value(fred_gdp, country, "gdp_growth", cutoff)
            if val is not None:
                row["gdp_growth"] = round(val, 2)
                row["gdp_growth_date"] = _quarter_label(dt)

        # США — квартальные метрики (Treasury + MTS + BEA)
        if country == "US" and not us_quarterly.empty:
            US_LABEL = {
                "debt_gdp": "Federal Gov",
                "budget_gdp": "Federal Gov",
                "trade_gdp": None,
            }
            for col, date_col in [
                ("debt_gdp", "debt_gdp_date"),
                ("budget_gdp", "budget_gdp_date"),
                ("trade_gdp", "trade_gdp_date"),
            ]:
                val, dt = _last_quarterly_value(us_quarterly, "US", col, cutoff)
                if val is not None:
                    row[col] = round(val, 2)
                    label = US_LABEL[col]
                    row[date_col] = f"{_quarter_label(dt)} ({label})" if label else _quarter_label(dt)

        # Великобритания — ONS
        if country == "GB" and not uk_quarterly.empty:
            for col, date_col in [
                ("debt_gdp", "debt_gdp_date"),
                ("budget_gdp", "budget_gdp_date"),
                ("trade_gdp", "trade_gdp_date"),
            ]:
                val, dt = _last_quarterly_value(uk_quarterly, "GB", col, cutoff)
                if val is not None:
                    row[col] = round(val, 2)
                    row[date_col] = _quarter_label(dt)

        # Япония — MOF Central Government
        if country == "JP" and not japan_quarterly.empty:
            val, dt = _last_quarterly_value(japan_quarterly, "JP", "debt_gdp", cutoff)
            if val is not None:
                row["debt_gdp"] = round(val, 2)
                row["debt_gdp_date"] = f"{_quarter_label(dt)} (Central Gov)"

        # Южная Корея — долг/ВВП (IMF DSBB, Central Gov)
        if country == "KR" and not korea_quarterly.empty:
            val, dt = _last_quarterly_value(korea_quarterly, "KR", "debt_gdp", cutoff)
            if val is not None:
                row["debt_gdp"] = round(val, 2)
                row["debt_gdp_date"] = f"{_quarter_label(dt)} (Central Gov)"

        # Австралия — Трейд/ВВП (ABS Data API)
        if country == "AU" and not australia_quarterly.empty:
            val, dt = _last_quarterly_value(australia_quarterly, "AU", "trade_gdp", cutoff)
            if val is not None:
                row["trade_gdp"] = round(val, 2)
                row["trade_gdp_date"] = _quarter_label(dt)

        # Швейцария — Трейд/ВВП (SNB + SECO)
        if country == "CH" and not switzerland_quarterly.empty:
            val, dt = _last_quarterly_value(switzerland_quarterly, "CH", "trade_gdp", cutoff)
            if val is not None:
                row["trade_gdp"] = round(val, 2)
                row["trade_gdp_date"] = _quarter_label(dt)

        # Швейцария — SECO (рост ВВП)
        if country == "CH" and not switzerland_gdp.empty:
            val, dt = _last_quarterly_value(switzerland_gdp, "CH", "gdp_growth", cutoff)
            if val is not None:
                row["gdp_growth"] = round(val, 2)
                row["gdp_growth_date"] = _quarter_label(dt)

        # Канада — долг/бюджет/трейд (StatCan WDS)
        if country == "CA" and not canada_quarterly.empty:
            for col, date_col in [
                ("debt_gdp", "debt_gdp_date"),
                ("budget_gdp", "budget_gdp_date"),
                ("trade_gdp", "trade_gdp_date"),
            ]:
                val, dt = _last_quarterly_value(canada_quarterly, "CA", col, cutoff)
                if val is not None:
                    row[col] = round(val, 2)
                    row[date_col] = _quarter_label(dt)

        # Сингапур — рост ВВП
        if country == "SG" and not sg_gdp.empty:
            val, dt = _last_quarterly_value(sg_gdp, "SG", "gdp_growth", cutoff)
            if val is not None:
                row["gdp_growth"] = round(val, 2)
                row["gdp_growth_date"] = _quarter_label(dt)

        # Сингапур — долг (Central Gov), бюджет (Central Gov), трейд (Current Account)
        if country == "SG" and not singapore_quarterly.empty:
            SG_LABEL = {
                "debt_gdp": "Central Gov",
                "budget_gdp": "Central Gov",
                "trade_gdp": None,
            }
            for col, date_col in [
                ("debt_gdp", "debt_gdp_date"),
                ("budget_gdp", "budget_gdp_date"),
                ("trade_gdp", "trade_gdp_date"),
            ]:
                val, dt = _last_quarterly_value(singapore_quarterly, "SG", col, cutoff)
                if val is not None:
                    row[col] = round(val, 2)
                    label = SG_LABEL[col]
                    row[date_col] = f"{_quarter_label(dt)} ({label})" if label else _quarter_label(dt)

        # Бразилия — рост ВВП (SIDRA)
        if country == "BR" and not br_gdp.empty:
            val, dt = _last_quarterly_value(br_gdp, "BR", "gdp_growth", cutoff)
            if val is not None:
                row["gdp_growth"] = round(val, 2)
                row["gdp_growth_date"] = _quarter_label(dt)

        # Бразилия — долг (BCB DBGG = General Gov) и трейд (BCB)
        if country == "BR" and not brazil_quarterly.empty:
            val, dt = _last_quarterly_value(brazil_quarterly, "BR", "debt_gdp", cutoff)
            if val is not None:
                row["debt_gdp"] = round(val, 2)
                row["debt_gdp_date"] = _quarter_label(dt)

            val, dt = _last_quarterly_value(brazil_quarterly, "BR", "trade_gdp", cutoff)
            if val is not None:
                row["trade_gdp"] = round(val, 2)
                row["trade_gdp_date"] = _quarter_label(dt)

            row["budget_gdp"] = None
            row["budget_gdp_date"] = None

        # Индия — рост ВВП
        if country == "IN" and not india_gdp.empty:
            val, dt = _last_quarterly_value(india_gdp, "IN", "gdp_growth", cutoff)
            if val is not None:
                row["gdp_growth"] = round(val, 2)
                row["gdp_growth_date"] = _quarter_label(dt)

        # Китай — долг (NIFD, Central Government)
        if country == "CN" and not china_debt.empty:
            val, dt = _last_quarterly_value(china_debt, "CN", "debt_gdp", cutoff)
            if val is not None:
                row["debt_gdp"] = round(val, 2)
                row["debt_gdp_date"] = f"{_quarter_label(dt)} (Central Gov)"

        # Китай — бюджет (Минфин, Central Gov) и трейд (SAFE, Current Account)
        if country == "CN" and not china_fiscal.empty:
            CN_LABEL = {
                "budget_gdp": "Central Gov",
                "trade_gdp": None,
            }
            for col, date_col in [
                ("budget_gdp", "budget_gdp_date"),
                ("trade_gdp", "trade_gdp_date"),
            ]:
                val, dt = _last_quarterly_value(china_fiscal, "CN", col, cutoff)
                if val is not None:
                    row[col] = round(val, 2)
                    label = CN_LABEL[col]
                    row[date_col] = f"{_quarter_label(dt)} ({label})" if label else _quarter_label(dt)

        # Китай — рост ВВП
        if country == "CN" and not china_gdp.empty:
            val, dt = _last_quarterly_value(china_gdp, "CN", "gdp_growth", cutoff)
            if val is not None:
                row["gdp_growth"] = round(val, 2)
                row["gdp_growth_date"] = _quarter_label(dt)

        # ============================================================
        # ИНФЛЯЦИЯ
        # ============================================================
        row["inflation"] = None
        row["inflation_date"] = None
        row["inflation_mom"] = None
        row["inflation_mom_date"] = None
        row["inflation_core"] = None
        row["inflation_core_date"] = None

        es_row = _last_inflation_row(eurostat, country, cutoff)
        if es_row is not None:
            row["inflation"] = round(es_row["value"], 2) if pd.notna(es_row.get("value")) else None
            row["inflation_date"] = _date_label(es_row["date"])
            if pd.notna(es_row.get("mom")):
                row["inflation_mom"] = round(es_row["mom"], 2)
                row["inflation_mom_date"] = _date_label(es_row["date"])
            if pd.notna(es_row.get("core")):
                row["inflation_core"] = round(es_row["core"], 2)
                row["inflation_core_date"] = _date_label(es_row["date"])

        if row["inflation"] is None:
            cf = _last_inflation_row(cpi_fred, country, cutoff)
            if cf is not None:
                age_days = (cutoff - cf["date"]).days
                if age_days <= 200:
                    row["inflation"] = round(cf["value"], 2) if pd.notna(cf.get("value")) else None
                    row["inflation_date"] = _date_label(cf["date"])
                    if pd.notna(cf.get("mom")):
                        row["inflation_mom"] = round(cf["mom"], 2)
                        row["inflation_mom_date"] = _date_label(cf["date"])
                    if pd.notna(cf.get("core")):
                        row["inflation_core"] = round(cf["core"], 2)
                        row["inflation_core_date"] = _date_label(cf["date"])

        if row["inflation"] is None and country == "CN" and not cpi_cn.empty:
            cn_row = _last_inflation_row(cpi_cn, country, cutoff)
            if cn_row is not None:
                row["inflation"] = round(cn_row["value"], 2) if pd.notna(cn_row.get("value")) else None
                row["inflation_date"] = _date_label(cn_row["date"])
                if pd.notna(cn_row.get("mom")):
                    row["inflation_mom"] = round(cn_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(cn_row["date"])

        if row["inflation"] is None and country == "BR" and not cpi_br.empty:
            br_row = _last_inflation_row(cpi_br, country, cutoff)
            if br_row is not None:
                row["inflation"] = round(br_row["value"], 2) if pd.notna(br_row.get("value")) else None
                row["inflation_date"] = _date_label(br_row["date"])
                if pd.notna(br_row.get("mom")):
                    row["inflation_mom"] = round(br_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(br_row["date"])
                if pd.notna(br_row.get("core")):
                    row["inflation_core"] = round(br_row["core"], 2)
                    row["inflation_core_date"] = _date_label(br_row["date"])

        if row["inflation"] is None and country == "IN" and not cpi_in.empty:
            in_row = _last_inflation_row(cpi_in, country, cutoff)
            if in_row is not None:
                row["inflation"] = round(in_row["value"], 2) if pd.notna(in_row.get("value")) else None
                row["inflation_date"] = _date_label(in_row["date"])
                if pd.notna(in_row.get("mom")):
                    row["inflation_mom"] = round(in_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(in_row["date"])
                if pd.notna(in_row.get("core")):
                    row["inflation_core"] = round(in_row["core"], 2)
                    row["inflation_core_date"] = _date_label(in_row["date"])

        if row["inflation"] is None and country == "GB" and not cpi_uk.empty:
            uk_row = _last_inflation_row(cpi_uk, country, cutoff)
            if uk_row is not None:
                row["inflation"] = round(uk_row["value"], 2) if pd.notna(uk_row.get("value")) else None
                row["inflation_date"] = _date_label(uk_row["date"])
                if pd.notna(uk_row.get("mom")):
                    row["inflation_mom"] = round(uk_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(uk_row["date"])
                if pd.notna(uk_row.get("core")):
                    row["inflation_core"] = round(uk_row["core"], 2)
                    row["inflation_core_date"] = _date_label(uk_row["date"])

        if row["inflation"] is None and country == "CA" and not cpi_ca.empty:
            ca_row = _last_inflation_row(cpi_ca, country, cutoff)
            if ca_row is not None:
                row["inflation"] = round(ca_row["value"], 2) if pd.notna(ca_row.get("value")) else None
                row["inflation_date"] = _date_label(ca_row["date"])
                if pd.notna(ca_row.get("mom")):
                    row["inflation_mom"] = round(ca_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(ca_row["date"])
                if pd.notna(ca_row.get("core")):
                    row["inflation_core"] = round(ca_row["core"], 2)
                    row["inflation_core_date"] = _date_label(ca_row["date"])

        if row["inflation"] is None and country == "AU" and not cpi_au.empty:
            au_row = _last_inflation_row(cpi_au, country, cutoff)
            if au_row is not None:
                row["inflation"] = round(au_row["value"], 2) if pd.notna(au_row.get("value")) else None
                row["inflation_date"] = _date_label(au_row["date"])
                if pd.notna(au_row.get("mom")):
                    row["inflation_mom"] = round(au_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(au_row["date"])
                if pd.notna(au_row.get("core")):
                    row["inflation_core"] = round(au_row["core"], 2)
                    row["inflation_core_date"] = _date_label(au_row["date"])

        if row["inflation"] is None and country == "TR" and not cpi_tr.empty:
            tr_row = _last_inflation_row(cpi_tr, country, cutoff)
            if tr_row is not None:
                row["inflation"] = round(tr_row["value"], 2) if pd.notna(tr_row.get("value")) else None
                row["inflation_date"] = _date_label(tr_row["date"])
                if pd.notna(tr_row.get("mom")):
                    row["inflation_mom"] = round(tr_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(tr_row["date"])
                if pd.notna(tr_row.get("core")):
                    row["inflation_core"] = round(tr_row["core"], 2)
                    row["inflation_core_date"] = _date_label(tr_row["date"])

        if row["inflation"] is None and country == "CH" and not cpi_ch.empty:
            ch_row = _last_inflation_row(cpi_ch, country, cutoff)
            if ch_row is not None:
                row["inflation"] = round(ch_row["value"], 2) if pd.notna(ch_row.get("value")) else None
                row["inflation_date"] = _date_label(ch_row["date"])
                if pd.notna(ch_row.get("mom")):
                    row["inflation_mom"] = round(ch_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(ch_row["date"])
                if pd.notna(ch_row.get("core")):
                    row["inflation_core"] = round(ch_row["core"], 2)
                    row["inflation_core_date"] = _date_label(ch_row["date"])

        if row["inflation"] is None and country == "JP" and not cpi_jp.empty:
            jp_row = _last_inflation_row(cpi_jp, country, cutoff)
            if jp_row is not None:
                row["inflation"] = round(jp_row["value"], 2) if pd.notna(jp_row.get("value")) else None
                row["inflation_date"] = _date_label(jp_row["date"])
                if pd.notna(jp_row.get("mom")):
                    row["inflation_mom"] = round(jp_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(jp_row["date"])
                if pd.notna(jp_row.get("core")):
                    row["inflation_core"] = round(jp_row["core"], 2)
                    row["inflation_core_date"] = _date_label(jp_row["date"])

        if row["inflation"] is None and country == "KR" and not cpi_kr.empty:
            kr_row = _last_inflation_row(cpi_kr, country, cutoff)
            if kr_row is not None:
                row["inflation"] = round(kr_row["value"], 2) if pd.notna(kr_row.get("value")) else None
                row["inflation_date"] = _date_label(kr_row["date"])
                if pd.notna(kr_row.get("mom")):
                    row["inflation_mom"] = round(kr_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(kr_row["date"])
                if pd.notna(kr_row.get("core")):
                    row["inflation_core"] = round(kr_row["core"], 2)
                    row["inflation_core_date"] = _date_label(kr_row["date"])

        if row["inflation"] is None and country == "SG" and not cpi_sg.empty:
            sg_row = _last_inflation_row(cpi_sg, country, cutoff)
            if sg_row is not None:
                row["inflation"] = round(sg_row["value"], 2) if pd.notna(sg_row.get("value")) else None
                row["inflation_date"] = _date_label(sg_row["date"])
                if pd.notna(sg_row.get("mom")):
                    row["inflation_mom"] = round(sg_row["mom"], 2)
                    row["inflation_mom_date"] = _date_label(sg_row["date"])
                if pd.notna(sg_row.get("core")):
                    row["inflation_core"] = round(sg_row["core"], 2)
                    row["inflation_core_date"] = _date_label(sg_row["date"])

        # Fallback: IMF
        if row["inflation"] is None:
            row["inflation"] = row.get("inflation_imf")
            if row["inflation"] is not None:
                row["inflation_date"] = f"{year} (IMF, год)"

        # ============================================================
        # БЕЗРАБОТИЦА
        # ============================================================
        row["unemployment"] = None
        row["unemployment_date"] = None

        if not unemp_eu.empty:
            un = unemp_eu[
                (unemp_eu["country"] == country) &
                (unemp_eu["date"] <= cutoff)
                ].sort_values("date")
            if not un.empty:
                last = un.iloc[-1]
                row["unemployment"] = round(last["value"], 2)
                row["unemployment_date"] = _date_label(last["date"])

        if row["unemployment"] is None and not unemp_fred.empty:
            uf = unemp_fred[
                (unemp_fred["country"] == country) &
                (unemp_fred["date"] <= cutoff)
                ].sort_values("date")
            if not uf.empty:
                last = uf.iloc[-1]
                row["unemployment"] = round(last["value"], 2)
                row["unemployment_date"] = _date_label(last["date"])

        if row["unemployment"] is None and country == "SG" and not unemp_sg.empty:
            s_data = unemp_sg[unemp_sg["date"] <= cutoff].sort_values("date")
            if not s_data.empty:
                s = s_data.iloc[-1]
                row["unemployment"] = round(s["value"], 2)
                quarter = (s["date"].month - 1) // 3 + 1
                row["unemployment_date"] = f"Q{quarter} {s['date'].year}"

        if row["unemployment"] is None and country == "BR" and not unemp_br.empty:
            b_data = unemp_br[unemp_br["date"] <= cutoff].sort_values("date")
            if not b_data.empty:
                b = b_data.iloc[-1]
                row["unemployment"] = round(b["value"], 2)
                quarter = (b["date"].month - 1) // 3 + 1
                row["unemployment_date"] = f"Q{quarter} {b['date'].year}"

        if row["unemployment"] is None and country == "CN" and not unemp_cn.empty:
            cn_data = unemp_cn[unemp_cn["date"] <= cutoff].sort_values("date")
            if not cn_data.empty:
                last = cn_data.iloc[-1]
                row["unemployment"] = round(last["value"], 2)
                row["unemployment_date"] = _date_label(last["date"])

        if row["unemployment"] is None and country == "IN" and not unemp_in.empty:
            in_data = unemp_in[unemp_in["date"] <= cutoff].sort_values("date")
            if not in_data.empty:
                last = in_data.iloc[-1]
                row["unemployment"] = round(last["value"], 2)
                row["unemployment_date"] = _date_label(last["date"])

        if row["unemployment"] is None and country == "CH" and not unemp_ch.empty:
            ch_data = unemp_ch[unemp_ch["date"] <= cutoff].sort_values("date")
            if not ch_data.empty:
                last = ch_data.iloc[-1]
                row["unemployment"] = round(last["value"], 2)
                row["unemployment_date"] = _date_label(last["date"])

        # ============================================================
        # СТАВКА ЦБ
        # ============================================================
        row["policy_rate"] = None
        row["policy_rate_date"] = None

        if not policy_rates.empty:
            # Для DE, FR, IT, ES — используем ставку ЕЦБ (EU)
            rate_country = "EU" if country in EUROZONE_COUNTRIES else country
            pr = policy_rates[
                (policy_rates["country"] == rate_country) &
                (policy_rates["date"] <= cutoff)
                ].sort_values("date")
            if not pr.empty:
                last = pr.iloc[-1]
                row["policy_rate"] = round(last["rate"], 2)
                row["policy_rate_date"] = _date_label(last["date"])

        rows.append(row)

    return pd.DataFrame(rows)
