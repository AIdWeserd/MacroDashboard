# Ручной запуск MacroDashboard на Ubuntu с доменом и HTTPS

[Открыть HTML-гайд](manual-deployment.html) — навигация по шагам, подстановка IP
и домена, копирование команд, отметки прогресса и печать в PDF. Работает офлайн.

После успешного ручного запуска: [GitHub Actions для работающей ВМ](GITHUB_ACTIONS_MIGRATION.md)
([HTML-гайд](github-actions.html)).

Результат: приложение доступно по `https://ВАШ_ДОМЕН`, SQLite хранится на диске
той же ВМ. Код собирается на ВМ, GitHub Actions и GHCR для первого запуска не нужны.
Команды ниже рассчитаны на Ubuntu 24.04 LTS amd64, обычного пользователя с sudo,
стандартный SSH-порт 22 и незанятые порты 80/443/8501.

Сначала запускаем web и проверяем его локально. Затем подключаем домен через Caddy
и включаем updater. Caddy работает отдельным Compose-проектом: перезапуск приложения
не удаляет его контейнер или хранилище сертификатов.

Обозначения: `PUBLIC_IP` — публичный IPv4 ВМ, `VM_USER` — ваш SSH-пользователь.
Вместо `macro.example.com` укажите свой домен или поддомен без `https://` и пути.
Приватные ключи и API-ключи не отправляйте в чат.

## 1. Подключиться и проверить Docker

Все команды с компьютера ниже выполняйте в WSL / Bash: там используется уже
настроенный SSH-доступ. Команды на ВМ выполняются после подключения по SSH,
в другом окружении. Удобно держать два окна: локальный WSL и SSH-сессию ВМ.

**На компьютере, WSL / Bash:**

```bash
ssh VM_USER@PUBLIC_IP
```

При нестандартном ключе: `ssh -i ~/.ssh/ИМЯ_КЛЮЧА VM_USER@PUBLIC_IP`.
Если уже используете алиас из ~/.ssh/config, подключайтесь привычной командой
вроде `ssh my-vm`: переносить SSH-ключи в Windows не требуется.
При первом входе сверяйте отпечаток SSH-ключа сервера через доверенный канал.

**Далее на ВМ, Bash:**

```bash
cat /etc/os-release
uname -m
command -v docker || true
sudo docker version
sudo docker compose version
sudo systemctl is-active docker
sudo ss -lntp | grep -E ':(80|443|8501)\b' || true
```

`sudo docker version` должен показать Client и Server, Compose — версию v2.20+
(также подходит более новая совместимая версия). Если обе проверки успешны,
пропустите установку. Если Docker есть, но служба остановлена:

```bash
sudo systemctl enable --now docker
sudo docker version
```

