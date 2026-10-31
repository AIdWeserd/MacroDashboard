"""Первый деплой должен работать до загрузки внешних макроданных."""

from contextlib import ExitStack
import unittest
from unittest.mock import patch

import pandas as pd
import src.build_summary as summary_module


class SummaryStartupTests(unittest.TestCase):
    def summary(self, imf=None):
        with ExitStack() as patches:
            for name in vars(summary_module):
                if name.startswith("load_"):
                    patches.enter_context(patch.object(summary_module, name, return_value=pd.DataFrame()))
            if imf is not None:
                patches.enter_context(patch.object(summary_module, "load_imf", return_value=imf))
            return summary_module.build_summary(year=2026, month=10)

    def test_empty_storage_preserves_schema_and_missing_values(self):
        result = self.summary()
        self.assertEqual(len(result), len(summary_module.COUNTRY_ORDER))
        columns = ["debt_gdp", "budget_gdp", "trade_gdp", "gdp_growth", "inflation_imf"]
        self.assertTrue(result[columns].isna().all().all())
        self.assertTrue(result[[name + "_date" for name in columns[:4]]].isna().all().all())

    def test_imf_values_still_override_initial_missing_values(self):
        imf = pd.DataFrame([{
            "country": "US", "year": 2026, "metric": "DEBT_GDP", "value": 123.45,
        }])
        result = self.summary(imf).set_index("country")
        self.assertEqual(result.loc["US", "debt_gdp"], 123.45)
        self.assertTrue(pd.isna(result.loc["US", "gdp_growth"]))


if __name__ == "__main__":
    unittest.main()
