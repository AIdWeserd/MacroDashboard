
"""Official Russian industrial producer price index (PPI) from Rosstat.

Run:
  python -m src.ppi_russia --dry-run --verbose
  python -m src.ppi_russia --save

Only published official month-on-month/year-on-year index numbers are used.
Index 102.5 corresponds to +2.5%. 2020 YoY is not fabricated.
TLS transport reuses the project's documented temporary exception in
src.fetch_russia; responsibility for replacing it belongs to the TLS audit.
"""
from __future__ import annotations

import argparse
import math
import posixpath
import re
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import pandas as pd
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from src.fetch_russia import _ru_download
from src.eurostat_extra import save_eurostat_extra

PAGE_URL = "https://rosstat.gov.ru/statistics/price"
WORKBOOK_TITLE = (
    "Индексы цен производителей по видам "
    "экономической деятельности с 1998 г."
)

START_MONTH = pd.Period("2020-01", freq="M")
CONTROL_MONTH = pd.Period("2026-09", freq="M")
CONTROL_INDICES = {
    "ppi_mom": 102.5,
    "ppi_yoy": 108.6,
}

OFFICIAL_CODE = "1323500.029.31"

MAX_HTML = 5_000_000
MAX_EXCEL = 25_000_000
MAX_XML_ROWS = 12_000

SOURCE = (
    "Росстат: индексы цен производителей промышленных товаров "
    "(внутренний рынок); опубликованный индекс минус 100"
)

COLUMNS = (
    "country", "date", "metric", "value",
    "source", "unit", "adjustment",
)

MONTHS = {
    name: i
    for i, name in enumerate(
        (
            "январь", "февраль", "март", "апрель",
            "май", "июнь", "июль", "август",
            "сентябрь", "октябрь", "ноябрь", "декабрь",
        ),
        1,
    )
}

NS_SHEET = (
    "http://schemas.openxmlformats.org/"
    "spreadsheetml/2006/main"
)
NS_DOC_REL = (
    "http://schemas.openxmlformats.org/"
    "officeDocument/2006/relationships"
)
NS_PACKAGE_REL = (
    "http://schemas.openxmlformats.org/"
    "package/2006/relationships"
)


def _normalize(value):
    if value is None:
        return ""

    return " ".join(
        str(value)
        .replace("ё", "е")
        .replace("Ё", "Е")
        .replace("\xa0", " ")
        .lower()
        .split()
    )


def _is_aggregate(name, code):
    label = _normalize(name)
    code = str(code).strip() if code is not None else ""

    return (
        code == OFFICIAL_CODE
        and "промышленность" in label
        and "собирательная классификационная группировка"
        in label
    )


def _number(value, where):
    if isinstance(value, bool) or value is None:
        raise ValueError(
            f"{where}: missing official index"
        )

    text = str(value).strip().replace(" ", "")

    # Rosstat sometimes appends footnote 1) directly:
    # 98,121) = 98,12 with footnote 1).
    footnote = re.fullmatch(
        r"(\d+[.,]\d{1,2})1\)",
        text,
    )

    if footnote:
        text = footnote.group(1)

    try:
        result = float(text.replace(",", "."))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"{where}: invalid index {value!r}"
        ) from exc

    if not math.isfinite(result) or not 5 < result < 400:
        raise ValueError(
            f"{where}: index out of bounds: {result}"
        )

    return result


def _month_number(value):
    name = re.sub(
        r"\d+\s*\)?",
        "",
        _normalize(value),
    ).strip(" .)")

    return MONTHS.get(name)


def _validate_url(url):
    parts = urlsplit(url)

    if (
        parts.scheme != "https"
        or parts.hostname not in {
            "rosstat.gov.ru",
            "www.rosstat.gov.ru",
        }
        or parts.username
        or parts.password
    ):
        raise ValueError(
            f"Non-official Rosstat URL: {url}"
        )

    return url


