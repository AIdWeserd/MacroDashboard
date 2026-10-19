
"""
Россия — CPI, квартальные госфинансы, текущий счёт,
рост ВВП и безработица.

Источники: Банк России, Росстат, Федеральное казначейство.

Запуск:
    python -m src.fetch_russia
"""

import re
import time
import warnings
import xml.etree.ElementTree as ET

from io import BytesIO
from urllib.parse import urljoin, urlparse

import pymupdf
import pandas as pd
import requests

from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning


# ============================================================
# Россия — инфляция
# ============================================================

BASE_URL = "https://www.cbr.ru"
INDEX_URL = BASE_URL + "/analytics/dkp/dinamic/"

FALLBACK_PDF_URL = (
    BASE_URL
    + "/Collection/Collection/File/62446/CPD_2026-9.pdf"
)

START_DATE = pd.Timestamp("2024-01-01")

MONTHS = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}

MONTH_PATTERN = "|".join(MONTHS)
NUMBER_PATTERN = r"-?\d+[.,]\d+"

ROW_PATTERN = re.compile(
    rf"^\s*({MONTH_PATTERN})\s+"
    rf"((?:{NUMBER_PATTERN}\s*)+)$",
    re.IGNORECASE,
)

PDF_LINK_PATTERN = re.compile(
    r"""(?:https?://(?:www\.)?cbr\.ru)?"""
    r"""(/Collection/Collection/File/\d+/CPD_"""
    r"""\d{4}[-_]\d{1,2}\.pdf)""",
    re.IGNORECASE,
)


def _session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    return session


def _get(session, url):
    response = session.get(
        url,
        timeout=(15, 60),
    )
    response.raise_for_status()
    return response


def _normalize(text):
    return (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("\u00ad", "")
        .replace("‑", "-")
        .replace("–", "-")
        .strip()
    )


def _pdf_period(url):
    match = re.search(
        r"CPD_(\d{4})[-_](\d{1,2})\.pdf",
        url,
        re.IGNORECASE,
    )

    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2))

    if not 1 <= month <= 12:
        return None

    return year, month


def _is_cbr_url(url):
    parsed = urlparse(url)

    return (
        parsed.scheme == "https"
        and parsed.hostname in ("www.cbr.ru", "cbr.ru")
    )


def _extract_pdf_links(html, base_url):
    links = set()

    for match in PDF_LINK_PATTERN.finditer(html):
        links.add(
            urljoin(BASE_URL, match.group(1))
        )

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["a", "iframe", "embed"]):
        raw = tag.get("href") or tag.get("src") or ""
        url = urljoin(base_url, raw)

        if _is_cbr_url(url) and _pdf_period(url) is not None:
            links.add(url)

    return links


