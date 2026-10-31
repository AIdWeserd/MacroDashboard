import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest


class CalendarTests(unittest.TestCase):
    def app(self):
        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))

    def test_render_does_not_fetch_calendar(self):
        with patch("src.storage.load_forexfactory", return_value=pd.DataFrame()), \
                patch("src.fetch_forexfactory.fetch_calendar") as fetch:
            app = self.app().run(timeout=30)
            self.assertFalse(app.exception)
            fetch.assert_not_called()
            self.assertTrue(any("Календарь пока пуст" in item.value for item in app.info))

    def test_failed_refresh_keeps_saved_events(self):
        saved = pd.DataFrame([{
            "datetime": pd.Timestamp("2026-10-11T12:00:00Z"),
            "country": "EU", "currency": "EUR", "event": "Saved event",
            "importance": 3, "actual": "1", "forecast": "2", "previous": "3",
        }])
        with patch("src.storage.load_forexfactory", return_value=saved), \
                patch("src.storage.save_forexfactory") as save, \
                patch("src.fetch_forexfactory.fetch_calendar", side_effect=RuntimeError("HTTP 403")) as fetch:
            app = self.app().run(timeout=30)
            app.button(key="refresh_calendar").click().run(timeout=30)
            self.assertFalse(app.exception)
            fetch.assert_called_once()
            save.assert_not_called()
            self.assertTrue(any("недоступен" in item.value for item in app.warning))
            self.assertTrue(any("Saved event" in item.value for item in app.markdown))


if __name__ == "__main__":
    unittest.main()