def discover_xlsx(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    for link in soup.find_all("a", href=True):
        url = urljoin(PAGE_URL, link["href"])

        try:
            _validate_url(url)
        except ValueError:
            continue

        if not urlsplit(url).path.lower().endswith(".xlsx"):
            continue

        contexts = [
            link.get_text(" ", strip=True)
        ]

        parent = link.parent

        for _ in range(3):
            if parent is None:
                break

            contexts.append(
                parent.get_text(
                    " ", strip=True
                )[:1400]
            )
            parent = parent.parent

        score = 0
        title = _normalize(WORKBOOK_TITLE)

        for depth, context in enumerate(contexts):
            text = _normalize(context)

            if title in text:
                score = max(
                    score, 100 - 20 * depth
                )
            elif (
                "индексы цен производителей по видам "
                "экономической деятельности" in text
                and "1998" in text
            ):
                score = max(
                    score, 80 - 20 * depth
                )

        if score >= 30:
            matches.append((score, url))

    if not matches:
        raise ValueError(
            "Official Rosstat historic PPI "
            "workbook link not found"
        )

    best_score = max(
        score for score, _ in matches
    )

    urls = {
        url
        for score, url in matches
        if score == best_score
    }

    if len(urls) != 1:
        raise ValueError(
            f"Ambiguous historic PPI links: {sorted(urls)}"
        )

    return urls.pop()


def _fetch_bytes(url, limit):
    _validate_url(url)

    # Existing documented temporary Rosstat TLS exception.
    # The backend security task will replace this transport.
    content = _ru_download(url)

    if (
        not isinstance(content, bytes)
        or len(content) > limit
    ):
        raise ValueError(
            "Rosstat returned invalid or oversized content"
        )

    return content


def _read_months(row, header, year, metric, label):
    months = {}

    for column in range(3, 15):
        month = _month_number(
            header[column - 1]
            if column <= len(header)
            else None
        )

        if month is None:
            continue

        if (
            column > len(row)
            or row[column - 1] is None
        ):
            continue

        period = pd.Period(
            f"{year}-{month:02d}",
            freq="M",
        )

        months[period] = _number(
            row[column - 1],
            f"{label}/{period}/{metric}",
        )

    return months


def _read_2020(wb):
    ws = wb["2.1"]

    if "промышленность" not in _normalize(
        ws.cell(1, 2).value
    ):
        raise ValueError(
            "2.1: incorrect aggregate title"
        )

    years = {}

    for col in range(
        2,
        min(ws.max_column, 30) + 1,
    ):
        match = re.search(
            r"\b20\d\d\b",
            str(ws.cell(3, col).value),
        )

        if match:
            years[int(match.group())] = col

    if 2020 not in years:
        raise ValueError(
            "2.1: 2020 column absent"
        )

    col = years[2020]
    result = {}

    for row in range(5, 17):
        month = _month_number(
            ws.cell(row, 1).value
        )

        if month is None:
            raise ValueError(
                f"2.1: invalid month in row {row}"
            )

        period = pd.Period(
            f"2020-{month:02d}",
            freq="M",
        )

        result[period] = _number(
            ws.cell(row, col).value,
            f"2.1/{period}",
        )

    if len(result) != 12:
        raise ValueError(
            "2.1: incomplete 2020"
        )

    return result


def _read_small_year(wb, year, metric):
    section = year - 2018
    suffix = "1" if metric == "ppi_mom" else "3"
    name = f"{section}.{suffix}"

    ws = wb[name]

    header = tuple(
        ws.iter_rows(
            min_row=3,
            max_row=3,
            max_col=14,
            values_only=True,
        )
    )[0]

    aggregate = tuple(
        ws.iter_rows(
            min_row=10,
            max_row=10,
            max_col=14,
            values_only=True,
        )
    )[0]

    if not _is_aggregate(
        aggregate[0],
        aggregate[1],
    ):
        raise ValueError(
            f"{name}: row 10 is not the industry aggregate"
        )

    title = _normalize(
        ws.cell(1, 1).value
    )

    if not re.search(
        rf"\b{year}\s*г",
        title,
    ):
        raise ValueError(
            f"{name}: wrong calendar year in heading"
        )

    indices = _read_months(
        aggregate,
        header,
        year,
        metric,
        name,
    )

    if len(indices) != 12:
        raise ValueError(
            f"{name}: expected 12 official months, "
            f"found {len(indices)}"
        )

    return indices


def _xml_sheet_paths(zf):
    main = ET.fromstring(
        zf.read("xl/workbook.xml")
    )

    rels_root = ET.fromstring(
        zf.read(
            "xl/_rels/workbook.xml.rels"
        )
    )

    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall(
            f"{{{NS_PACKAGE_REL}}}Relationship"
        )
    }

    found = {}

    for node in main.findall(
        f".//{{{NS_SHEET}}}sheet"
    ):
        rid = node.attrib[
            f"{{{NS_DOC_REL}}}id"
        ]

        target = rels[rid]

        name = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(
                posixpath.join("xl", target)
            )
        )

        if (
            name not in zf.namelist()
            or not name.startswith(
                "xl/worksheets/"
            )
        ):
            raise ValueError(
                f"Invalid worksheet reference: {name}"
            )

        found[node.attrib["name"]] = name

    return found


