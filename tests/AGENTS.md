# Контекст проверок

Запуск из корня: `python -m unittest discover -s tests -v`.
В CI тесты подключены к runtime-образу read-only, сеть отключена,
`MACRO_DATA_DIR=/tmp/macro-tests`. Не обращаться к рабочей SQLite или API-ключам.
Для AppTest подменять загрузчики до запуска. Операционные тесты проверяют backup
и завершение процессов по timeout/shutdown. Корневой test.py — ручная диагностика.