def _discover_pdf_urls(session):
    """
    Автоматически ищет выпуски на сайте ЦБ РФ.

    Если более новый выпуск не найден,
    используется последний проверенный PDF.
    """
    urls = {FALLBACK_PDF_URL}

    try:
        response = _get(session, INDEX_URL)

        urls.update(
            _extract_pdf_links(
                response.text,
                response.url,
            )
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        issue_pages = []

        for tag in soup.find_all("a", href=True):
            url = urljoin(
                response.url,
                tag["href"],
            )

            if not _is_cbr_url(url):
                continue

            if re.search(
                r"/analytics/dkp/dinamic/"
                r"CPD_\d{4}[-_]\d{1,2}/?",
                url,
                re.IGNORECASE,
            ):
                issue_pages.append(url)

        def issue_key(url):
            match = re.search(
                r"CPD_(\d{4})[-_](\d{1,2})",
                url,
                re.IGNORECASE,
            )

            if not match:
                return (0, 0)

            return (
                int(match.group(1)),
                int(match.group(2)),
            )

        issue_pages = sorted(
            set(issue_pages),
            key=issue_key,
            reverse=True,
        )

        for url in issue_pages[:4]:
            try:
                page = _get(session, url)

                urls.update(
                    _extract_pdf_links(
                        page.text,
                        page.url,
                    )
                )

            except requests.RequestException as exc:
                print(
                    "[WARN] Не удалось открыть выпуск:",
                    url,
                    exc,
                )

    except requests.RequestException as exc:
        print(
            "[WARN] Архив ЦБ временно недоступен:",
            exc,
        )

    return sorted(
        urls,
        key=lambda url: _pdf_period(url) or (0, 0),
        reverse=True,
    )


def _find_table_page(document, number):
    markers = {
        6: (
            "ДИНАМИКА ПОТРЕБИТЕЛЬСКИХ ЦЕН",
            "МЕСЯЦ К",
            "ПРЕДЫДУЩЕГО",
        ),
        8: (
            "СТРУКТУРА ПРИРОСТА ИНФЛЯЦИИ",
            "ЗА МЕСЯЦ",
        ),
    }

    for page_number in range(len(document)):
        text = _normalize(
            document[page_number].get_text(
                "text",
                sort=True,
            )
        )

        upper = text.upper()

        if not all(
            marker in upper
            for marker in markers[number]
        ):
            continue

        if re.search(
            rf"табл\.?\s*{number}\b",
            text,
            re.IGNORECASE,
        ):
            return page_number

    raise ValueError(
        f"Не найдена таблица № {number}"
    )


def _read_table(document, number):
    """
    Таблица 6:
        value = CPI YoY
        core  = Core CPI YoY

    Таблица 8:
        mom = CPI MoM без сезонной корректировки.
    """
    page_number = _find_table_page(
        document,
        number,
    )

    text = _normalize(
        document[page_number].get_text(
            "text",
            sort=True,
        )
    )

    records = []
    year = None

    for original_line in text.splitlines():
        line = _normalize(original_line)

        year_match = re.fullmatch(
            r"(202[4-9]|20[3-9]\d)",
            line,
        )

        if year_match:
            year = int(year_match.group(1))
            continue

        if year is None:
            continue

        match = ROW_PATTERN.match(
            line.lower()
        )

        if not match:
            continue

        month_name = match.group(1)

        values = re.findall(
            NUMBER_PATTERN,
            match.group(2),
        )

        expected_columns = 8 if number == 6 else 7

        if len(values) != expected_columns:
            raise ValueError(
                f"Таблица {number}: "
                f"{month_name} {year}; "
                f"ожидалось {expected_columns} "
                f"числовых колонок, получено {len(values)}"
            )

        values = [
            float(value.replace(",", "."))
            for value in values
        ]

        month = MONTHS[month_name]

        date = (
            pd.Timestamp(year, month, 1)
            + pd.offsets.MonthEnd(0)
        )

        if date < START_DATE:
            continue

        if number == 6:
            record = {
                "date": date,
                "value": values[0],
                "core": values[1],
            }
        else:
            record = {
                "date": date,
                "mom": values[4],
            }

        records.append(record)

    if not records:
        raise ValueError(
            f"Таблица {number}: "
            "месячные значения не найдены"
        )

    result = pd.DataFrame(records)

    if result["date"].duplicated().any():
        raise ValueError(
            f"Таблица {number}: повторяющиеся даты"
        )

    return result.sort_values("date")


def _parse_pdf(data, source_url):
    if not data.startswith(b"%PDF"):
        raise ValueError(
            "ЦБ вернул файл, который не является PDF"
        )

    document = pymupdf.open(
        stream=BytesIO(data),
        filetype="pdf",
    )

    try:
        yoy_core = _read_table(
            document,
            6,
        )

        mom = _read_table(
            document,
            8,
        )

    finally:
        document.close()

    result = yoy_core.merge(
        mom,
        on="date",
        how="outer",
        validate="one_to_one",
    )

    result["country"] = "RU"
    result["cbr_source_url"] = source_url

    result["cbr_methodology"] = (
        "CPI YoY: таблица 6; "
        "Core CPI YoY: таблица 6; "
        "CPI MoM: таблица 8, "
        "без сезонной корректировки"
    )

    return result[
        [
            "date",
            "country",
            "value",
            "mom",
            "core",
            "cbr_source_url",
            "cbr_methodology",
        ]
    ].sort_values("date").reset_index(drop=True)


def _validate(df, issue_period):
    year, month = issue_period

    cutoff = (
        pd.Timestamp(year, month, 1)
        + pd.offsets.MonthEnd(0)
    )

    df = df[
        (df["date"] >= START_DATE)
        & (df["date"] <= cutoff)
    ].copy()

    calendar = pd.date_range(
        START_DATE,
        cutoff,
        freq="ME",
    )

    missing = sorted(
        set(calendar) - set(df["date"])
    )

    if missing:
        raise ValueError(
            "Отсутствуют месяцы: "
            + ", ".join(
                date.strftime("%Y-%m")
                for date in missing
            )
        )

    for column in ("value", "mom", "core"):
        if df[column].isna().any():
            raise ValueError(
                f"Пропуски показателя {column}"
            )

    # Контроль по уже проверенному выпуску.
    if cutoff >= pd.Timestamp("2026-09-30"):
        sep = df.loc[
            df["date"] == pd.Timestamp("2026-09-30")
        ]

        if len(sep) != 1:
            raise ValueError(
                "Отсутствует сентябрь 2026"
            )

        row = sep.iloc[0]

        expected = {
            "value": 6.35,
            "mom": 0.35,
            "core": 5.47,
        }

        for column, expected_value in expected.items():
            if abs(
                float(row[column]) - expected_value
            ) > 0.001:
                raise ValueError(
                    f"Контроль {column}: "
                    f"{row[column]}, "
                    f"ожидалось {expected_value}"
                )

    return df.reset_index(drop=True)


def fetch_russia_cpi():
    """Получает три ряда инфляции из Банка России."""
    session = _session()

    print("[CBR] Поиск официальных выпусков...")

    pdf_urls = _discover_pdf_urls(session)
    errors = []

    for pdf_url in pdf_urls:
        period = _pdf_period(pdf_url)

        if period is None or period < (2026, 9):
            continue

        print(
            "[CBR] Проверяем:",
            pdf_url,
        )

        try:
            response = _get(
                session,
                pdf_url,
            )

            df = _parse_pdf(
                response.content,
                response.url,
            )

            df = _validate(
                df,
                period,
            )

            print(
                "[CBR] Успешно:",
                len(df),
                "месяцев",
            )

            return df

        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
            pymupdf.FileDataError,
        ) as exc:
            errors.append(
                f"{pdf_url}: {exc}"
            )

            print(
                "[CBR] Ошибка:",
                exc,
            )

    raise RuntimeError(
        "Не удалось получить официальный ряд "
        "инфляции Банка России.\n"
        + "\n".join(errors)
    )