def _shared_strings(zf):
    """Read shared strings without scanning large worksheets."""

    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    strings = []

    with zf.open("xl/sharedStrings.xml") as stream:
        for _, elem in ET.iterparse(
            stream,
            events=("end",),
        ):
            if elem.tag == f"{{{NS_SHEET}}}si":
                strings.append(
                    "".join(
                        t.text or ""
                        for t in elem.iter(
                            f"{{{NS_SHEET}}}t"
                        )
                    )
                )

                elem.clear()

    return strings


def _xlsx_xml_row(elem, shared):
    values = {}

    for cell in elem.findall(
        f"{{{NS_SHEET}}}c"
    ):
        address = cell.get("r", "")

        letter = re.match(
            r"[A-Z]+",
            address,
        )

        if not letter:
            continue

        col = letter.group(0)
        kind = cell.get("t", "")

        if kind == "inlineStr":
            value = "".join(
                t.text or ""
                for t in cell.iter(
                    f"{{{NS_SHEET}}}t"
                )
            )
        else:
            element = cell.find(
                f"{{{NS_SHEET}}}v"
            )

            value = (
                element.text
                if element is not None
                else None
            )

            if kind == "s" and value is not None:
                value = shared[int(value)]

        values[col] = value

    return values


def _read_large_year(
    zf,
    paths,
    shared,
    year,
    metric,
    verbose=False,
):
    prefix = "7" if year == 2025 else "8"

    name = (
        f"{prefix}."
        f"{'1' if metric == 'ppi_mom' else '3'}"
    )

    if name not in paths:
        raise ValueError(
            f"Missing official worksheet {name}"
        )

    print(
        f"[ROSSTAT] {name}: locating exact "
        "industry group and national row",
        flush=True,
    )

    group_seen = False
    waiting = 0
    result = None
    header = None

    with zf.open(paths[name]) as stream:
        for _, elem in ET.iterparse(
            stream,
            events=("end",),
        ):
            if elem.tag != f"{{{NS_SHEET}}}row":
                continue

            row_num = int(
                elem.attrib.get("r", "0")
            )

            if row_num > MAX_XML_ROWS:
                raise ValueError(
                    f"{name}: row cap exceeded"
                )

            row = _xlsx_xml_row(
                elem,
                shared,
            )

            elem.clear()

            if row_num == 1:
                title = _normalize(
                    row.get("A")
                )

                if not re.search(
                    rf"\b{year}\s*г",
                    title,
                ):
                    raise ValueError(
                        f"{name}: wrong year in title: "
                        f"{title[:180]}"
                    )

            elif row_num == 3:
                header = row

            if _is_aggregate(
                row.get("A"),
                row.get("B"),
            ):
                if group_seen:
                    raise ValueError(
                        f"{name}: duplicate industry aggregate"
                    )

                group_seen = True
                waiting = 4

                if verbose:
                    print(
                        f"[ROSSTAT] {name}: "
                        f"industry group row={row_num}"
                    )

                continue

            if waiting:
                if (
                    _normalize(row.get("A"))
                    == "российская федерация"
                ):
                    if header is None:
                        raise ValueError(
                            f"{name}: month header absent"
                        )

                    months = {}

                    for index, _ in enumerate(
                        MONTHS,
                        3,
                    ):
                        col = chr(
                            ord("A") + index - 1
                        )

                        heading = header.get(col)

                        if heading is None:
                            continue

                        month = _month_number(
                            heading
                        )

                        if (
                            month is None
                            or month != index - 2
                        ):
                            raise ValueError(
                                f"{name}: unexpected month "
                                f"in {col}: {heading!r}"
                            )

                        value = row.get(col)

                        if value is not None:
                            period = pd.Period(
                                f"{year}-{month:02d}",
                                freq="M",
                            )

                            months[period] = _number(
                                value,
                                f"{name}/{period}/{metric}",
                            )

                    result = months
                    break

                if row.get("A") is not None:
                    waiting -= 1

                if waiting == 0:
                    raise ValueError(
                        f"{name}: Russian Federation "
                        "row not found after aggregate"
                    )

    if not group_seen:
        raise ValueError(
            f"{name}: official industry aggregate "
            f"with code {OFFICIAL_CODE} absent"
        )

    if not result:
        raise ValueError(
            f"{name}: Russian Federation row "
            "has no indices"
        )

    needed = 12 if year == 2025 else 9

    if len(result) < needed:
        raise ValueError(
            f"{name}: too few months: {len(result)} "
            f"(minimum {needed})"
        )

    expected = set(
        pd.period_range(
            f"{year}-01",
            max(result),
            freq="M",
        )
    )

    if set(result) != expected:
        raise ValueError(
            f"{name}: missing interior months"
        )

    print(
        f"[ROSSTAT] {name}: aggregate confirmed, "
        f"{len(result)} months",
        flush=True,
    )

    return result


