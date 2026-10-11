import io
import streamlit as st
import pandas as pd
from config import COUNTRIES, INDICATORS
from src.storage import (
    load_fred, load_rss, load_forexfactory, load_imf,
    load_eurostat, load_eurostat_unemployment,
    load_policy_rates,
)
from src.build_summary import build_summary, COUNTRY_NAMES, MONTH_NAMES
from src.snapshot import (
    save_weekly_snapshot, load_previous_snapshot,
    compare_with_previous, SUMMARY_METRICS,
)
from src.fetch_forexfactory import fetch_calendar
from src.charts import line_chart

st.set_page_config(page_title="Macro Dashboard", layout="wide")
st.title("📈 Макро-дашборд")


@st.dialog("График", width="large")
def show_chart_fullscreen(fig):
    st.plotly_chart(fig, width='stretch')
    if st.button("Закрыть"):
        st.rerun()


# ============================================================
# Хелперы для экспорта
# ============================================================
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Macro")
    return buf.getvalue()


def to_html_bytes(df: pd.DataFrame) -> bytes:
    html = df.to_html(index=False, escape=False, border=1, justify="center")
    return html.encode("utf-8-sig")


def to_pdf_bytes(df: pd.DataFrame) -> bytes:
    try:
        from fpdf import FPDF
    except ImportError:
        return b""

    def translit(s: str) -> str:
        table = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
            "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
            "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
            "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
            "э": "e", "ю": "yu", "я": "ya", "—": "-",
        }
        return "".join(table.get(c.lower(), c) for c in s)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=8)

    cols = [translit(str(c)) for c in df.columns]
    col_width = (pdf.w - 20) / max(len(cols), 1)

    for c in cols:
        pdf.cell(col_width, 6, c[:20], border=1)
    pdf.ln()

    for _, row in df.iterrows():
        for val in row:
            txt = translit(str(val)).replace("\n", " ")
            pdf.cell(col_width, 6, txt[:20], border=1)
        pdf.ln()

    return bytes(pdf.output())


# ============================================================
# Хелпер: value_if_in_period
# ============================================================
def parse_date_label(date_label: str) -> tuple[str, int] | None:
    """
    Парсит date_label. Возвращает (тип, номер) или None.
    - ("month", YYYYMM) — "авг 2026"
    - ("quarter", YYYYQQ) — "Q2 2026"
    - ("year", YYYY) — "2026 (IMF, год)"
    """
    if not date_label:
        return None
    s = str(date_label).strip()
    parts = s.replace(",", "").split()
    if len(parts) < 2:
        return None

    if "IMF" in s or "год" in s:
        try:
            return ("year", int(parts[0]))
        except ValueError:
            return None

    if parts[0].startswith("Q"):
        try:
            q = int(parts[0][1:])
            y = int(parts[1])
            return ("quarter", y * 10 + q)
        except ValueError:
            return None

    month_str, year_str = parts[0], parts[1]
    inv_months = {v: k for k, v in MONTH_NAMES.items()}
    if month_str in inv_months:
        try:
            y = int(year_str)
            return ("month", y * 100 + inv_months[month_str])
        except ValueError:
            return None

    return None


def value_if_in_period(value, date_label, target_year, target_month) -> str:
    """
    Показывает значение, если его период завершился не позже выбранного месяца.
    """
    if pd.isna(value) or value is None:
        return "—"

    parsed = parse_date_label(date_label)
    if parsed is None:
        return "—"

    kind, num = parsed
    target_month_num = target_year * 100 + target_month

    if kind == "month":
        if num == target_month_num:
            return f"{value:.2f}"
        return "—"

    if kind == "quarter":
        q_year = num // 10
        q_num = num % 10
        q_end_month = q_num * 3
        q_end = q_year * 100 + q_end_month
        if q_end <= target_month_num:
            return f"{value:.2f}"
        return "—"

    if kind == "year":
        if num <= target_year:
            return f"{value:.2f}"
        return "—"

    return "—"


# ============================================================
# ГЛАВНАЯ: Сводная таблица
# ============================================================
st.subheader("🌍 Сводная таблица по странам")

imf = load_imf()
now = pd.Timestamp.now()

if not imf.empty:
    available_years = sorted(
        set(imf["year"].unique()) | {now.year},
        reverse=True,
    )
else:
    available_years = [now.year]

default_year_idx = available_years.index(now.year) if now.year in available_years else 0

MONTH_OPTIONS = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр",
    5: "май", 6: "июн", 7: "июл", 8: "авг",
    9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}

