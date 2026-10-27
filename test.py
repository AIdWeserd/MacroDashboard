"""Macro Dashboard: единый временный test.py для проверки этапов 1 и 2.

Запуск: python test.py
Нет запросов в интернет и записи в рабочую SQLite. Тестовые БД
создаются только в системном временном каталоге и удаляются.
"""
import unittest
import pandas as pd
from src.summary_ui import METRICS, sort_summary, make_forecast_table, compare_snapshot


class SummaryUiTests(unittest.TestCase):
    def setUp(self):
        self.summary = pd.DataFrame([
            {"country":"CA", "country_name":"Канада", "inflation":3.1, "inflation_date":"сен 2026"},
            {"country":"US", "country_name":"США", "inflation":4.0, "inflation_date":"сен 2026"},
            {"country":"RU", "country_name":"Россия", "inflation":6.0, "inflation_date":"сен 2026"},
        ])
        self.imf = pd.DataFrame([
            {"country":"CA", "metric":"GDP_USD_BN", "year":2025, "value":2000},
            {"country":"US", "metric":"GDP_USD_BN", "year":2025, "value":30000},
            {"country":"RU", "metric":"GDP_USD_BN", "year":2025, "value":2200},
            {"country":"US", "metric":"GDP_GROWTH", "year":2027, "value":1.7},
            {"country":"CA", "metric":"INFLATION", "year":2027, "value":2.0},
        ])

    def test_legacy_order_when_imf_not_populated(self):
        out, message = sort_summary(self.summary, pd.DataFrame(), "ВВП ↓", 2026, 2026)
        self.assertEqual(out.country.tolist(), self.summary.country.tolist())
        self.assertIn("нет номинального ВВП", message)

    def test_nominal_gdp_sort_not_gdp_growth(self):
        out, _ = sort_summary(self.summary, self.imf, "ВВП ↓", 2026, 2026)
        self.assertEqual(out.country.tolist(), ["US", "RU", "CA"])
        self.assertEqual(out.set_index("country")["inflation"].to_dict(),
                         self.summary.set_index("country")["inflation"].to_dict())

    def test_gdp_asc(self):
        out, _ = sort_summary(self.summary, self.imf, "ВВП ↑", 2026, 2026)
        self.assertEqual(out.country.tolist(), ["CA", "RU", "US"])

    def test_missing_gdp_stays_last(self):
        imf = self.imf[self.imf.country.ne("RU")]
        out, message = sort_summary(self.summary, imf, "ВВП ↓", 2026, 2026)
        self.assertEqual(out.country.tolist(), ["US", "CA", "RU"])
        self.assertIn("1 экономик", message)

    def test_forecasts_only_published(self):
        forecast = make_forecast_table(self.imf, {"US":"США", "CA":"Канада"}, 2027)
        self.assertEqual(set(forecast["Страна"]), {"США", "Канада"})
        self.assertIn("прогноз", forecast["Год / статус"].iloc[0])
        self.assertAlmostEqual(float(forecast.loc[forecast["Страна"].eq("США"), "Реальный ВВП YoY, %"].iloc[0]),1.7)
        self.assertTrue(make_forecast_table(self.imf, {"US":"США"}, 2035).empty)

    def test_snapshot_is_not_previous_release(self):
        old = pd.DataFrame([
            {"snapshot_date":"2026-W42", "country":"CA", "metric":"inflation", "value":2.9},
        ])
        out = compare_snapshot(self.summary[self.summary.country.eq("CA")], old,
                               {"CA":"Канада"}, ["inflation"])
        self.assertEqual(out.iloc[0]["Прошлый недельный снимок"], 2.9)
        self.assertEqual(out.iloc[0]["Сейчас"], 3.1)

    def test_metric_frequency_labels_present(self):
        self.assertEqual(len(METRICS), 13)
        self.assertTrue(all(m.frequency and m.label for m in METRICS))



