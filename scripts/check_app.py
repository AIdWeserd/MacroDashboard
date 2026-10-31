"""Проверка рендера приложения без сетевого обновления данных."""

from unittest.mock import patch
from pathlib import Path

from streamlit.testing.v1 import AppTest


def main() -> None:
    with patch("src.fetch_forexfactory.fetch_calendar") as fetch:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path)).run(timeout=60)
        if app.exception:
            raise RuntimeError("Streamlit render failed: " + str(app.exception))
        fetch.assert_not_called()
    print("Streamlit render OK")


if __name__ == "__main__":
    main()