# ============================================================
# ФИЛЬТРЫ ПЕРВОЙ ТАБЛИЦЫ
# ============================================================
col_year, col_month = st.columns(2)
with col_year:
    selected_year = st.selectbox(
        "Год",
        available_years,
        index=default_year_idx,
        key="summary_year",
    )
with col_month:
    selected_month_name = st.selectbox(
        "Месяц",
        list(MONTH_OPTIONS.values()),
        index=now.month - 1,
        key="summary_month",
    )
    selected_month = [k for k, v in MONTH_OPTIONS.items() if v == selected_month_name][0]

summary = build_summary(year=selected_year, month=selected_month)

if summary.empty:
    st.warning("Нет данных. Запусти: python scheduler.py")
else:
    previous = load_previous_snapshot()
    changed = compare_with_previous(summary, previous)

    display = summary[[
        "country", "country_name",
        "inflation", "inflation_date",
        "inflation_mom", "inflation_mom_date",
        "inflation_core", "inflation_core_date",
        "unemployment", "unemployment_date",
        "debt_gdp", "debt_gdp_date",
        "budget_gdp", "budget_gdp_date",
        "trade_gdp", "trade_gdp_date",
        "gdp_growth", "gdp_growth_date",
        "policy_rate", "policy_rate_date",
    ]].copy()


    def merge_value_date(value, date):
        if pd.isna(value) or value is None:
            return "—"
        val_str = f"{value:.2f}"
        if date:
            return f"{val_str}\n{date}"
        return val_str


    display["Инфляция"] = [merge_value_date(v, d) for v, d in zip(display["inflation"], display["inflation_date"])]
    display["Инфляция MoM"] = [merge_value_date(v, d) for v, d in
                               zip(display["inflation_mom"], display["inflation_mom_date"])]
    display["Core"] = [merge_value_date(v, d) for v, d in
                       zip(display["inflation_core"], display["inflation_core_date"])]
    display["Безработица"] = [merge_value_date(v, d) for v, d in
                              zip(display["unemployment"], display["unemployment_date"])]
    display["Долг/ВВП"] = [merge_value_date(v, d) for v, d in zip(display["debt_gdp"], display["debt_gdp_date"])]
    display["Бюджет/ВВП"] = [merge_value_date(v, d) for v, d in zip(display["budget_gdp"], display["budget_gdp_date"])]
    display["Трейд/ВВП"] = [merge_value_date(v, d) for v, d in zip(display["trade_gdp"], display["trade_gdp_date"])]
    display["Рост ВВП"] = [merge_value_date(v, d) for v, d in zip(display["gdp_growth"], display["gdp_growth_date"])]
    display["Ставка"] = [merge_value_date(v, d) for v, d in zip(display["policy_rate"], display["policy_rate_date"])]

    display = display.rename(columns={"country_name": "Страна"})

    ALL_METRIC_COLS = [
        "Инфляция", "Инфляция MoM", "Core",
        "Безработица",
        "Долг/ВВП", "Бюджет/ВВП", "Трейд/ВВП",
        "Рост ВВП",
        "Ставка",
    ]

    # ============================================================
    # ФИЛЬТРЫ КОЛОНОК через st.pills (галочки)
    # ============================================================
    selected_cols = st.pills(
        "Какие метрики показывать (таблица с датами)",
        options=ALL_METRIC_COLS,
        default=ALL_METRIC_COLS,
        selection_mode="multi",
        key="summary_cols_pills",
    )
    if not selected_cols:
        selected_cols = ALL_METRIC_COLS

    display_with_dates = display[["country", "Страна"] + selected_cols].copy()

    metric_to_key = {human: key for key, human in SUMMARY_METRICS}
    highlight_color = "background-color: #ccffcc"


    def highlight_row(row):
        country = row["country"]
        styles = [""] * len(row)
        for i, col in enumerate(row.index):
            if col in ("country", "Страна"):
                continue
            metric_key = metric_to_key.get(col)
            if metric_key is None:
                continue
            if (country, metric_key) in changed:
                styles[i] = highlight_color
        return styles


    styled = display_with_dates.style.apply(highlight_row, axis=1)

    st.dataframe(
        styled,
        width='stretch',
        hide_index=True,
        column_config={"country": None},
    )

    if changed:
        st.caption(f"🟢 Зелёным подсвечены {len(changed)} обновившихся метрик относительно снимка недельной давности.")
    else:
        if previous.empty:
            st.caption("📸 Прошлый снимок ещё не накоплен — подсветка появится после следующей недели.")
        else:
            st.caption("🟢 Свежих изменений относительно прошлого снимка нет.")

    # ============================================================
    # ВТОРАЯ ТАБЛИЦА — со своими фильтрами
    # ============================================================
    st.markdown("---")
    st.subheader("🔢 Таблица без дат (только значения)")
    st.caption(
        "Показаны значения, чей период **завершился не позже выбранного месяца**: "
        "месячные — точно в этом месяце; квартальные — если квартал закончился; "
        "годовые — если год уже прошёл."
    )

    col2_year, col2_month = st.columns(2)
    with col2_year:
        selected_year_2 = st.selectbox(
            "Год (без дат)",
            available_years,
            index=default_year_idx,
            key="no_dates_year",
        )
    with col2_month:
        selected_month_name_2 = st.selectbox(
            "Месяц (без дат)",
            list(MONTH_OPTIONS.values()),
            index=now.month - 1,
            key="no_dates_month",
        )
        selected_month_2 = [k for k, v in MONTH_OPTIONS.items() if v == selected_month_name_2][0]

    selected_cols_2 = st.pills(
        "Какие метрики показывать (таблица без дат)",
        options=ALL_METRIC_COLS,
        default=ALL_METRIC_COLS,
        selection_mode="multi",
        key="no_dates_cols_pills",
    )
    if not selected_cols_2:
        selected_cols_2 = ALL_METRIC_COLS

    if selected_year_2 != selected_year or selected_month_2 != selected_month:
        summary_2 = build_summary(year=selected_year_2, month=selected_month_2)
    else:
        summary_2 = summary

    display_no_dates = summary_2[["country", "country_name"]].copy()
    display_no_dates = display_no_dates.rename(columns={"country_name": "Страна"})

    for col in selected_cols_2:
        key = metric_to_key.get(col)
        if key is None:
            display_no_dates[col] = "—"
            continue
        value_col = key
        date_col = f"{key}_date"
        if value_col not in summary_2.columns or date_col not in summary_2.columns:
            display_no_dates[col] = "—"
            continue
        display_no_dates[col] = [
            value_if_in_period(v, d, selected_year_2, selected_month_2)
            for v, d in zip(summary_2[value_col], summary_2[date_col])
        ]

    st.dataframe(
        display_no_dates.drop(columns=["country"]),
        width='stretch',
        hide_index=True,
    )

    # ============================================================
    # ЭКСПОРТ
    # ============================================================
    st.markdown("---")
    st.subheader("📥 Скачать таблицу")

    col_fmt, col_which = st.columns(2)
    with col_fmt:
        export_format = st.selectbox(
            "Формат",
            ["CSV", "Excel (.xlsx)", "HTML", "PDF"],
            key="export_format",
        )
    with col_which:
        export_which = st.selectbox(
            "Какую таблицу",
            ["С датами", "Без дат"],
            key="export_which",
        )

    if export_which == "С датами":
        export_df = display_with_dates.drop(columns=["country"])
    else:
        export_df = display_no_dates.drop(columns=["country"])

    if export_format == "CSV":
        data = export_df.to_csv(index=False).encode("utf-8-sig")
        mime = "text/csv"
        ext = "csv"
    elif export_format == "Excel (.xlsx)":
        data = to_excel_bytes(export_df)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif export_format == "HTML":
        data = to_html_bytes(export_df)
        mime = "text/html"
        ext = "html"
    else:
        data = to_pdf_bytes(export_df)
        mime = "application/pdf"
        ext = "pdf"

    st.download_button(
        label=f"📥 Скачать {export_format}",
        data=data,
        file_name=f"macro_{'with' if export_which == 'С датами' else 'no'}_dates.{ext}",
        mime=mime,
        key="download_table",
    )

    st.caption(
        "📌 **Источники:** IMF WEO, Eurostat, FRED, BEA, Treasury Fiscal Data, "
        "национальные статистические службы. Дата указана под значением."
    )