# Auxiliary regression checks for official Eurostat Core MoM.
# Kept separate from tests of the presentation model to avoid network calls.
class EurostatCoreMomTests(unittest.TestCase):
    def test_official_monthly_core_is_kept_as_published(self):
        from unittest.mock import patch
        from src.fetch_eurostat import fetch_eurostat_hicp
        date = pd.Timestamp.now().replace(day=1)
        def fake(unit, coicop):
            amounts = {
                ('RCH_A', 'TOTAL'): 2.8,
                ('RCH_M', 'TOTAL'): 0.3,
                ('RCH_A', 'TOT_X_NRG_FOOD'): 2.1,
                ('RCH_M', 'TOT_X_NRG_FOOD'): 0.4,
            }
            return pd.DataFrame([{'date':date,'country':'DE','value':amounts[(unit,coicop)]}])
        with patch('src.fetch_eurostat._fetch_slice', side_effect=fake):
            actual = fetch_eurostat_hicp()
        self.assertEqual(float(actual.iloc[0]['core_mom']), 0.4)
        self.assertEqual(float(actual.iloc[0]['value']), 2.8)
        self.assertEqual(float(actual.iloc[0]['core']), 2.1)

    def test_core_mom_failure_does_not_break_existing_hicp(self):
        from unittest.mock import patch
        from src.fetch_eurostat import fetch_eurostat_hicp
        date = pd.Timestamp.now().replace(day=1)
        def fake(unit, coicop):
            if unit == 'RCH_M' and coicop == 'TOT_X_NRG_FOOD':
                raise RuntimeError('temporary interruption')
            return pd.DataFrame([{'date':date,'country':'EU','value':1.2}])
        with patch('src.fetch_eurostat._fetch_slice', side_effect=fake):
            actual = fetch_eurostat_hicp()
        self.assertEqual(len(actual), 1)
        self.assertTrue(pd.isna(actual.iloc[0]['core_mom']))
        self.assertEqual(actual.iloc[0]['mom'], 1.2)

    def test_build_summary_copies_only_published_values(self):
        from src.build_summary import _set_inflation
        date = pd.Timestamp.now().replace(day=1)
        row = {'inflation':None,'inflation_mom':None,
               'inflation_core':None,'inflation_core_mom':None}
        sample = pd.DataFrame([{'date':date,'country':'DE', 'value':3.1,
                                'mom':0.2,'core':2.8,'core_mom':0.05}])
        _set_inflation(row, sample, date + pd.offsets.MonthEnd(0), 'DE')
        self.assertEqual(row['inflation_core_mom'],0.05)
        self.assertEqual(row['inflation_core'],2.8)
        self.assertIn('inflation_core_mom_date',row)


class MainSummaryDateLayoutTests(unittest.TestCase):
    def test_main_table_keeps_period_inside_each_metric_cell(self):
        # The Streamlit entrypoint cannot be imported as a test module:
        # importing it would execute the app. Extract only the pure formatter.
        import ast
        from pathlib import Path
        app = Path(__file__).resolve().parent / "app.py"
        source = app.read_text(encoding="utf-8")
        self.assertNotIn("summary_period_columns", source)
        self.assertNotIn("Период · ", source)
        self.assertIn("🔢 Таблица без дат (только значения)", source)
        self.assertIn("merge_value_date(v, d) for v, d in zip(values, dates)", source)

        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "merge_value_date")
        fn = ast.Module(body=[node], type_ignores=[])
        namespace = {"pd": pd}
        exec(compile(ast.fix_missing_locations(fn), str(app), "exec"), namespace)
        merge = namespace["merge_value_date"]
        self.assertEqual(merge(3.09, "сен 2026"), "3.09 · сен 2026")
        self.assertEqual(merge(120.74, "Q2 2026 (StatCan, Gen Gov)"),
                         "120.74 · Q2 2026 (StatCan, Gen Gov)")
        self.assertEqual(merge(float("nan"), "сен 2026"), "—")


# ----------- Eurostat extra, проверка записи во временную SQLite -----------

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import eurostat_extra as e