# ============================================================
# Россия — квартальные показатели
# ============================================================

RU_GDP_URL = (
    "https://rosstat.gov.ru/storage/mediabank/"
    "VVP_kvartal_s-1995-2026.xlsx"
)

RU_GFS_URLS = {
    2024: (
        "https://roskazna.gov.ru/uploads/migrate/eng/"
        "documents/budgets-execution-information/"
        "government-finance-statistics-reporting-of-"
        "the-russian-federation/GFS 4q2024.xlsx"
    ),
    2025: (
        "https://roskazna.gov.ru/storage/page-files/"
        "39/GFS 4q2025_IMF.xlsx"
    ),
    2026: (
        "https://roskazna.gov.ru/storage/page-files/"
        "39/GFS 2q2026_с.xlsx"
    ),
}

RU_BOP_URL = (
    "https://www.cbr.ru/vfs/statistics/"
    "credit_statistics/bop/"
    "bal_of_payments_standart.xlsx"
)

RU_FX_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"


def _ru_download(url, params=None):
    last_error = None

    for attempt in range(4):
        try:
            # Временный обход TLS-проблемы на Windows.
            with warnings.catch_warnings():
                warnings.simplefilter(
                    "ignore",
                    InsecureRequestWarning,
                )

                result = requests.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0"
                    },
                    verify=False,
                    timeout=(25, 90),
                )

            result.raise_for_status()
            return result.content

        except requests.RequestException as exc:
            last_error = exc

            if attempt < 3:
                time.sleep(2 * (attempt + 1))

    raise RuntimeError(
        f"Ошибка загрузки {url}: {last_error}"
    )


def _ru_excel(url, sheet):
    content = _ru_download(url)

    if not content.startswith(b"PK"):
        raise ValueError(
            f"Ожидался XLSX: {url}"
        )

    return pd.read_excel(
        BytesIO(content),
        sheet_name=sheet,
        header=None,
    )