st.divider()

# ============================================================
# Expander'ы
# ============================================================

with st.expander("📆 Месячные метрики (детально)", expanded=False):
    eurostat = load_eurostat()
    unemp = load_eurostat_unemployment()

    if not eurostat.empty:
        st.markdown("**Инфляция (HICP, ЕС) — YoY / MoM / Core**")
        es_rows = []
        for country in eurostat["country"].unique():
            sub = eurostat[eurostat["country"] == country].sort_values("date")
            if sub.empty:
                continue
            last = sub.iloc[-1]
            es_rows.append({
                "Страна": COUNTRY_NAMES.get(country, country),
                "Месяц": f"{MONTH_NAMES[last['date'].month]} {last['date'].year}",
                "YoY, %": round(last["value"], 2) if pd.notna(last.get("value")) else None,
                "MoM, %": round(last["mom"], 2) if pd.notna(last.get("mom")) else None,
                "Core YoY, %": round(last["core"], 2) if pd.notna(last.get("core")) else None,
            })
        if es_rows:
            st.dataframe(pd.DataFrame(es_rows), width='stretch', hide_index=True)

    if not unemp.empty:
        st.markdown("**Безработица (%, SA)**")
        un_rows = []
        for country in unemp["country"].unique():
            sub = unemp[unemp["country"] == country].sort_values("date")
            if len(sub) < 2:
                continue
            last = sub.iloc[-1]
            prev = sub.iloc[-2]
            un_rows.append({
                "Страна": COUNTRY_NAMES.get(country, country),
                "Месяц": f"{MONTH_NAMES[last['date'].month]} {last['date'].year}",
                "Безработица, %": round(last["value"], 2),
                "Пред. месяц, %": round(prev["value"], 2),
                "Изм., п.п.": round(last["value"] - prev["value"], 2),
            })
        if un_rows:
            st.dataframe(pd.DataFrame(un_rows), width='stretch', hide_index=True)