def parse_russia_ppi(blob, verbose=False):
    if (
        len(blob) > MAX_EXCEL
        or not zipfile.is_zipfile(
            BytesIO(blob)
        )
    ):
        raise ValueError(
            "Official XLSX missing or invalid"
        )

    result = {
        "ppi_mom": {},
        "ppi_yoy": {},
    }

    wb = load_workbook(
        BytesIO(blob),
        read_only=True,
        data_only=True,
        keep_links=False,
    )

    try:
        result["ppi_mom"].update(
            _read_2020(wb)
        )

        for year in range(2021, 2025):
            for metric in result:
                result[metric].update(
                    _read_small_year(
                        wb,
                        year,
                        metric,
                    )
                )

    finally:
        wb.close()

    with zipfile.ZipFile(
        BytesIO(blob)
    ) as zf:
        paths = _xml_sheet_paths(zf)
        shared = _shared_strings(zf)

        for year in (2025, 2026):
            for metric in result:
                result[metric].update(
                    _read_large_year(
                        zf,
                        paths,
                        shared,
                        year,
                        metric,
                        verbose=verbose,
                    )
                )

    latest = None

    for metric, series in result.items():
        if not series:
            raise ValueError(
                f"No {metric} data"
            )

        expected_start = (
            "2020-01"
            if metric == "ppi_mom"
            else "2021-01"
        )

        end = max(series)

        if end < CONTROL_MONTH:
            raise ValueError(
                f"{metric}: official archive older "
                "than September 2026"
            )

        expected = set(
            pd.period_range(
                expected_start,
                end,
                freq="M",
            )
        )

        missing = sorted(
            expected - set(series)
        )

        if missing:
            raise ValueError(
                f"{metric}: missing months {missing[:8]}"
            )

        if latest is None:
            latest = end
        elif latest != end:
            raise ValueError(
                f"PPI MoM/YoY end at different "
                f"months: {latest}/{end}"
            )

        control_value = series[CONTROL_MONTH]

        if (
            end == CONTROL_MONTH
            and abs(
                control_value
                - CONTROL_INDICES[metric]
            ) > 0.051
        ):
            raise ValueError(
                f"{metric} 2026-09: expected index "
                f"{CONTROL_INDICES[metric]}, "
                f"got {control_value}"
            )

        if verbose:
            print(
                f"[ROSSTAT] {metric}: "
                f"first={min(series)}, "
                f"last={end}, "
                f"index={series[end]}"
            )

    records = []

    for metric, series in result.items():
        for period, idx in sorted(
            series.items()
        ):
            records.append(
                (
                    "RU",
                    period.start_time,
                    metric,
                    round(idx - 100.0, 3),
                    SOURCE,
                    "%",
                    "NSA; published Rosstat index (-100 p.p.)",
                )
            )

    df = pd.DataFrame.from_records(
        records,
        columns=COLUMNS,
    )

    if df.duplicated(
        ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "Duplicate PPI measurements"
        )

    return (
        df.sort_values(
            ["date", "metric"]
        )
        .reset_index(drop=True)
    )


