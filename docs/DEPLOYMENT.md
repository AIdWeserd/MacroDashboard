# Деплой MacroDashboard на ВМ Яндекс Облака

Если приложение уже запущено вручную с Caddy и доменом, переходите по
[гайду миграции на GitHub Actions](GITHUB_ACTIONS_MIGRATION.md)
([HTML](github-actions.html)): он сохраняет ручной релиз для первого отката.

Для первого ручного запуска на Ubuntu с доменом и HTTPS используйте
[MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md). Эта инструкция ниже описывает
автоматические релизы через GitHub Actions и прямой доступ по IP:port.

[Визуальная инструкция в PDF](../output/pdf/macrodashboard-visual-deployment.pdf) -
11 страниц со схемой деплоя, порядком настройки ВМ и GitHub, портами и диагностикой.

После push в `master` GitHub Actions проверяет приложение, собирает Docker-образ,
публикует его в GitHub Container Registry (GHCR) и через SSH заменяет контейнеры
на вашей ВМ. ВМ остаётся прежней: новые контейнеры используют прежний каталог SQLite.
Адрес после настройки: `http://PUBLIC_IP:8501`.

Все команды для ВМ ниже выполняются в Bash на Ubuntu. Значения `PUBLIC_IP`,
`OWNER`, `REPOSITORY` замените своими. Приватные ключи и API-ключи не коммитьте.
Конфигурация рассчитана на GitHub.com, Ubuntu 24.04 LTS amd64 и Docker Compose v2
с поддержкой `up --wait` (2.20+). Домен и TLS для доступа по IP не требуются.

## 1. Подготовить ВМ и сеть

Создайте обычную ВМ Ubuntu 24.04 LTS x86_64 в Compute Cloud с публичным
статическим IPv4 и SSH-ключом администратора. Для начальной конфигурации разумно
выделить 2 vCPU, 4 ГБ RAM и SSD 30 ГБ; следите за памятью и ростом данных.
Сборка выполняется на GitHub, а не на ВМ. Статический IP сохранит адрес для SSH
и браузера при остановках ВМ.

Назначьте сетевому интерфейсу ВМ собственную группу безопасности VPC:

| Направление | Протокол и порт | Источник или назначение | Зачем |
| --- | --- | --- | --- |
| Входящий | TCP 22 | Ваш IP `/32` и адреса runner | Администрирование и деплой |
| Входящий | TCP 8501 | Ваш IP `/32` либо `0.0.0.0/0` для общего доступа | Streamlit |
| Исходящий | Любой | `0.0.0.0/0` | HTTPS/HTTP источников, GHCR, DNS, обновления ОС |