def _ru_nominal_gdp():
    frame = _ru_excel(RU_GDP_URL, "2")

    values = {}
    year = None

    quarter_map = {
        "I": 1,
        "II": 2,
        "III": 3,
        "IV": 4,
    }

    for col in range(frame.shape[1]):
        year_match = re.search(
            r"(?:19|20)\d{2}",
            str(frame.iat[2, col]),
        )

        if year_match:
            year = int(year_match.group())

        if year is None or year < 2023:
            continue

        quarter_match = re.search(
            r"\b(IV|III|II|I)\s+квартал",
            str(frame.iat[3, col]),
            re.IGNORECASE,
        )

        if not quarter_match:
            continue

        amount = pd.to_numeric(
            frame.iat[4, col],
            errors="coerce",
        )

        if pd.notna(amount):
            quarter = quarter_map[
                quarter_match.group(1).upper()
            ]

            values[f"{year}Q{quarter}"] = float(
                amount
            )

    return values


def _ru_gfs_data():
    nlb = {}
    debt = {}

    for year, url in RU_GFS_URLS.items():
        ops = _ru_excel(
            url,
            "Stmt of Govt Operations",
        )

        bal = _ru_excel(
            url,
            "Balance Sheet",
        )

        def code_row(frame, code):
            hits = [
                i
                for i in range(frame.shape[0])
                if str(
                    frame.iat[i, 1]
                ).strip().upper() == code
            ]

            if len(hits) != 1:
                raise ValueError(
                    f"GFS {year}: строка {code}: "
                    f"{len(hits)} совпадений"
                )

            return hits[0]

        nlb_row = code_row(ops, "NLB")
        debt_row = code_row(bal, "63")

        for q in range(1, 5):
            if (year, q) > (2026, 2):
                continue

            key = f"{year}Q{q}"

            a = pd.to_numeric(
                ops.iat[nlb_row, q + 3],
                errors="coerce",
            )

            b = pd.to_numeric(
                bal.iat[debt_row, q + 3],
                errors="coerce",
            )

            if pd.notna(a):
                nlb[key] = float(a)

            if pd.notna(b):
                debt[key] = float(b)

    return nlb, debt


def _ru_current_account():
    frame = _ru_excel(
        RU_BOP_URL,
        "Кварталы",
    )

    if (
        str(frame.iat[5, 0]).strip()
        != "Счет текущих операций"
    ):
        raise ValueError(
            "ЦБ РФ: изменилась строка текущего счёта"
        )

    result = {}

    for col in range(1, frame.shape[1]):
        title = str(frame.iat[4, col])

        match = re.search(
            r"([1-4])\s*квартал\s*(20\d{2})",
            title,
            re.IGNORECASE,
        )

        if not match:
            continue

        quarter = int(match.group(1))
        year = int(match.group(2))

        if (
            (year, quarter) < (2024, 1)
            or (year, quarter) > (2026, 2)
        ):
            continue

        amount = pd.to_numeric(
            frame.iat[5, col],
            errors="coerce",
        )

        if pd.notna(amount):
            # Значения ЦБ указаны в млн USD.
            result[f"{year}Q{quarter}"] = float(
                amount
            )

    return result


def _ru_fx_quarterly():
    payload = {
        "date_req1": "20/12/2023",
        "date_req2": "30/06/2026",
        "VAL_NM_RQ": "R01235",
    }

    root = ET.fromstring(
        _ru_download(
            RU_FX_URL,
            payload,
        )
    )

    entries = []

    for record in root.findall("Record"):
        dt = pd.to_datetime(
            record.attrib["Date"],
            format="%d.%m.%Y",
        )

        nominal = float(
            record.findtext("Nominal").replace(
                ",", "."
            )
        )

        value = float(
            record.findtext("Value").replace(
                ",", "."
            )
        )

        entries.append(
            (dt, value / nominal)
        )

    if not entries:
        raise ValueError(
            "Не получен ряд USD/RUB Банка России"
        )

    rates = pd.Series(
        dict(entries),
        dtype="float64",
    ).sort_index()

    days = pd.date_range(
        "2024-01-01",
        "2026-06-30",
        freq="D",
    )

    daily = (
        rates.reindex(
            rates.index.union(days)
        )
        .sort_index()
        .ffill()
        .reindex(days)
    )

    if daily.isna().any():
        raise ValueError(
            "В ежедневном курсе ЦБ есть пропуски"
        )

    return (
        daily.groupby(
            days.to_period("Q").astype(str)
        )
        .mean()
        .to_dict()
    )