Если порты уже заняты nginx, Apache, Caddy или другим приложением, сначала выясните,
что это за сервис: не останавливайте его вслепую. Установка ниже предназначена
для новой ВМ без другой установки Docker. Если установлен docker.io, podman-docker
или Docker без Compose, используйте раздел о конфликтующих пакетах в
[официальной инструкции Docker](https://docs.docker.com/engine/install/ubuntu/).

## 2. Установить Docker, только если его нет

**На ВМ:**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl nano dnsutils
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Даже если Docker уже был установлен, для следующих проверок удобно иметь:

```bash
sudo apt-get update
sudo apt-get install -y curl nano dnsutils
```

Все дальнейшие команды Docker используют sudo: добавлять пользователя в группу
docker и переподключаться к SSH не требуется.

## 3. Настроить DNS и сетевые правила

В DNS-панели, обслуживающей домен, создайте запись:

| Тип | Имя | Значение |
| --- | --- | --- |
| A | `macro` для macro.example.com, либо `@` для корня домена | PUBLIC_IP ВМ |

Указаны должны быть авторитетные DNS-серверы домена. Если DNS обслуживает регистратор,
создавать зону Yandex Cloud DNS дополнительно не нужно. Если включён прокси DNS-провайдера,
для первого запуска выберите обычный режим DNS only. У выбранного имени не должно
быть старой AAAA-записи, ведущей на другой сервер; IPv6 без настройки ВМ не добавляйте.
Для ВМ желательно закрепить статический публичный IP.

На ВМ проверьте DNS (подставьте свой домен):

```bash
dig +short A macro.example.com @1.1.1.1
dig +short AAAA macro.example.com @1.1.1.1
```

A-запись должна возвращать публичный IP ВМ. Пока изменения DNS не распространились,
проверять HTTPS рано; локальный web уже можно собирать и запускать.

В Яндекс Облаке назначьте интерфейсу ВМ группу безопасности с правилами:

| Направление | Порт | Адреса |
| --- | --- | --- |
| Входящий TCP | 22 | Ваш публичный IP `/32` для SSH |
| Входящий TCP | 80 | `0.0.0.0/0` |
| Входящий TCP | 443 | `0.0.0.0/0` |
| Исходящий | Любой | `0.0.0.0/0` |

8501 наружу не открывайте: web слушает localhost ВМ, к нему обращается Caddy.
[Добавление правил VPC](https://yandex.cloud/ru/docs/vpc/operations/security-group-add-rule).

Проверьте firewall ОС:

```bash
sudo ufw status
```

Если он active, разрешите порты (для нестандартного SSH-порта замените 22):

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

Если UFW inactive, включать его ради запуска не обязательно: доступ уже ограничивает
группа VPC. Не закрывайте действующее SSH-подключение до проверки нового входа.

## 4. Перенести текущий проект на ВМ

Подготовленные файлы пока могут быть только в рабочем дереве компьютера, а не в GitHub.
Архив ниже переносит именно текущий код. `.env`, `data/`, `.git/` и локальные черновики
в архив не входят. Если внутри src/ или scripts/ есть ваши собственные приватные файлы,
исключите их до упаковки.

**На компьютере откройте отдельное окно WSL / Bash, без подключения к ВМ:**

Windows-путь `G:\Edu\MacroDashboard` обычно доступен в WSL как
`/mnt/g/Edu/MacroDashboard`. Переменная vm_target — тот же адрес или SSH-алиас,
которым вы уже успешно подключаетесь к ВМ.

```bash
cd /mnt/g/Edu/MacroDashboard
vm_target='VM_USER@PUBLIC_IP'
macro_archive=/tmp/macrodashboard-upload.tar.gz

tar -czf "$macro_archive" \
  --exclude=__pycache__ --exclude='*.pyc' --exclude=.env \
  --exclude='*.key' --exclude='*.pem' --exclude='*.db' \
  Dockerfile .dockerignore .env.example requirements.txt requirements.lock \
  app.py scheduler.py config.py src scripts .streamlit \
  compose.yaml compose.local.yaml deploy \
  && scp "$macro_archive" "${vm_target}:~/macrodashboard-upload.tar.gz"
```

Например, если работает `ssh my-vm`, замените строку на `vm_target='my-vm'`.
Если подключаетесь напрямую с отдельным ключом, добавьте к scp
`-i ~/.ssh/ИМЯ_КЛЮЧА`; для нестандартного порта у scp используется `-P ПОРТ`.
Настройки алиаса ~/.ssh/config применяются к ssh и scp автоматически.
Этот архив не переносит базу и API-ключи. Мы начнём с пустой базы; перенос старой
базы описан ниже.

**На ВМ:**

```bash
sudo install -d -o "$(id -u)" -g "$(id -g)" -m 750 /opt/macrodashboard
tar -xzf ~/macrodashboard-upload.tar.gz -C /opt/macrodashboard
cd /opt/macrodashboard
ls Dockerfile compose.yaml compose.local.yaml deploy/compose.caddy.yaml
sudo install -d -o 10001 -g 10001 -m 750 /opt/macrodashboard/data
```

Каталог data принадлежит пользователю контейнера. Если переносите уже существующие
файлы базы/PDF, им также нужны права UID/GID `10001:10001`.

## 5. Заполнить конфигурацию

**На ВМ, в /opt/macrodashboard:**

```bash
umask 077
test -f .env || cp .env.example .env
nano .env
```

Заполните реальные FRED_API_KEY, ESTAT_APP_ID, BEA_API_KEY. Сохранение в nano:
Ctrl+O, Enter, выход Ctrl+X. Без ключей часть источников не загрузится.

Создайте настройки Compose, если файл ещё отсутствует:

```bash
if [ ! -f compose.env ]; then
  cat > compose.env <<'EOF'
MACRO_BIND_ADDRESS=127.0.0.1
MACRO_PORT=8501
MACRO_HOST_DATA_DIR=/opt/macrodashboard/data
MACRO_UPDATE_INTERVAL=21600
MACRO_UPDATE_TIMEOUT=14400
MACRO_DOMAIN=macro.example.com
EOF
fi
nano compose.env
chmod 600 .env compose.env
```

Замените `macro.example.com` своим доменом. Остальные значения пока оставьте как есть.
`MACRO_BIND_ADDRESS=127.0.0.1` здесь намеренно: публикацией в интернете занимается Caddy.
Не используйте для этого сценария `deploy/compose.env.example` без изменения bind:
прежний шаблон рассчитан на прямой внешний доступ по IP:8501.

## 6. Собрать образ и запустить интерфейс

Определите в текущем Bash две функции. После нового SSH-входа их нужно определить
заново либо сохранить в ~/.bashrc. Они используют разные имена Compose-проектов:

```bash
cd /opt/macrodashboard
dc() {
  sudo docker compose --project-name macrodashboard \
    --env-file /opt/macrodashboard/compose.env \
    -f /opt/macrodashboard/compose.yaml \
    -f /opt/macrodashboard/compose.local.yaml "$@"
}
proxy() {
  sudo docker compose --project-name macrodashboard-proxy \
    --env-file /opt/macrodashboard/compose.env \
    -f /opt/macrodashboard/deploy/compose.caddy.yaml "$@"
}

dc config --quiet
proxy config --quiet
dc build web
dc up -d --no-build --wait --wait-timeout 180 web
dc ps
curl --fail http://127.0.0.1:8501/_stcore/health
dc exec -T -e MACRO_DATA_DIR=/tmp/macro-manual-check web python -m scripts.check_app
```

Сборка скачивает зависимости и может занять несколько минут. При ошибке не переходите
дальше: сначала проверьте текст ошибки. Health должен ответить `ok`, проверка приложения —
`Streamlit render OK`. Проверка рендера использует временную базу и не меняет рабочую.

**На компьютере, WSL / Bash — дополнительная проверка до настройки HTTPS:**

```bash
ssh -N -L 18501:127.0.0.1:8501 VM_USER@PUBLIC_IP
```

При подключении по алиасу замените `VM_USER@PUBLIC_IP` этим алиасом.
Пока это окно открыто, в браузере компьютера откройте `http://localhost:18501`.
Завершение туннеля — Ctrl+C. Внешний порт 8501 для этого открывать не нужно.

## 7. Запустить HTTPS

Перед этим DNS домена уже должен вести на ВМ, а TCP 80/443 — быть доступен извне.
Конфигурация `deploy/Caddyfile` перенаправляет запросы на `127.0.0.1:8501`.
Caddy автоматически получает сертификат, продлевает его и перенаправляет HTTP
на HTTPS; WebSocket поддерживает reverse_proxy.
[Автоматический HTTPS](https://caddyserver.com/docs/automatic-https),
[reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

**На ВМ:**

```bash
proxy pull
proxy run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
proxy up -d
proxy logs --tail=100 caddy
```

При первой выдаче сертификата подождите немного. Затем:

```bash
curl -I http://macro.example.com
curl -I https://macro.example.com
curl --fail https://macro.example.com/_stcore/health
```

Подставьте свой домен во всех трёх командах. HTTP должен перенаправляться на HTTPS,
HTTPS проходить проверку сертификата, health отвечать `ok`. Не добавляйте curl -k:
он скрывает ошибки сертификата. Проверьте адрес `https://ВАШ_ДОМЕН` также из браузера
компьютера; у панели домена не требуется отдельно покупать SSL-сертификат.

Сертификаты Caddy хранятся в постоянных Docker volumes. Не удаляйте их через down -v.
Сервис использует host networking Linux, поэтому эта конфигурация предназначена
для Ubuntu-ВМ, а не универсального запуска в Docker Desktop.

## 8. Включить обновление данных

После успешного запуска интерфейса и HTTPS:

```bash
dc up -d --no-build updater
dc logs -f --tail=100 updater
```

Ctrl+C завершает просмотр логов, контейнер продолжает работу. Updater выполняет
полную загрузку сразу, затем через 6 часов после окончания предыдущей. Один запуск
ограничен 4 часами. Часть источников может быть недоступна из сети ВМ: смотрите
`[ERROR]`, `[WARN]`, `[SAVE]` и даты показателей в приложении.
Код завершения scheduler 0 не доказывает успех всех источников.

При ручном обновлении остановите фоновый updater, чтобы не запускать два scheduler:

```bash
dc stop updater
dc exec -T web python scheduler.py cn us
dc start updater
```

Для полной ручной загрузки вместо `cn us` не передавайте группы. Базу отдельно
разворачивать не нужно: `/opt/macrodashboard/data/macro.db` используется обоими сервисами.
После перезагрузки ВМ Docker и контейнеры запускаются автоматически.

## 9. Перенести существующую базу при необходимости

Это альтернатива началу с пустой базы. Создавайте backup в том Python-окружении,
где уже работает проект и установлены его зависимости; WSL имеет отдельное
окружение от Windows. Не копируйте .venv между Windows и WSL.

**На компьютере, WSL / Bash, с установленными зависимостями проекта:**

```bash
cd /mnt/g/Edu/MacroDashboard
python3 -m scripts.backup /tmp/macro-transfer.db \
  && scp /tmp/macro-transfer.db VM_USER@PUBLIC_IP:~/macro-transfer.db
```

Если Python-окружение проекта есть только в Windows, создайте backup из него
в отдельный файл, затем отправьте этот файл через scp из WSL по пути /mnt/… .
Если перенос старой базы не нужен, пропустите этот раздел и оставьте загрузку updater.
Команда не перезаписывает уже существующую копию: при повторении выберите другое имя.
Не копируйте открытую рабочую macro.db обычным scp.

**На ВМ:**

Остановите оба писателя. Если старая база уже содержит полезные данные,
сначала сохраните её через backup, как в следующем разделе. Для замены:

```bash
dc stop web updater
if sudo test -e /opt/macrodashboard/data/macro.db; then
  sudo mv /opt/macrodashboard/data/macro.db "/opt/macrodashboard/data/macro.db.before-import-$(date +%Y%m%d-%H%M%S)"
fi
sudo rm -f /opt/macrodashboard/data/macro.db-wal /opt/macrodashboard/data/macro.db-shm
sudo install -o 10001 -g 10001 -m 640 ~/macro-transfer.db /opt/macrodashboard/data/macro.db
dc up -d --no-build --wait --wait-timeout 180
```

Не выполняйте перенос параллельно ручным обновлениям или деплою. PDF NIFD в backup
SQLite не входят; при необходимости перенесите каталог отдельно.

## 10. Обслуживание и ручные обновления кода

Быстрые команды на ВМ в shell с функциями dc и proxy:

```bash
dc ps
proxy ps
dc logs --tail=100 web updater
proxy logs --tail=100 caddy
df -h
sudo docker stats --no-stream
```

Резервная копия SQLite при работающем web:

```bash
dc exec -T web python -m scripts.backup
```

Копии находятся в `/opt/macrodashboard/data/backups`. Храните их также вне диска ВМ.
Ручная схема не создаёт backup перед релизом автоматически: выполняйте команду сами.

Для следующего релиза заново соберите и отправьте архив с компьютера. На ВМ
сначала выполните backup, затем:

```bash
dc stop updater
tar -xzf ~/macrodashboard-upload.tar.gz -C /opt/macrodashboard
dc build web
dc up -d --no-build --force-recreate --wait --wait-timeout 180
```

`.env` и compose.env архив не содержит, data/ сохраняется. Если сборка не прошла,
старый web продолжает работать; верните updater через `dc start updater` до исправления.
В ручной схеме нет автоматического отката релиза. На время пересоздания web будет
небольшой перерыв и сброс пользовательских сессий.

После изменения домена в compose.env:

```bash
proxy up -d --force-recreate
```

## 11. Если что-то не работает

| Симптом | Проверка |
| --- | --- |
| docker: command not found | Установка в разделе 2 |
| Cannot connect to Docker daemon | sudo systemctl status docker; sudo journalctl -u docker -n 50 |
| Port already allocated | sudo ss -lntp; другой сервис занял 80, 443 или 8501 |
| Ошибка сборки | Доступ ВМ к Docker Hub/PyPI, место на диске, текст ошибки pip |
| Permission denied в /app/data | UID/GID каталога и перенесённых файлов: 10001:10001 |
| localhost health работает, домен нет | A/AAAA, VPC 80/443, UFW, логи Caddy |
| Caddy не выдаёт сертификат | DNS на ВМ, доступность 80/443, CAA домена и сообщения ACME |
| HTTPS отвечает 502 | dc ps, dc logs web, curl http://127.0.0.1:8501/_stcore/health |
| Интерфейс пустой | Логи updater, API-ключи, доступность источников, даты метрик |

В этой конфигурации интерфейс доступен всем, кто знает домен; вход по паролю
не добавлен. Если нужен закрытый доступ, до публикации добавьте защиту в Caddy.
GitHub Actions, отдельный пользователь deploy и автоматические релизы подключаются
следующим этапом по [DEPLOYMENT.md](DEPLOYMENT.md); его функции команд отличаются
от ручной схемы. Перед переходом согласуйте пути и владельца env-файлов.