def fetch_russia_ppi(xlsx=None, verbose=False):
    if xlsx:
        path = Path(xlsx)

        if path.suffix.lower() != ".xlsx":
            raise ValueError(
                "Expected local Rosstat XLSX"
            )

        blob = path.read_bytes()

        print(
            f"[ROSSTAT] Local archive: {path}"
        )

    else:
        print(
            f"[ROSSTAT] Landing page: {PAGE_URL}"
        )

        html = _fetch_bytes(
            PAGE_URL,
            MAX_HTML,
        )

        url = discover_xlsx(html)

        print(
            f"[ROSSTAT] GET: {url}"
        )

        blob = _fetch_bytes(
            url,
            MAX_EXCEL,
        )

    print(
        f"[ROSSTAT] XLSX bytes: {len(blob)}",
        flush=True,
    )

    return parse_russia_ppi(
        blob,
        verbose=verbose,
    )


def run(dry_run=True, xlsx=None, verbose=False):
    try:
        df = fetch_russia_ppi(
            xlsx=xlsx,
            verbose=verbose,
        )

        for metric in (
            "ppi_mom",
            "ppi_yoy",
        ):
            group = df.loc[
                df["metric"] == metric
            ]

            first = group.iloc[0]
            last = group.iloc[-1]

            print(
                f"[PASS] RU/{metric}: "
                f"n={len(group)}, "
                f"{first['date']:%Y-%m}.."
                f"{last['date']:%Y-%m}, "
                f"latest={last['value']:+.1f}%"
            )

        if dry_run:
            print(
                "[READ-ONLY] SQLite unchanged"
            )
        else:
            save_eurostat_extra(df)

        return 0

    except Exception as exc:
        print(
            f"[FAIL] Russia PPI: "
            f"{type(exc).__name__}: {exc}"
        )

        print(
            "[READ-ONLY] No database writes "
            "if validation failed"
        )

        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Official Russian Rosstat PPI"
    )

    actions = parser.add_mutually_exclusive_group()

    actions.add_argument(
        "--dry-run",
        action="store_true",
        help="validate only (default)",
    )

    actions.add_argument(
        "--save",
        action="store_true",
        help="save after validation",
    )

    parser.add_argument(
        "--xlsx",
        help="local official XLSX, optional",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
    )

    args = parser.parse_args()

    raise SystemExit(
        run(
            dry_run=not args.save,
            xlsx=args.xlsx,
            verbose=args.verbose,
        )
    )
