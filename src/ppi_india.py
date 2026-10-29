"""India: official monthly Output Producer Price Index (OPPI), all commodities.

Publisher: Office of the Economic Adviser, DPIIT (Government of India).
Data: OPPI, base 2022-23=100, historical monthly levels from 2023-04.
       This is NOT wholesale price index (WPI) and NOT trial input PPI.

Usage from project root:
    python -m src.ppi_india --dry-run
    python -m src.ppi_india
    python -m src.ppi_india --xlsx "C:\\path\\downloaded_official_OPPI.xlsx" --dry-run

The public OEA download page may change its HTML layout. On unknown layouts
this module deliberately refuses to save anything and prints diagnostics.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
import re
import ssl
import sys
import time
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup
import pandas as pd
import requests
from openpyxl import load_workbook

from src.eurostat_extra import save_eurostat_extra

INDEX_PAGE = "https://eaindustry.nic.in/download_data_2223.asp"
PUBLISHER = "OEA/DPIIT India"
START = pd.Period("2023-04", freq="M")
MIN_LAST = pd.Period("2026-09", freq="M")
COLS = ["country", "date", "metric", "value", "source", "unit", "adjustment"]
SOURCE = ("OEA/DPIIT India, Output PPI All Commodities (2022-23=100); "
          "MoM/YoY calculated from official rounded monthly OPPI levels; not WPI")
HEADERS = {"User-Agent": "MacroDashboard/1.0 (official OEA statistics)",
           "Accept": "text/html,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,*/*"}
MAX_FILE_BYTES = 32_000_000
MON_ABBR = {m.lower(): i for i, m in enumerate((
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"), 1)}
MON_ABBR.update({m[:3]: i for m, i in MON_ABBR.items()})
FINALIZED_CONTROL = {
    "2026-06": 110.0,
    "2026-07": 109.9,
}
PROVISIONAL_CONTROL = {
    "2026-08": 110.8,
    "2026-09": 112.5,
}
MONTHLY_CONTROL = {
    "2026-06": 110.0,
    "2026-07": 109.9,
    "2026-08": 110.8,
    "2026-09": 112.5,
}


def _norm(obj: object) -> str:
    return re.sub(r"\s+", " ", str(obj or "").strip()).casefold()


def _is_aggregate(obj: object) -> bool:
    s = re.sub(r"[^a-z0-9]+", " ", _norm(obj)).strip()
    return bool(re.fullmatch(r"(?:(?:[ivx]+|\d+) )?all commodit(?:y|ies)", s))


def _month(obj: object) -> pd.Period | None:
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return pd.Period(obj, freq="M")
    if not isinstance(obj, str):
        return None
    s = re.sub(r"\s+", " ", obj.strip().replace("'", ""))
    for p in (r"^(20\d{2})[-/]([01]?\d)(?:[-/]\d{1,2})?$", r"^([01]?\d)[-/](20\d{2})$"):
        m = re.fullmatch(p, s)
        if m:
            a, b = map(int, m.groups())
            yr, mo = (a, b) if a >= 2000 else (b, a)
            if 1 <= mo <= 12:
                return pd.Period(f"{yr}-{mo:02d}", freq="M")
    m = re.fullmatch(r"(?i)([a-z]{3,9})[- /.]+(20\d{2}|\d{2})", s)
    if m:
        mon = MON_ABBR.get(m.group(1).lower()) or MON_ABBR.get(m.group(1).lower()[:3])
        y = int(m.group(2))
        if y < 100: y += 2000
        if mon:
            return pd.Period(f"{y}-{mon:02d}", freq="M")
    m = re.fullmatch(r"(?i)(20\d{2}|\d{2})[- /.]+([a-z]{3,9})", s)
    if m:
        y = int(m.group(1))
        if y < 100: y += 2000
        mon = MON_ABBR.get(m.group(2).lower()) or MON_ABBR.get(m.group(2).lower()[:3])
        if mon:
            return pd.Period(f"{y}-{mon:02d}", freq="M")
    return None


def _level(obj: object) -> Decimal | None:
    if obj is None or isinstance(obj, bool):
        return None
    try:
        s = str(obj).strip().replace(",", "")
        if s in ("", "-", "..", "NA", "NR", "N/A", "None"):
            return None
        x = Decimal(s)
        return x if x.is_finite() and Decimal(30) < x < Decimal(400) else None
    except ArithmeticError:
        return None


def _ensure_official_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname not in ("eaindustry.nic.in", "www.eaindustry.nic.in"):
        raise ValueError(f"OEA: refusing external/non-HTTPS URL: {p.hostname}")
    return url


class _OfficialRedirect(urlrequest.HTTPRedirectHandler):
    """Do not send OEA requests to non-government or unverified HTTP hosts."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ensure_official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get_windows_verified(url: str, context: ssl.SSLContext) -> bytes:
    """Use verified HTTPS with a specific CA context; no verify=False."""
    _ensure_official_url(url)
    opener = urlrequest.build_opener(
        _OfficialRedirect(), urlrequest.HTTPSHandler(context=context)
    )
    request = urlrequest.Request(url, headers=HEADERS)
    with opener.open(request, timeout=70) as response:
        _ensure_official_url(response.geturl())
        payload = bytearray()
        while True:
            block = response.read(131072)
            if not block:
                break
            payload.extend(block)
            if len(payload) > MAX_FILE_BYTES:
                raise ValueError("OEA: download exceeds safe size")
        return bytes(payload)


