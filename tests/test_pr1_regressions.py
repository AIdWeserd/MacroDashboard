"""Локальные регрессионные проверки PR №1, без запросов к источникам."""
import ast
from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, Mock

import pandas as pd
import requests

from src import fetch_us_bea as bea, storage
import src.build_summary as summary


class AnnualTests(unittest.TestCase):
    def test_missing_debt_preserves_bea_and_history(self):
        dates = pd.date_range("2024-01-01", periods=4, freq="QS")
        with patch.object(bea, "_fetch_nipa_annual", return_value=pd.DataFrame({"date": dates[:1], "value": [-1800.]})), \
             patch.object(bea, "fetch_us_gdp", return_value=pd.DataFrame({"date": dates, "gdp_usd_mn": [30000.]*4})), \
             patch.object(bea, "fetch_us_current_account", return_value=pd.DataFrame({"date": dates, "trade_usd_mn": [-300.]*4})), \
             patch.object(bea, "fetch_us_general_gov_debt_annual", return_value=pd.DataFrame()):
            result = bea.fetch_us_general_gov_annual()
        self.assertFalse(result.empty)
        self.assertTrue(result.debt_gdp.isna().all())
        self.assertTrue(result.attrs["source_issues"])
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory)/"test.db"):
            old = result.copy()
            old["debt_gdp"] = 100.
            storage.save_us_annual_bea(old)
            storage.save_us_annual_bea(result)
            stored = storage.load_us_annual_bea()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored.debt_gdp.iloc[0], 100.)
            with sqlite3.connect(storage.DB_PATH) as con:
                self.assertEqual(con.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_empty_current_account_preserves_budget(self):
        dates = pd.date_range("2024-01-01", periods=4, freq="QS")
        with patch.object(bea, "_fetch_nipa_annual", return_value=pd.DataFrame({"date": dates[:1], "value": [-1800.]})), \
             patch.object(bea, "fetch_us_gdp", return_value=pd.DataFrame({"date": dates, "gdp_usd_mn": [30000.]*4})), \
             patch.object(bea, "_get", return_value={"BEAAPI": {"Results": {"Data": []}}}), \
             patch.object(bea, "fetch_us_general_gov_debt_annual", return_value=pd.DataFrame()):
            result = bea.fetch_us_general_gov_annual()
        self.assertFalse(result.empty)
        self.assertTrue(result.trade_gdp.isna().all())
        self.assertTrue(result.debt_gdp.isna().all())
        self.assertTrue(result.budget_gdp.notna().all())
        self.assertEqual(len(result.attrs["source_issues"]), 2)

    def test_fred_error_does_not_disclose_key(self):
        secret = "dummy-secret-never-print"
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(f"401 https://example.test/?api_key={secret}")
        output = io.StringIO()
        with patch.object(bea, "FRED_API_KEY", secret), patch.object(bea.requests, "get", return_value=response), redirect_stdout(output):
            self.assertTrue(bea.fetch_us_general_gov_debt_annual().empty)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("HTTPError", output.getvalue())


def app_helpers():
    tree = ast.parse(Path("app.py").read_text())
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ("to_pdf_bytes", "to_excel_bytes")]
    namespace = {"pd": pd, "io": io}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


class ExportTests(unittest.TestCase):
    def test_pdf_failure_is_explicit(self):
        with patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Не удалось создать PDF"):
                app_helpers()["to_pdf_bytes"](pd.DataFrame({"Страна": ["Россия"]}))

    def test_missing_playwright_is_explicit(self):
        with patch.dict("sys.modules", {"playwright.sync_api": None}):
            with self.assertRaisesRegex(RuntimeError, "PDF недоступен"):
                app_helpers()["to_pdf_bytes"](pd.DataFrame({"Страна": ["Россия"]}))

    def test_excel_has_no_formula(self):
        from openpyxl import load_workbook
        data = app_helpers()["to_excel_bytes"](pd.DataFrame({"Страна": ["=1+1"]}))
        book = load_workbook(io.BytesIO(data))
        self.assertNotEqual(book.active["A2"].data_type, "f")


class AppTests(unittest.TestCase):
    def test_regions_are_independent_and_pdf_error_visible(self):
        from streamlit.testing.v1 import AppTest
        import src.snapshot as snapshots
        rows = []
        from src.summary_ui import METRICS
        for country, name, region in (("US", "США", "Америка"), ("DE", "Германия", "Европа")):
            row = {"country": country, "country_name": name, "region": region}
            for metric in METRICS:
                row[metric.key] = 4.
                row[metric.key + "_date"] = "2025 (Eurostat, Gen Gov)"
            rows.append(row)
        with ExitStack() as stack:
            for name in vars(storage):
                if name.startswith("load_"):
                    stack.enter_context(patch.object(storage, name, return_value=pd.DataFrame()))
            stack.enter_context(patch.object(summary, "build_summary", return_value=pd.DataFrame(rows)))
            stack.enter_context(patch.object(snapshots, "load_previous_snapshot", return_value=pd.DataFrame()))
            stack.enter_context(patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("unavailable")))
            app = AppTest.from_file(str(Path("app.py").resolve()), default_timeout=30).run()
            self.assertEqual(len(app.exception), 0)
            app.button_group(key="summary_region").set_value(["Америка"])
            app.button_group(key="no_dates_region").set_value(["Европа"])
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.dataframe[0].value["Страна"].tolist(), ["США"])
            self.assertEqual(app.dataframe[1].value["Страна"].tolist(), ["Германия"])
            app.selectbox(key="export_format").set_value("PDF").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Не удалось создать PDF" in item.value for item in app.error))
            download = next(item for item in app.get("download_button") if item.proto.id.endswith("download_table"))
            self.assertTrue(download.proto.disabled)


if __name__ == "__main__":
    unittest.main()
