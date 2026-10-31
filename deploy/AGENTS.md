# Контекст конфигурации ВМ

Каноническая инструкция — `docs/DEPLOYMENT.md`. Здесь только безопасные шаблоны.
API-ключи — в `.env` ВМ, параметры Compose — в `compose.env`; секретов в Git нет.
Имена переменных согласовывать с Compose, workflow и инструкцией.

Контракт: Ubuntu amd64, Compose v2.20+, `/opt/macrodashboard`, пользователь deploy,
UID/GID данных 10001:10001, один web и один updater. Изменение путей/портов должно
учитывать deploy.sh, права и правила VPC. Не публиковать Docker API/socket,
не отключать CORS/XSRF или проверку SSH host key. Релиз не должен удалять SQLite.

`compose.caddy.yaml` + `Caddyfile` — отдельный проект macrodashboard-proxy для
ручного запуска Ubuntu/Linux. Host networking обращается к localhost:8501 ВМ;
MACRO_DOMAIN передаётся из compose.env. Данные сертификатов — постоянные volumes.
Не открывать 8501 наружу в сценарии HTTPS; не удалять volumes Caddy при релизах.
Пошаговый ручной сценарий: docs/MANUAL_DEPLOYMENT.md.