def _is_cert_issue(exc: BaseException) -> bool:
    """Different HTTPS clients wrap certificate-validation errors differently."""
    message = str(exc).casefold()
    return ("certificate_verify_failed" in message
            or "certificate verify failed" in message
            or "unable to get local issuer" in message)


def _get_after_cert_failure(url: str, initial_error: BaseException) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError(
            "OEA TLS: Python could not verify the official server certificate. "
            "Use a trusted CA chain or download the official Excel in a browser "
            "and run --xlsx <file>. HTTPS verification remains enabled."
        ) from initial_error

    # Python on Windows can use the OS ROOT/CA stores instead of Requests' certifi.
    print("[OEA/TLS] Trying Windows trusted CA store (verification enabled)")
    try:
        return _get_windows_verified(url, ssl.create_default_context())
    except (OSError, ssl.SSLError) as exc:
        if not _is_cert_issue(exc):
            raise

    # Native Windows Schannel may be able to fetch missing intermediates (AIA).
    # This remains cryptographically verified; no insecure HTTP or skipped checks.
    try:
        import truststore
    except ImportError as exc:
        raise RuntimeError(
            "OEA TLS: Requests and Windows CA fallback could not validate the "
            "certificate chain. Install Windows native TLS support with "
            "'python -m pip install truststore', then retry. "
            "Do not use verify=False."
        ) from exc

    print("[OEA/TLS] Trying native Windows certificate verification (truststore)")
    try:
        return _get_windows_verified(url, truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    except (OSError, ssl.SSLError) as exc:
        raise RuntimeError(
            "OEA TLS: the official website certificate could not be verified "
            "even by Windows. Do not bypass the warning. "
            "If the browser verifies the official site, download its OPPI Excel "
            "into Downloads and use '--xlsx <file>' as a temporary fallback. "
            f"Technical detail: {type(exc).__name__}: {exc}"
        ) from exc


def _get(url: str) -> bytes:
    _ensure_official_url(url)
    for attempt in range(3):
        try:
            with requests.get(url, headers=HEADERS, timeout=(18, 70), stream=True) as r:
                r.raise_for_status()
                _ensure_official_url(r.url)
                chunks = []
                total = 0
                for chunk in r.iter_content(chunk_size=131072):
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise ValueError("OEA: download exceeds safe size")
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.exceptions.SSLError as exc:
            if not _is_cert_issue(exc):
                raise
            print("[OEA/TLS] Default certificate verification failed; "
                  "checking trusted Windows certificates")
            return _get_after_cert_failure(url, exc)
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            temporary = (isinstance(exc, (requests.Timeout, requests.ConnectionError))
                         or status in (429, 500, 502, 503, 504))
            if not temporary or attempt == 2:
                raise
            time.sleep(1.5 * (2 ** attempt))
    raise RuntimeError("OEA: unavailable")


def _link_from_element(element, page_url: str) -> str | None:
    href = element.get("href") or ""
    onclick = element.get("onclick") or ""
    if href.startswith("javascript:"):
        onclick = href + " " + onclick
        href = ""
    if not href or href == "#":
        links = re.findall(r"['\"]([^'\"]+\.(?:xls|xlsx|csv|asp)(?:\?[^'\"]*)?)['\"]", onclick, re.I)
        if links:
            href = links[0]
    if not href or href.startswith(("mailto:", "#")):
        return None
    if href.lower().endswith((".js", ".css")):
        return None
    full = urljoin(page_url, unquote(href).replace("&amp;", "&"))
    try:
        _ensure_official_url(full)
    except ValueError:
        return None
    if full == page_url:
        return None
    return full


def discover_oppi_url(page: bytes) -> tuple[str, list[str]]:
    """Discover link under the **OPPI** column of the official download table.

    Never use the neighboring WPI / trial IPPI column even when label matches.
    """
    soup = BeautifulSoup(page, "html.parser")
    candidates = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for i, tr in enumerate(rows):
            cells = tr.find_all(["td", "th"], recursive=False)
            headings = [_norm(c.get_text(" ", strip=True)) for c in cells]
            oppi_columns = [j for j, h in enumerate(headings)
                            if "output producer price" in h or re.search(r"\boppi\b", h)]
            for pos in oppi_columns:
                for next_tr in rows[i + 1:i + 5]:
                    next_cells = next_tr.find_all(["td", "th"], recursive=False)
                    heading = _norm(next_tr.get_text(" ", strip=True))
                    if not ("apr-2023" in heading or "apr 2023" in heading or
                            "monthly" in heading or "index" in heading):
                        continue
                    if len(next_cells) <= pos:
                        continue
                    for a in next_cells[pos].find_all(["a", "button"], recursive=True):
                        link = _link_from_element(a, INDEX_PAGE)
                        if link:
                            candidates.append(link)
    # Simpler alternative site layouts may label an individual link as OPPI.
    for a in soup.find_all(["a", "button"]):
        desc = _norm(a.get_text(" ", strip=True) + " " + str(a.get("title", "")))
        if "output producer price" in desc or re.search(r"\boppi\b", desc):
            link = _link_from_element(a, INDEX_PAGE)
            if link:
                candidates.append(link)
    candidates = list(dict.fromkeys(candidates))
    page_anchors = [a.get_text(" ", strip=True)[:65] for a in soup.find_all("a")][:25]
    # The OEA page also advertises yearly OPPI; never choose it by link order.
    monthly = [u for u in candidates if _is_official_oppi_monthly_filename(u)]
    if not monthly:
        raise ValueError("OEA: could not identify the official OPPI *monthly* workbook "
                         f"(not WPI/IPPI/yearly); candidates={candidates[:12]}, "
                         f"page anchors={page_anchors}. "
                         "Use an original oppi_monthly_index_YYYYMM.xlsx with --xlsx.")
    monthly.sort(reverse=True)
    return monthly[0], candidates


def _is_official_oppi_monthly_filename(filename_or_url: str) -> bool:
    """Require the issuer's exact monthly OPPI export naming convention.

    This is important: the WPI All Commodities index has *similar* recent
    values and cannot be distinguished by a few spot checks alone.
    """
    name = Path(unquote(urlparse(str(filename_or_url)).path)).name.lower()
    return bool(re.fullmatch(r"oppi_monthly_index_20\d{4}\.xlsx?", name))


def _extract_oea_sheet2(rows: list[tuple], title: str) -> dict[pd.Period, Decimal] | None:
    """Actual OEA monthly export (observed 2026-10):

    Level | Commodity Code | Commodity Name | Commodity Weight | Apr-23 | ...
    All   | 1000000000    | ALL COMMODITIES | 100              | 99.1   | ...

    Sheet2 does not contain 'OPPI' in its visible cells: workbook provenance
    must be established by the official URL / original local filename.
    """
    candidates = []
    expected_fields = ["level", "commodity code", "commodity name", "commodity weight"]
    for i, row in enumerate(rows[:35]):
        if len(row) < 20 or [_norm(x) for x in row[:4]] != expected_fields:
            continue
        monthcols: list[tuple[int, pd.Period]] = []
        for j in range(4, len(row)):
            cell = row[j]
            if isinstance(cell, str):
                cell = re.sub(r"\s*\([PFR]\)\s*$", "", cell, flags=re.I)
            month = _month(cell)
            if month is not None:
                monthcols.append((j, month))
        if len(monthcols) < 20:
            continue
        periods = [p for _, p in monthcols]
        if len(set(periods)) != len(periods) or periods != list(pd.period_range(periods[0], periods[-1], freq="M")):
            raise ValueError(f"OEA: invalid/duplicate monthly column headings in {title}")
        if periods[0] != START:
            raise ValueError(f"OEA: OPPI table must begin {START}, found {periods[0]}")
        for rowdata in rows[i+1:]:
            if len(rowdata) < 4 or not _is_aggregate(rowdata[2]):
                continue
            level = _norm(rowdata[0])
            code = re.sub(r"\.0+$", "", str(rowdata[1]).strip())
            weight = _level(rowdata[3])
            if level != "all" or code != "1000000000" or weight != Decimal("100"):
                raise ValueError("OEA: 'ALL COMMODITIES' row has unexpected level, code, or weight: "
                                 f"{[rowdata[k] for k in range(4)]}")
            values = {}
            for j, month in monthcols:
                v = _level(rowdata[j] if j < len(rowdata) else None)
                if v is None:
                    raise ValueError(f"OEA: missing/invalid OPPI value at {month} ({title})")
                values[month] = v
            candidates.append(values)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError(f"OEA: {len(candidates)} matching All Commodities series: ambiguous workbook")
    return candidates[0]


def _sheet_rows(sheet):
    # Safety bounds; rows beyond this still need expanding if OEA gets more data.
    if (sheet.max_row or 0) > 25000 or (sheet.max_column or 0) > 550:
        raise ValueError(f"OEA: implausible sheet size {sheet.title}")
    return list(sheet.iter_rows(values_only=True))


def _read_rows_xlsx(data: bytes) -> list[tuple[str, list[tuple]]]:
    from zipfile import BadZipFile
    try:
        book = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except (BadZipFile, ValueError, OSError) as exc:
        raise ValueError("OEA: unsupported workbook format (expected .xlsx)") from exc
    try:
        return [(sheet.title, _sheet_rows(sheet)) for sheet in book.worksheets]
    finally:
        book.close()


def _read_rows_xls(data: bytes) -> list[tuple[str, list[tuple]]]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("OEA published binary .xls: install 'xlrd>=2' in .venv") from exc
    book = xlrd.open_workbook(file_contents=data)
    return [(s.name, [tuple(s.row_values(i)) for i in range(s.nrows)])
            for s in book.sheets()]


def _extract_tall(rows: list[tuple], aggregate_col: int, label_row: int) -> dict[pd.Period, Decimal]:
    """Data may be horizontal: aggregate column next to a month column."""
    result = {}
    for row in rows[label_row + 1:]:
        if aggregate_col >= len(row):
            continue
        value = _level(row[aggregate_col])
        if value is None:
            continue
        dates = [p for j in range(min(10, len(row))) if j != aggregate_col
                 if (p := _month(row[j])) is not None]
        if len(dates) != 1:
            continue
        period = dates[0]
        if period in result:
            raise ValueError(f"OEA: duplicate {period} for OPPI")
        result[period] = value
    return result


def _extract_wide(rows: list[tuple], aggregate_row: int, label_col: int) -> dict[pd.Period, Decimal]:
    """Data may be wide: aggregate row and monthly column headings."""
    data = rows[aggregate_row]
    found = {}
    for j, value in enumerate(data):
        if j == label_col or (num := _level(value)) is None:
            continue
        labels = []
        for row in rows[max(0, aggregate_row - 14):aggregate_row]:
            if j < len(row):
                labels.append(row[j])
        months = [x for x in (_month(x) for x in labels) if x is not None]
        months = list(dict.fromkeys(months))
        if len(months) != 1:
            continue
        month = months[0]
        if month in found and found[month] != num:
            raise ValueError(f"OEA: conflicting values for {month}")
        found[month] = num
    return found


def _candidate_series(sheets: list[tuple[str, list[tuple]]]):
    candidates = []
    for title, rows in sheets:
        # Excel must identify OPPI rather than WPI; do not trust an undifferentiated file.
        context = " ".join([title, *[str(cell) for row in rows[:28]
                                         for cell in row[:12] if cell is not None]])
        context_norm = _norm(context)
        is_oppi = "output producer price" in context_norm or bool(re.search(r"\boppi\b", context_norm))
        if not is_oppi:
            continue
        for i, row in enumerate(rows):
            for j, cell in enumerate(row[:18]):
                if not _is_aggregate(cell):
                    continue
                for series in (_extract_wide(rows, i, j), _extract_tall(rows, j, i)):
                    if len(series) >= 12:
                        candidates.append((title, series))
    return candidates


def _validate_controls(series: dict[pd.Period, Decimal]) -> bool:
    # June/July 2026 are final according to the September 2026 OEA release.
    for year_month, published in FINALIZED_CONTROL.items():
        v = series.get(pd.Period(year_month, freq="M"))
        if v is None or abs(v - Decimal(str(published))) > Decimal("0.051"):
            return False
    # August/September 2026 were provisional. Enforce them for the initial
    # release, but don't block later official revisions when new months arrive.
    if max(series) <= pd.Period("2026-09", freq="M"):
        for year_month, published in PROVISIONAL_CONTROL.items():
            v = series.get(pd.Period(year_month, freq="M"))
            if v is None or abs(v - Decimal(str(published))) > Decimal("0.051"):
                return False
    return True


def _validated_levels(sheets: list[tuple[str, list[tuple]]], *,
                      verified_monthly_oppi: bool = False) -> dict[pd.Period, Decimal]:
    # No title appears in OEA's actual Sheet2. Identity therefore comes from
    # the officially discovered URL / original OEA filename, combined with
    # the exact level/code/weight/header structure and published controls.
    structured = []
    if verified_monthly_oppi:
        for title, rows in sheets:
            series = _extract_oea_sheet2(rows, title)
            if series:
                structured.append((title, series))
    candidates = structured if structured else _candidate_series(sheets)
    if not candidates:
        names = [name for name, _ in sheets]
        preview = [str(x)[:100] for _, rows in sheets[:2] for row in rows[:8]
                   for x in row[:6] if x is not None][:30]
        raise ValueError("OEA: no validated OPPI All Commodities monthly series "
                         f"in sheets {names}; sample: {preview}; "
                         "requires official OPPI monthly workbook (not WPI).")
    complete = []
    for title, series in candidates:
        newest = max(series)
        expected = set(pd.period_range(START, newest, freq="M"))
        if newest < MIN_LAST or not expected.issubset(series):
            continue
        if newest > pd.Period(pd.Timestamp.now(), freq="M"):
            continue
        if not _validate_controls(series):
            continue
        complete.append((title, series))
    if not complete:
        example = [(title, len(s), str(max(s)),
                    str(s.get(pd.Period("2026-06", freq="M"))),
                    str(s.get(pd.Period("2026-09", freq="M"))))
                   for title, s in candidates[:5]]
        raise ValueError("OEA: candidate OPPI found, but monthly history or official "
                         f"control values do not match; examples={example}; no data saved")
    first = complete[0][1]
    for _, series in complete[1:]:
        if first != series:
            raise ValueError("OEA: multiple contradictory OPPI All Commodities series")
    return first


def parse_oppi(data: bytes, *, source_name: str | None = None) -> pd.DataFrame:
    if data[:4] == b"PK\x03\x04":
        sheets = _read_rows_xlsx(data)
    elif data[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        sheets = _read_rows_xls(data)
    else:
        raise ValueError("OEA: download is not a supported Excel workbook; "
                         f"prefix={data[:45]!r}")
    return levels_to_frame(_validated_levels(
        sheets, verified_monthly_oppi=bool(source_name and _is_official_oppi_monthly_filename(source_name))))


def _ratio(current: Decimal, base: Decimal) -> float:
    if base <= 0:
        raise ValueError("OEA: nonpositive base")
    x = (current / base - Decimal(1)) * Decimal(100)
    if not x.is_finite() or abs(x) > 300:
        raise ValueError("OEA: implausible monthly/yoy change")
    return float(x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def levels_to_frame(levels: dict[pd.Period, Decimal]) -> pd.DataFrame:
    latest = max(levels, default=None)
    if latest is None or latest < MIN_LAST:
        raise ValueError("OEA: source is older than the September 2026 release")
    expected = set(pd.period_range(START, latest, freq="M"))
    if not expected.issubset(levels):
        raise ValueError("OEA: monthly gaps: " + ", ".join(map(str, sorted(expected - set(levels))[:15])))
    if not _validate_controls(levels):
        raise ValueError("OEA: index differs from published final/provisional OPPI controls")
    out = []
    for p in sorted(expected):
        for metric, lag in (("ppi_mom", 1), ("ppi_yoy", 12)):
            old = levels.get(p - lag)
            if old is None:
                continue
            out.append(("IN", p.start_time, metric,
                        _ratio(levels[p], old), SOURCE, "%",
                        "NSA; change from rounded official OPPI levels"))
    df = pd.DataFrame(out, columns=COLS)
    if df.empty or set(df.metric) != {"ppi_mom", "ppi_yoy"} or df.duplicated(["country", "date", "metric"]).any():
        raise ValueError("OEA: incomplete output frame")
    return df.sort_values(["date", "metric"]).reset_index(drop=True)


def fetch_india_ppi(*, xlsx: str | Path | None = None) -> pd.DataFrame:
    if xlsx is not None:
        path = Path(xlsx)
        if path.suffix.lower() not in (".xls", ".xlsx"):
            raise ValueError("OEA: local file must be official .xlsx or .xls")
        if not _is_official_oppi_monthly_filename(path.name):
            raise ValueError("OEA: local workbook must retain its original official "
                             "name oppi_monthly_index_YYYYMM.xlsx to verify OPPI "
                             "provenance; not WPI/IPPI/yearly")
        print(f"[OEA] Official OPPI local file: {path}")
        blob = path.read_bytes()
        source_name = path.name
    else:
        print(f"[OEA] Find official OPPI download: {INDEX_PAGE}")
        url, candidates = discover_oppi_url(_get(INDEX_PAGE))
        if len(candidates) > 1:
            print(f"[OEA] Candidate links: {candidates[:5]}")
        print(f"[OEA] GET {url}")
        blob = _get(url)
        source_name = url
    return parse_oppi(blob, source_name=source_name)


def run(*, dry_run: bool = False, xlsx: str | None = None) -> int:
    try:
        frame = fetch_india_ppi(xlsx=xlsx)
        for metric, part in frame.groupby("metric"):
            last = part.iloc[-1]
            print(f"[PASS] IN/{metric}: n={len(part)}, "
                  f"{part.date.min():%Y-%m}..{last.date:%Y-%m}, latest={last.value:+.1f}%")
        if dry_run:
            print("[READ-ONLY] Database unchanged")
            return 0
        save_eurostat_extra(frame)
        return 0
    except (ValueError, RuntimeError, OSError, requests.RequestException) as exc:
        print(f"[FAIL] India OPPI: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Official India Output PPI")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--xlsx", help="official OEA OPPI xlsx/xls saved locally")
    opts = parser.parse_args()
    sys.exit(run(dry_run=opts.dry_run, xlsx=opts.xlsx))