def fetch_russia_quarterly():
    """
    Квартальные показатели России.

    debt_gdp:
        GFS broad debt, строка 63,
        делённая на ВВП последних четырёх кварталов.

    budget_gdp:
        General Government Net Lending/Borrowing
        за квартал / квартальный ВВП.

    trade_gdp:
        Current Account, млн USD,
        пересчитанный в рубли по среднему курсу,
        делённый на квартальный ВВП.

    gdp_growth:
        Индекс физического объёма ВВП Росстата
        к соответствующему кварталу прошлого года
        минус 100.

    unemployment:
        Готовое квартальное значение Росстата.
    """

    # --------------------------------------------------------
    # Финансовые данные
    # --------------------------------------------------------

    gdp = _ru_nominal_gdp()
    nlb, debt = _ru_gfs_data()
    current_account = _ru_current_account()
    fx = _ru_fx_quarterly()

    results = []

    for period in pd.period_range(
        "2024Q1",
        "2026Q2",
        freq="Q",
    ):
        key = str(period)

        g = gdp.get(key)
        quarterly_nlb = nlb.get(key)
        debt_stock = debt.get(key)
        ca_usd_mn = current_account.get(key)
        fx_rate = fx.get(key)

        previous_four = [
            gdp.get(str(period - lag))
            for lag in (0, 1, 2, 3)
        ]

        ttm_gdp = (
            sum(previous_four)
            if all(
                value is not None
                for value in previous_four
            )
            else None
        )

        debt_gdp = None
        budget_gdp = None
        trade_gdp = None

        if (
            debt_stock is not None
            and ttm_gdp is not None
            and ttm_gdp > 0
        ):
            debt_gdp = (
                debt_stock / ttm_gdp * 100
            )

        if (
            quarterly_nlb is not None
            and g is not None
            and g > 0
        ):
            budget_gdp = (
                quarterly_nlb / g * 100
            )

        if (
            ca_usd_mn is not None
            and fx_rate is not None
            and g is not None
            and g > 0
        ):
            trade_gdp = (
                ca_usd_mn * fx_rate
                / (10 * g)
            )

        results.append({
            "date": period.end_time.normalize(),
            "country": "RU",
            "debt_gdp": debt_gdp,
            "budget_gdp": budget_gdp,
            "trade_gdp": trade_gdp,
        })

    result = pd.DataFrame(results)

    for col in (
        "debt_gdp",
        "budget_gdp",
        "trade_gdp",
    ):
        if result[col].isna().any():
            raise ValueError(
                f"RU {col}: есть пропущенные кварталы"
            )

    print(
        "[RU] Финансовые показатели:",
        len(result),
        "кварталов",
    )

    # --------------------------------------------------------
    # Годовые финансовые показатели
    # --------------------------------------------------------

    for column in (
        "annual_debt_gdp",
        "annual_budget_gdp",
        "annual_trade_gdp",
    ):
        result[column] = float("nan")

    for year in (2024, 2025):
        keys = [
            f"{year}Q{q}"
            for q in range(1, 5)
        ]

        required = (
            [gdp.get(k) for k in keys]
            + [nlb.get(k) for k in keys]
            + [current_account.get(k) for k in keys]
            + [fx.get(k) for k in keys]
            + [debt.get(f"{year}Q4")]
        )

        if any(x is None for x in required):
            raise ValueError(
                f"RU {year}: неполные годовые данные"
            )

        annual_gdp = sum(gdp[k] for k in keys)
        annual_budget = sum(nlb[k] for k in keys)

        annual_ca_rub_bln = sum(
            current_account[k] * fx[k] / 1000
            for k in keys
        )

        if annual_gdp <= 0:
            raise ValueError(
                f"RU {year}: ВВП должен быть положительным"
            )

        mask = (
            result["date"]
            == pd.Timestamp(year, 12, 31)
        )

        if mask.sum() != 1:
            raise ValueError(
                f"RU {year}: строка Q4 не найдена"
            )

        result.loc[
            mask, "annual_debt_gdp"
        ] = (
            debt[f"{year}Q4"] / annual_gdp * 100
        )

        result.loc[
            mask, "annual_budget_gdp"
        ] = (
            annual_budget / annual_gdp * 100
        )

        result.loc[
            mask, "annual_trade_gdp"
        ] = (
            annual_ca_rub_bln / annual_gdp * 100
        )

    print("[RU] Годовые показатели: 2024, 2025")

    # --------------------------------------------------------
    # Рост ВВП YoY — Росстат
    # --------------------------------------------------------

    # Единственное разрешённое исключение:
    # официальный индекс физического объёма минус 100.

    gdp_frame = _ru_excel(
        RU_GDP_URL,
        "12",
    )

    gdp_growth = {}
    source_year = None

    quarter_numbers = {
        "I": 1,
        "II": 2,
        "III": 3,
        "IV": 4,
    }

    for col in range(gdp_frame.shape[1]):
        match_year = re.search(
            r"20\d{2}",
            str(gdp_frame.iat[2, col]),
        )

        if match_year:
            source_year = int(
                match_year.group()
            )

        if source_year is None or source_year < 2024:
            continue

        match_quarter = re.search(
            r"\b(IV|III|II|I)\s+квартал",
            str(gdp_frame.iat[3, col]),
            re.I,
        )

        if not match_quarter:
            continue

        index = pd.to_numeric(
            gdp_frame.iat[4, col],
            errors="coerce",
        )

        if pd.notna(index):
            quarter = quarter_numbers[
                match_quarter.group(1).upper()
            ]

            gdp_growth[
                f"{source_year}Q{quarter}"
            ] = float(index) - 100.0

    # --------------------------------------------------------
    # Безработица — Росстат
    # --------------------------------------------------------

    unemployment_url = (
        "https://rosstat.gov.ru/storage/mediabank/"
        "Trud-3_15-s.xlsx"
    )

    unemployment_frame = _ru_excel(
        unemployment_url,
        "4",
    )

    unemployment = {}

    quarter_names = {
        "январь - март": 1,
        "апрель - июнь": 2,
        "июль - сентябрь": 3,
        "октябрь - декабрь": 4,
        "октябрь-декабрь": 4,
    }

    if "Российская Федерация" not in str(
        unemployment_frame.iat[5, 0]
    ):
        raise ValueError(
            "Росстат: изменилась строка России "
            "в таблице безработицы"
        )

    for col in range(
        1,
        unemployment_frame.shape[1],
    ):
        header = (
            str(unemployment_frame.iat[4, col])
            .lower()
            .replace("–", "-")
            .replace("—", "-")
        )

        match_year = re.search(
            r"20\d{2}",
            header,
        )

        if not match_year:
            continue

        source_year = int(
            match_year.group()
        )

        if source_year < 2024:
            continue

        for name, quarter in quarter_names.items():
            if name not in header:
                continue

            value = pd.to_numeric(
                unemployment_frame.iat[5, col],
                errors="coerce",
            )

            if pd.notna(value):
                unemployment[
                    f"{source_year}Q{quarter}"
                ] = float(value)

            break

    # --------------------------------------------------------
    # Добавляем два показателя к квартальной таблице
    # --------------------------------------------------------

    for column in (
        "gdp_growth",
        "unemployment",
    ):
        result[column] = float("nan")

    for idx, date in result["date"].items():
        key = str(
            pd.Period(date, freq="Q")
        )

        if key in gdp_growth:
            result.at[
                idx, "gdp_growth"
            ] = gdp_growth[key]

        if key in unemployment:
            result.at[
                idx, "unemployment"
            ] = unemployment[key]

    # Проверка полноты данных.
    for column in (
        "gdp_growth",
        "unemployment",
    ):
        if result[column].isna().any():
            missing = (
                result.loc[
                    result[column].isna(),
                    "date",
                ]
                .dt.to_period("Q")
                .astype(str)
                .tolist()
            )

            raise ValueError(
                f"RU {column}: "
                f"отсутствуют кварталы {missing}"
            )

    print(
        "[RU] ВВП YoY и безработица:",
        len(result),
        "кварталов",
    )



    # ========================================================
    # Годовой ВВП YoY и годовая безработица Росстата
    # ========================================================

    annual_gdp_url = (
        "https://rosstat.gov.ru/storage/mediabank/"
        "VVP_god_s1995-2025.xlsx"
    )

    annual_gdp_frame = _ru_excel(
        annual_gdp_url, "8"
    )

    annual_unemployment_frame = _ru_excel(
        "https://rosstat.gov.ru/storage/mediabank/"
        "Trud-3_15-s.xlsx",
        "2",
    )

    annual_gdp_growth = {}
    annual_unemployment = {}

    # Лист 8: строка 2 — годы,
    # строка 3 — официальный индекс ВВП.
    for col in range(annual_gdp_frame.shape[1]):
        match = re.search(
            r"20\d{2}",
            str(annual_gdp_frame.iat[2, col]),
        )

        if not match:
            continue

        year = int(match.group())

        if year < 2024:
            continue

        index = pd.to_numeric(
            annual_gdp_frame.iat[3, col],
            errors="coerce",
        )

        if pd.notna(index):
            # Разрешённое преобразование индекса
            # физического объёма ВВП в рост YoY.
            annual_gdp_growth[year] = (
                float(index) - 100.0
            )

    # Лист 2: строка 4 — годы,
    # строка 5 — Российская Федерация.
    if "Российская Федерация" not in str(
        annual_unemployment_frame.iat[5, 0]
    ):
        raise ValueError(
            "RU annual unemployment: "
            "не найдена строка России"
        )

    for col in range(
        1, annual_unemployment_frame.shape[1]
    ):
        match = re.search(
            r"20\d{2}",
            str(annual_unemployment_frame.iat[4, col]),
        )

        if not match:
            continue

        year = int(match.group())

        if year < 2024:
            continue

        value = pd.to_numeric(
            annual_unemployment_frame.iat[5, col],
            errors="coerce",
        )

        if pd.notna(value):
            annual_unemployment[year] = float(value)

    result["annual_gdp_growth"] = float("nan")
    result["annual_unemployment"] = float("nan")

    # Записываем годовые показатели
    # в строку окончания соответствующего года.
    for year in (2024, 2025):
        if year not in annual_gdp_growth:
            raise ValueError(
                f"RU {year}: нет годового роста ВВП"
            )

        if year not in annual_unemployment:
            raise ValueError(
                f"RU {year}: нет годовой безработицы"
            )

        mask = (
            result["date"]
            == pd.Timestamp(year, 12, 31)
        )

        if mask.sum() != 1:
            raise ValueError(
                f"RU {year}: не найдена строка Q4"
            )

        result.loc[
            mask, "annual_gdp_growth"
        ] = annual_gdp_growth[year]

        result.loc[
            mask, "annual_unemployment"
        ] = annual_unemployment[year]

    print(
        "[RU] Годовой ВВП и безработица:",
        sorted(annual_gdp_growth.keys()),
    )

    return result


# ============================================================
# Ручной запуск модуля
# ============================================================

if __name__ == "__main__":
    data = fetch_russia_cpi()

    print("\nВСЯ ИСТОРИЯ CPI:")
    print(
        data[
            ["date", "value", "mom", "core"]
        ].to_string(index=False)
    )

    print("\nПОКРЫТИЕ CPI:")

    for column in (
        "value",
        "mom",
        "core",
    ):
        print(
            column,
            data[column].notna().sum(),
            "/",
            len(data),
        )

    quarterly = fetch_russia_quarterly()

    print("\nКВАРТАЛЬНЫЕ ПОКАЗАТЕЛИ:")
    print(
        quarterly.to_string(
            index=False,
        )
    )

    print("\nПОКРЫТИЕ:")

    for column in (
        "debt_gdp",
        "budget_gdp",
        "trade_gdp",
        "gdp_growth",
        "unemployment",
    ):
        print(
            column,
            quarterly[column].notna().sum(),
            "/",
            len(quarterly),
        )