Обычные GitHub-hosted runners имеют меняющиеся адреса. Для простой схемы SSH
можно разрешить TCP 22 от `0.0.0.0/0`, оставив только вход по ключам. Если требуется
закрытый SSH, используйте runner со статическим исходящим IP или VPN и разрешите
его диапазон; стандартный runner не получит доступ через правило только с вашим IP.
Не устанавливайте self-hosted runner для непроверенных PR на production-ВМ.
[Правила VPC](https://yandex.cloud/ru/docs/vpc/operations/security-group-add-rule),
[адреса runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Проверьте, что firewall внутри ОС также разрешает нужные подключения. Если UFW
уже включён, сначала разрешите SSH, затем порт приложения:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 8501/tcp
```

Docker публикует порты через собственные правила firewall, которые могут обходить
обычные правила UFW. Ограничивайте внешний доступ группой безопасности VPC.
Не открывайте наружу Docker API (2375/2376); SQLite сетевого порта не имеет.
Смена внешнего порта описана ниже и требует также изменения правила VPC.

## 2. Установить Docker

Подключитесь как администратор: `ssh ADMIN_USER@PUBLIC_IP`. Для новой Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin util-linux
sudo systemctl enable --now docker
sudo docker run --rm hello-world
docker compose version
```

Если Docker уже установлен другим способом, сначала сверьте совместимость пакетов
с [официальной инструкцией Docker](https://docs.docker.com/engine/install/ubuntu/).
`util-linux` предоставляет `flock` для сериализации деплоев на ВМ.

## 3. Создать пользователя деплоя и каталоги

```bash
sudo adduser --disabled-password --gecos '' deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy -m 750 /opt/macrodashboard
sudo install -d -o deploy -g deploy -m 750 /opt/macrodashboard/releases
sudo install -d -o 10001 -g 10001 -m 750 /opt/macrodashboard/data
sudo install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
sudo -u deploy touch /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

Группа `docker` фактически даёт административные права на ВМ. Выдавайте доступ
к production environment только доверенным сопровождающим репозитория.

На своём компьютере создайте отдельный ключ для Actions:

```bash
ssh-keygen -t ed25519 -f ./macrodashboard-deploy -C github-actions-macrodashboard -N ''
```

Содержимое `macrodashboard-deploy.pub` добавьте одной строкой в
`/home/deploy/.ssh/authorized_keys` на ВМ. Можно начать строку с `restrict `,
чтобы запретить туннели, PTY и forwarding, сохранив выполнение команд.
Закрытый файл `macrodashboard-deploy` понадобится как GitHub secret.
Храните его за пределами проекта. Проверьте новый вход:

```bash
ssh -i ./macrodashboard-deploy deploy@PUBLIC_IP 'docker info >/dev/null && echo OK'
```

На ВМ создайте два файла от пользователя `deploy`:

```bash
sudo -iu deploy
umask 077
nano /opt/macrodashboard/.env
nano /opt/macrodashboard/compose.env
chmod 600 /opt/macrodashboard/.env /opt/macrodashboard/compose.env
```

Первый файл заполните по корневому `.env.example`: `FRED_API_KEY`, `ESTAT_APP_ID`,
`BEA_API_KEY`. Используется синтаксис env-файла Docker Compose, без `export`.
API-ключи не нужны GitHub Actions для сборки или деплоя и не входят в образ.

Второй файл скопируйте из `deploy/compose.env.example`:

```dotenv
MACRO_BIND_ADDRESS=0.0.0.0
MACRO_PORT=8501
MACRO_HOST_DATA_DIR=/opt/macrodashboard/data
MACRO_UPDATE_INTERVAL=21600
MACRO_UPDATE_TIMEOUT=14400
```

`MACRO_BIND_ADDRESS=0.0.0.0` открывает порт на интерфейсах ВМ. Значение по умолчанию
в Compose — `127.0.0.1`, поэтому без этой настройки снаружи подключиться нельзя.
Не задавайте `MACRO_IMAGE` в `.env` или `compose.env`: digest передаёт скрипт релиза.

## 4. Разрешить ВМ скачивать образ из GHCR

Для приватного образа создайте отдельный GitHub PAT **classic** со scope
`read:packages`. Учётная запись должна иметь право чтения package, а для организации
с SSO — соответствующую авторизацию. На ВМ под `deploy` выполните:

```bash
read -rsp 'GHCR read token: ' GHCR_TOKEN; echo
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_LOGIN --password-stdin
unset GHCR_TOKEN
```

Токен остаётся в конфигурации Docker пользователя `deploy`; следите за его сроком
действия и правами файла `~/.docker/config.json`. Не выполняйте login через sudo:
деплой использует учётные данные пользователя `deploy`.
Если package публичный, pull возможен без login. Видимость package настраивается
отдельно от репозитория; первый опубликованный package может быть приватным.
[Права и аутентификация GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## 5. Настроить GitHub Actions

В репозитории откройте **Settings → Environments**, создайте `production`.
В deployment branches разрешите только `master`. Для автоматического деплоя без
ручной паузы не включайте required reviewers. Защитите `master` проверкой `check`
и обязательным review перед merge, если работаете командой.

Для приватного репозитория environments требуют подходящего тарифа GitHub.
Если `production` недоступен, удалите `environment: production` из job `deploy`,
а перечисленные ниже secrets/variable задайте на уровне репозитория в
**Settings → Secrets and variables → Actions**. Условие ветки master в `publish`
сохраните: job deploy зависит от него. В этом варианте правил защиты environment
нет; ограничьте право изменения workflow доверенными сопровождающими.
[Доступность environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

В **production → Environment secrets** добавьте:

| Secret | Значение |
| --- | --- |
| `DEPLOY_HOST` | Статический публичный IPv4 или DNS-имя ВМ, без схемы и порта |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | Полный закрытый ключ, включая BEGIN/END и переводы строк |
| `DEPLOY_KNOWN_HOSTS` | Проверенная строка host key из `known_hosts` |

При нестандартном SSH-порте добавьте environment **variable** `DEPLOY_PORT`.
По умолчанию — `22`. Откройте этот порт в VPC и настройте sshd на ВМ заранее.

Чтобы получить `DEPLOY_KNOWN_HOSTS`, на доверенном компьютере выполните:

```bash
ssh-keyscan -t ed25519 PUBLIC_IP > vm_known_hosts
ssh-keygen -lf vm_known_hosts
```

Сравните отпечаток с `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`,
выполненным на ВМ через уже проверенное административное подключение.
Только после совпадения переносите содержимое `vm_known_hosts` в secret.
Для нестандартного порта используйте `ssh-keyscan -p PORT`, строка содержит
`[PUBLIC_IP]:PORT`. Автоматически доверять host key при каждом деплое нельзя.

В **Settings → Actions → General** разрешите используемые actions и выдачу
`GITHUB_TOKEN` прав `packages:write` для job `publish` (задано в workflow).
Личный токен для публикации не требуется. При политике организации с ограничениями
пакетов администратор должен разрешить публикацию/доступ Actions к package.
[Публикация через Actions](https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions).

Перенесите изменения этой ветки в `master` обычным review/merge. До этого можно
открыть PR, чтобы проверить `check` без секретов и деплоя. После merge:

1. `check` собирает образ, запускает offline-тесты, проверяет Streamlit и HTTP.
2. `publish` загружает именно этот образ в `ghcr.io/owner/repository:COMMIT_SHA`.
3. `deploy` копирует Compose и скрипт в отдельный каталог релиза на ВМ, скачивает
   образ по digest, делает backup при наличии предыдущего релиза и заменяет сервисы.

Первый приватный package может потребовать настройки прав после публикации;
после исправления повторите упавшую job. Запуск вручную: **Actions → Check, build
and deploy → Run workflow → master**. Запуск из иной ветки только проверяет код.
Если основная ветка называется `main`, замените `master` в push-фильтре, двух
условиях сохранения образа, условии `publish` и ограничении environment.

## 6. Проверить первый запуск

На ВМ войдите как `deploy` и определите вспомогательную функцию для текущего релиза:

```bash
cd /opt/macrodashboard
dc() {
  MACRO_IMAGE=$(cat /opt/macrodashboard/current/image) docker compose \
    --project-name macrodashboard --project-directory /opt/macrodashboard \
    --env-file /opt/macrodashboard/compose.env \
    -f /opt/macrodashboard/current/compose.yaml "$@"
}
dc ps
dc logs --tail=100 web updater
curl --fail http://127.0.0.1:8501/_stcore/health
```

Функция `dc` нужна также для следующих разделов; её можно добавить в `~/.bashrc`.
Откройте с вашего компьютера `http://PUBLIC_IP:8501`. Streamlit использует WebSocket;
прямой доступ через опубликованный порт поддерживает его без reverse proxy.
Docker автоматически поднимает сервисы после перезагрузки ВМ.

Новая база изначально пустая. `updater` выполняет полное обновление сразу при запуске,
затем через 6 часов после окончания предыдущего. Один запуск ограничен 4 часами;
после таймаута дочерние процессы завершаются и следующий запуск повторяется позже.
Источники могут быть недоступны из региона ВМ; успешный старт web не подтверждает
их доступность. `scheduler.py` продолжает работу после ошибок отдельных источников,
поэтому код `0` не доказывает полную загрузку. Проверяйте `[ERROR]`, `[WARN]`,
`[SAVE]` в логах и даты показателей в UI. Недельный snapshot создаёт полный запуск.

Для переноса имеющейся SQLite остановите локальные писатели либо создайте копию
через `python -m scripts.backup PATH_TO_COPY`, передайте копию на ВМ и при
остановленных **обоих** контейнерах положите её в
`/opt/macrodashboard/data/macro.db`. Восстановите владельца `10001:10001`.
Не копируйте открытую базу обычным `cp`/`scp`: сначала получите согласованный backup.

## 7. Обновление, порт и ручная загрузка

Обычный релиз — merge/push в `master`. Ключи и данные остаются на ВМ.
Смена env-параметров требует пересоздания контейнеров:

```bash
nano /opt/macrodashboard/compose.env
dc up -d --no-build --force-recreate --wait --wait-timeout 180
```

Например, `MACRO_PORT=8080` даст `http://PUBLIC_IP:8080`, при этом внутренний порт
останется 8501. Откройте TCP 8080 в VPC/firewall; старое правило 8501 уберите,
если оно больше не используется. При конфликте порта проверьте `sudo ss -lntp`.

Для ручного обновления сначала остановите фоновый updater:

```bash
dc stop updater
dc exec -T web python scheduler.py cn us
dc start updater
```

Для полного запуска без фильтра: `dc exec -T web python scheduler.py`.
Не запускайте ещё один updater или несколько ручных обновлений одновременно.
При остановке web сервис недоступен; при остановке только updater интерфейс
продолжает показывать сохранённые данные.

## 8. Резервные копии и восстановление

Перед заменой предыдущего релиза деплой вызывает SQLite backup API; копии хранятся
в `data/backups/`. Дополнительная согласованная копия при работающем приложении:

```bash
dc exec -T web python -m scripts.backup
```

Для регулярного backup добавьте в crontab пользователя `deploy`, например:

```cron
15 2 * * * flock -w 300 /opt/macrodashboard/.deploy.lock /bin/bash -c 'cd /opt/macrodashboard && MACRO_IMAGE=$(cat current/image) /usr/bin/docker compose --project-name macrodashboard --project-directory /opt/macrodashboard --env-file compose.env -f current/compose.yaml exec -T web python -m scripts.backup' >> /opt/macrodashboard/backup.log 2>&1
```

Время cron определяется часовым поясом ВМ (`timedatectl`). Контролируйте ошибки
backup и объём диска. Копии на том же диске не защищают от потери ВМ: выгружайте
их на другой носитель/Object Storage по своим правилам хранения. Автоматического
удаления старых копий и релизов нет; удаляйте их после проверки внешнего backup,
сохраняя `current`, `previous` и используемые ими Docker-образы.

Восстановление выбранной копии (администратор ВМ; замените `BACKUP_NAME.db`):

```bash
# В shell пользователя deploy, где определена dc:
dc stop web updater
sudo mv /opt/macrodashboard/data/macro.db /opt/macrodashboard/data/macro.db.before-restore
# После остановки всех писателей уберите оставшиеся sidecar-файлы прежней базы.
sudo rm -f /opt/macrodashboard/data/macro.db-wal /opt/macrodashboard/data/macro.db-shm
sudo cp /opt/macrodashboard/data/backups/BACKUP_NAME.db /opt/macrodashboard/data/macro.db
sudo chown 10001:10001 /opt/macrodashboard/data/macro.db
dc up -d --no-build --wait --wait-timeout 180
```

Не запускайте восстановление параллельно workflow деплоя; временно отключите
workflow в GitHub. Файл `macro.db.before-restore` не перезаписывайте повторно,
если он нужен для восстановления. Backup также содержит данные снимков сводки.

## 9. Откат релиза

При ошибке запуска скрипт пытается вернуть предыдущие контейнеры и оставляет
workflow красным. На первом деплое предыдущего релиза нет: неработающий стек
останавливается. Проверьте лог job, если сам откат не удался.
Ошибки скачивания образа/config до замены не останавливают работающий релиз.

Чтобы вручную вернуться к `previous`, временно отключите workflow, затем:

```bash
cd /opt/macrodashboard
release=$(readlink -f previous)
test -f "$release/image"
bash "$release/scripts/deploy.sh" "$release" "$(cat "$release/image")"
```

Повторное использование каталога здесь предназначено только для осознанного
ручного отката. После отката исправьте/откатите commit в `master`, затем включите
workflow. SQLite автоматически не восстанавливается: откат кода и восстановление
данных — отдельные операции. При будущих несовместимых миграциях схемы сначала
планируйте совместимость релизов и восстановление backup.

## 10. Диагностика и границы конфигурации

| Симптом | Проверка |
| --- | --- |
| SSH timeout | Публичный IP, TCP-порт, группа VPC для адреса runner, sshd |
| Host key verification failed | Проверенный `DEPLOY_KNOWN_HOSTS`, порт и смена host key |
| GHCR denied/unauthorized | Login под deploy, scope и срок PAT, права на package |
| Permission denied в `/app/data` | Владелец каталога и файлов на ВМ `10001:10001` |
| Локально curl работает, извне нет | `MACRO_BIND_ADDRESS=0.0.0.0`, VPC, внешний порт |
| Healthcheck зелёный, данных нет | Логи updater, API-ключи, сеть источников и даты в UI |
| Контейнер перезапускается/OOM | `dc logs`, `docker stats --no-stream`, RAM и диск ВМ |

Это одна ВМ с коротким перерывом при релизе. Балансировщик, домен, TLS,
аутентификация и масштабирование здесь не настроены. При доступе через
`0.0.0.0/0` любой пользователь сможет открыть приложение и его функции обновления;
для личного использования ограничьте порт своим IP. Если нужен доступ по домену
через HTTPS, добавьте reverse proxy с WebSocket и публикуйте Streamlit только на
localhost. Образ запускается без root, но не заменяет контроль доступа приложения.

Зависимости runtime фиксируются в `requirements.lock`, полученном в Linux/Python
3.12. Обновляйте его намеренно вместе с проверками. Внешние API могут менять
форматы и ограничения независимо от релиза приложения.