class EurostatExtraTests(unittest.TestCase):
    def sample(self, metric="ppi_yoy"):
        return pd.DataFrame([
            {"country": "DE", "date": pd.Timestamp("2026-08-31"),
             "metric": metric, "value": 1.5, "source": "Eurostat/sts_inppd_m",
             "unit": "PCH_SM", "adjustment": "NSA"},
            {"country": "DE", "date": pd.Timestamp("2026-09-30"),
             "metric": metric, "value": 1.6, "source": "Eurostat/sts_inppd_m",
             "unit": "PCH_SM", "adjustment": "NSA"},
        ])

    def test_cutoff_and_metadata(self):
        frame = e.enrich_summary(pd.DataFrame([{"country":"DE", "inflation":3.4}]),
                                 self.sample(), 2026, 8)
        self.assertEqual(frame.iloc[0].ppi_yoy, 1.5)
        self.assertEqual(frame.iloc[0].inflation, 3.4)
        self.assertIn("авг 2026", frame.iloc[0].ppi_yoy_date)

    def test_not_weekly_snapshot(self):
        result = e.previous_published(self.sample(), ["DE"], 2026, 9)
        self.assertEqual(result.iloc[0]["Текущее"], 1.6)
        self.assertEqual(result.iloc[0]["Предыдущее"], 1.5)

    def test_write_idempotence_and_preserves_existing_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.sqlite"
            with closing(sqlite3.connect(path)) as conn:
                with conn:
                    conn.execute("CREATE TABLE legacy(data TEXT)")
                    conn.execute("INSERT INTO legacy VALUES ('untouched')")
            with patch.object(e, "DB_PATH", path):
                e.save_eurostat_extra(self.sample())
                e.save_eurostat_extra(self.sample())
                got = e.load_eurostat_extra()
                self.assertEqual(len(got), 2)
                with closing(sqlite3.connect(path)) as conn:
                    self.assertEqual(conn.execute("SELECT data FROM legacy").fetchone()[0], "untouched")
                    self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_storage_connections_close_explicitly(self):
        """Regression: Windows cannot remove a temp DB while it remains open."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.sqlite"
            real_connect = sqlite3.connect
            opened = []

            class TrackedConnection(sqlite3.Connection):
                closed_explicitly = False

                def close(self):
                    self.closed_explicitly = True
                    return super().close()

            def tracked_connect(*args, **kwargs):
                kwargs["factory"] = TrackedConnection
                conn = real_connect(*args, **kwargs)
                opened.append(conn)
                return conn

            with patch.object(e, "DB_PATH", path), patch.object(
                e.sqlite3, "connect", side_effect=tracked_connect
            ):
                e.save_eurostat_extra(self.sample())
                self.assertEqual(len(e.load_eurostat_extra()), 2)

            self.assertEqual(len(opened), 2)
            self.assertTrue(all(conn.closed_explicitly for conn in opened))

    def test_refuse_null_no_write(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(e, "DB_PATH", Path(folder)/"test.sqlite"):
                broken = self.sample()
                broken.loc[0, "value"] = None
                with self.assertRaises(ValueError):
                    e.save_eurostat_extra(broken)
                self.assertFalse(e.DB_PATH.exists())

    def test_period_quarter_end(self):
        self.assertEqual(str(e._period_date("2026-Q2"))[:10], "2026-06-30")
        self.assertEqual(str(e._period_date("2026-09"))[:10], "2026-09-30")

    def test_source_data_dimensions_are_not_mixed(self):
        """SA value cannot be accepted as NSA YoY even if source returns it."""
        def payload():
            ids = ["geo", "time", "freq", "unit", "s_adj", "indic_bt", "nace_r2"]
            vals = ["DE", "2026-09", "M", "PCH_SM", "SA", "PRC_PRR_DOM", "B-E36"]
            return {"id": ids, "size": [1]*len(ids),
                    "dimension": {i:{"category":{"index":{v:0}}} for i,v in zip(ids,vals)},
                    "value": {"0":2.0}}
        class Response:
            def raise_for_status(self): pass
            def json(self): return payload()
        with patch.object(e.requests,"get", return_value=Response()):
            got=e.fetch_eurostat_extra("ppi_yoy")
        self.assertTrue(got.empty)



if __name__ == "__main__":
    unittest.main(verbosity=2)