with st.expander("💰 Ставки ЦБ (исторические)", expanded=False):
    pr = load_policy_rates()
    if pr.empty:
        st.caption("Нет данных. Запусти: python scheduler.py rates")
    else:
        months_back = st.slider("Месяцев назад", 6, 36, 12, key="rates_months")
        cutoff_pr = pd.Timestamp.now() - pd.DateOffset(months=months_back)
        pr_filtered = pr[pr["date"] >= cutoff_pr].copy()

        pr_filtered["month_label"] = pr_filtered["date"].apply(
            lambda d: f"{MONTH_NAMES[d.month]} {d.year}"
        )
        month_order = (
            pr_filtered[["date", "month_label"]]
            .drop_duplicates()
            .sort_values("date")["month_label"]
            .tolist()
        )
        pivot = pr_filtered.pivot_table(
            index="country",
            columns="month_label",
            values="rate",
            aggfunc="last",
        )
        pivot.index = [COUNTRY_NAMES.get(c, c) for c in pivot.index]
        pivot = pivot[[c for c in month_order if c in pivot.columns]]

        st.dataframe(pivot, width="stretch")

        csv_pr = pivot.to_csv().encode("utf-8-sig")
        st.download_button(
            label="📥 Скачать ставки в CSV",
            data=csv_pr,
            file_name="policy_rates.csv",
            mime="text/csv",
            key="download_rates",
        )

with st.expander("📅 Экономический календарь", expanded=False):
    with st.spinner("Загружаю календарь..."):
        try:
            cal = fetch_calendar()
        except Exception as e:
            st.error(f"Ошибка: {e}")
            cal = pd.DataFrame()

    if not cal.empty:
        min_imp = st.slider("Мин. важность", 1, 3, 2, key="cal_imp")
        filtered = cal[cal["importance"] >= min_imp]
        st.caption(f"Событий: {len(filtered)}")
        for _, row in filtered.head(30).iterrows():
            dt = row["datetime"].strftime("%Y-%m-%d %H:%M")
            stars = "⭐" * int(row["importance"])
            actual = row.get("actual") or "—"
            forecast = row.get("forecast") or "—"
            previous = row.get("previous") or "—"
            st.markdown(
                f"**{dt} — {row['country']} — {row['event']}** {stars}  \n"
                f"Actual: `{actual}` | Forecast: `{forecast}` | Previous: `{previous}`"
            )
            st.divider()

with st.expander("📊 FRED (исторические ряды)", expanded=False):
    macro = load_fred()
    if not macro.empty:
        col1, col2 = st.columns(2)
        country = col1.selectbox("Страна", list(COUNTRIES.keys()), key="fred_c")
        indicator = col2.selectbox("Индикатор", list(INDICATORS.keys()), key="fred_i")
        fig = line_chart(macro, country, indicator)
        if fig:
            st.plotly_chart(fig, width='stretch')
            if st.button("🔍 Открыть график на весь экран", key="fred_fullscreen"):
                show_chart_fullscreen(fig)

with st.expander("📰 Новости", expanded=False):
    news = load_rss()
    if not news.empty:
        for _, row in news.head(20).iterrows():
            st.markdown(
                f"**[{row['title']}]({row['link']})**  \n"
                f"<small>{row['source']} — {row['published']:%Y-%m-%d %H:%M}</small>",
                unsafe_allow_html=True,
            )
            st.divider()
