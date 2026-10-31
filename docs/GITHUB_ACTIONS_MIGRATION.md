# GitHub Actions для уже работающего MacroDashboard

[HTML-гайд с копированием команд](github-actions.html).

Начальная точка: приложение уже запущено по MANUAL_DEPLOYMENT.md, домен
macro-dashboard.ru направлен на ВМ 158.160.231.174, Caddy обслуживает HTTPS,
web и updater работают в Compose-проекте macrodashboard. Команды с компьютера
выполняются в WSL. Ничего заново устанавливать или переносить базу не нужно.

После настройки push в master запускает check → publish → deploy. GitHub собирает
и проверяет образ, публикует в GHCR, затем подключается к ВМ по SSH и заменяет
web/updater. Caddy — отдельный проект macrodashboard-proxy, он продолжает работу.
Короткий перерыв Streamlit и сброс сессий при замене web ожидаемы.

В командах PUBLIC_IP — 158.160.231.174, macro.example.com — macro-dashboard.ru,
VM_USER — ваш нынешний администратор SSH. В HTML значения IP и домена подставлены.
Новый пользователь deploy используется только для автоматизации. Личные ключи
и токены не отправляйте в чат и не коммитьте.

Не объединяйте ветку в master до завершения шагов 1–7: merge уже запускает выкладку.

## 1. Проверить текущий запуск и сделать backup

**На ВМ, в привычной SSH-сессии администратора:**

```bash
cd /opt/macrodashboard
sudo docker compose --project-name macrodashboard \
  --env-file compose.env -f compose.yaml -f compose.local.yaml ps
sudo docker compose --project-name macrodashboard-proxy \
  --env-file compose.env -f deploy/compose.caddy.yaml ps
curl --fail https://macro.example.com/_stcore/health
sudo docker compose --project-name macrodashboard \
  --env-file compose.env -f compose.yaml -f compose.local.yaml \
  exec -T web python -m scripts.backup
```

Health должен отвечать ok. Резервная копия появится в data/backups. Выполнение
backup не требует остановки приложения. Если один из шагов не прошёл, сначала
восстановите текущий ручной запуск; автоматизацию подключайте после этого.

Входящие TCP 22, 80 и 443 оставьте как сейчас. SSH с 0.0.0.0/0 доступен обычным
GitHub-hosted runners, отдельные изменения группы безопасности для них не нужны.
8501 остаётся закрытым снаружи. DNS и сертификаты не перенастраиваем.

## 2. Подготовить пользователя deploy и права

**На ВМ, администратор:**

```bash
id deploy >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
sudo touch /home/deploy/.ssh/authorized_keys
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
sudo install -d -o deploy -g deploy -m 750 /opt/macrodashboard/releases
sudo chown deploy:deploy /opt/macrodashboard
sudo chown deploy:deploy /opt/macrodashboard/.env /opt/macrodashboard/compose.env
sudo chmod 600 /opt/macrodashboard/.env /opt/macrodashboard/compose.env
sudo touch /opt/macrodashboard/.deploy.lock
sudo chown deploy:deploy /opt/macrodashboard/.deploy.lock
sudo apt-get install -y util-linux
sudo -iu deploy
```

Теперь команды идут от deploy. Не делайте рекурсивный chown всего проекта:
каталог data и файлы SQLite должны остаться у UID/GID 10001:10001.
Группа docker даёт административные возможности на ВМ; приватный ключ
автоматизации должен быть доступен только доверенным сопровождающим.

**На ВМ, пользователь deploy:**

```bash
whoami
docker info >/dev/null && echo 'Docker доступен'
test -r /opt/macrodashboard/.env && echo '.env читается'
test -r /opt/macrodashboard/compose.env && echo 'compose.env читается'
cd /opt/macrodashboard
nano compose.env
```

Сохраните текущие настройки. В compose.env должны остаться:

```dotenv
MACRO_BIND_ADDRESS=127.0.0.1
MACRO_PORT=8501
MACRO_HOST_DATA_DIR=/opt/macrodashboard/data
MACRO_UPDATE_INTERVAL=21600
MACRO_UPDATE_TIMEOUT=14400
MACRO_DOMAIN=macro.example.com
```

MACRO_IMAGE здесь не задавайте: digest выбирает workflow. Существующие API-ключи
в .env сохраняются. Если ключей ещё нет, оставьте значения пустыми: CI их не требует,
а ограничения обновления отдельных источников остаются прежними.

После смены владельца каталога обычный администратор может не иметь доступа к нему
без sudo. Для дальнейшей работы используйте deploy или команды через sudo.

## 3. Сохранить ручную версию для первого отката

Без этого шага скрипт не знает о прежнем ручном релизе: при ошибке первой выкладки
у него не будет зарегистрированной версии для отката. Зарегистрируем уже работающий
образ, не останавливая контейнеры и не пересоздавая базу.

**На ВМ, пользователь deploy:**

```bash
register_manual_baseline() {
  local root=/opt/macrodashboard
  local baseline="$root/releases/manual-baseline"
  local web_container running_image baseline_image

  if [ -e "$root/current" ] || [ -L "$root/current" ]; then
    echo 'current уже существует: повторная регистрация не требуется'
    return 0
  fi
  if [ -e "$baseline" ]; then
    echo 'manual-baseline уже существует: проверьте его перед повторением' >&2
    return 1
  fi

  web_container=$(docker ps -q \
    --filter label=com.docker.compose.project=macrodashboard \
    --filter label=com.docker.compose.service=web)
  if ! [[ "$web_container" =~ ^[a-f0-9]{12,64}$ ]]; then
    echo 'Не найден единственный работающий контейнер web' >&2
    return 1
  fi
  running_image=$(docker inspect --format '{{.Image}}' "$web_container") || return 1
  baseline_image="macrodashboard:manual-baseline-$(date -u +%Y%m%d%H%M%S)"
  docker image tag "$running_image" "$baseline_image" || return 1
  mkdir -m 700 "$baseline" || return 1
  cp "$root/compose.yaml" "$baseline/compose.yaml" || return 1
  printf '%s\n' "$baseline_image" > "$baseline/image" || return 1
  ln -s "$baseline" "$root/current" || return 1
  echo "Ручная версия сохранена: $baseline_image"
}
register_manual_baseline
```

Проверьте результат:

```bash
readlink -f /opt/macrodashboard/current
cat /opt/macrodashboard/current/image
```

Ожидаются каталог releases/manual-baseline и тег macrodashboard:manual-baseline-… .
Тег указывает на фактически работающий образ, а не на результат новой сборки.
Не удаляйте этот образ и каталог до успешного автоматического релиза и проверки
возможности отката. Обновлённый deploy.sh увидит baseline как предыдущий релиз,
остановит updater, создаст backup и при ошибке старта попытается вернуть его.

## 4. Создать отдельный SSH ключ для Actions

**На компьютере, WSL / Bash:**

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/macrodashboard-actions \
  -C github-actions-macrodashboard -N ''
scp ~/.ssh/macrodashboard-actions.pub VM_USER@PUBLIC_IP:~/macrodashboard-actions.pub
```

Если этот файл ключа уже существует, не перезаписывайте его без необходимости:
используйте существующую пару либо новое имя. При SSH-алиасе замените VM_USER@PUBLIC_IP
на привычный алиас. Этот ключ предназначен для входа GitHub на ВМ; это отдельная
пара от ключа, которым вы работаете с GitHub-репозиторием из WSL.

**На ВМ, в отдельной сессии прежнего администратора (не deploy):**

```bash
{ printf 'restrict '; cat ~/macrodashboard-actions.pub; } \
  | sudo tee -a /home/deploy/.ssh/authorized_keys >/dev/null
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

restrict запрещает forwarding и PTY, но оставляет выполнение команд, необходимое
Actions. Своё административное SSH-подключение и его ключ не меняйте.

## 5. Проверить SSH и сохранить host key ВМ

Вначале на ВМ узнайте настоящий отпечаток host key через уже проверенную SSH-сессию.

**На ВМ, администратор:**

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

**На компьютере, WSL / Bash:**

```bash
ssh-keyscan -t ed25519 PUBLIC_IP > ~/.ssh/macrodashboard-known-hosts
ssh-keygen -lf ~/.ssh/macrodashboard-known-hosts
```

Сравните отпечатки: они должны совпадать. Сохранённая строка понадобится для
DEPLOY_KNOWN_HOSTS. Не отключайте StrictHostKeyChecking и не делайте ssh-keyscan
заново внутри каждого workflow: доверенный ключ фиксируется один раз.

Только после совпадения проверьте новый доступ:

```bash
ssh -i ~/.ssh/macrodashboard-actions \
  -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$HOME/.ssh/macrodashboard-known-hosts" \
  deploy@PUBLIC_IP 'whoami; docker info >/dev/null && echo Docker_OK'
```

Должны появиться deploy и Docker_OK. Адрес для Actions — публичный IP, не ваш
локальный SSH-алиас: runner не имеет ~/.ssh/config из WSL.

## 6. Дать ВМ доступ к GHCR

GitHub Actions публикует образ в ghcr.io/aidweserd/macrodashboard с помощью
встроенного GITHUB_TOKEN. Отдельный токен для публикации не нужен.
Но для скачивания приватного образа на ВМ нужен read-only токен.

В своём аккаунте GitHub откройте Settings → Developer settings → Personal access
tokens → Tokens (classic) → Generate new token (classic). Выберите срок действия
и scope read:packages. Аккаунт должен иметь доступ к package; для организаций с SSO
может понадобиться авторизация токена. Fine-grained PAT для этого login не используйте.
[Аутентификация GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

**На ВМ, пользователь deploy:**

```bash
read -rsp 'GHCR read token: ' GHCR_TOKEN; echo
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u AIdWeserd --password-stdin
unset GHCR_TOKEN
```

Введите токен в приглашении терминала. Если токен принадлежит другому GitHub-логину,
замените AIdWeserd на него. Не используйте sudo для login: образ скачивается
пользователем deploy, а не root. Docker хранит login в домашнем каталоге deploy;
следите за сроком действия токена. Публичный package можно скачивать без login.

Первого образа ещё может не быть — это нормально. Он появится после publish.
Login проверяет аутентификацию; право скачивания конкретного package проверит pull.

## 7. Настроить GitHub secrets

В репозитории AIdWeserd/MacroDashboard откройте Settings → Environments,
создайте production. В Deployment branches разрешите только master. Для полностью
автоматической выкладки не задавайте required reviewers.

Если environments недоступны для приватного репозитория на вашем тарифе, удалите
только строку environment: production из job deploy в .github/workflows/pipeline.yaml.
Тогда сохраните secrets ниже в Settings → Secrets and variables → Actions →
Repository secrets. Условия ветки master и зависимость deploy от publish оставьте.
Вариант с environment использует Environment secrets внутри production.
[Доступность environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

| Secret | Значение |
| --- | --- |
| DEPLOY_HOST | PUBLIC_IP |
| DEPLOY_USER | deploy |
| DEPLOY_SSH_KEY | Полное содержимое приватного ~/.ssh/macrodashboard-actions |
| DEPLOY_KNOWN_HOSTS | Содержимое проверенного ~/.ssh/macrodashboard-known-hosts |

Для переноса приватного ключа из WSL в буфер обмена Windows:

**На компьютере, WSL / Bash:**

```bash
clip.exe < ~/.ssh/macrodashboard-actions
```

Вставьте в DEPLOY_SSH_KEY и сохраните. Включите BEGIN/END и все переводы строк.
Не вставляйте ключ в исходники, workflow или чат. Затем скопируйте known_hosts:

```bash
clip.exe < ~/.ssh/macrodashboard-known-hosts
```

Если clip.exe недоступен, откройте файлы локально и скопируйте содержимое вручную.
При SSH-порте 22 переменная DEPLOY_PORT не требуется. API-ключи FRED/BEA/e-Stat
и содержимое .env в GitHub secrets для этого workflow не нужны.

В Settings → Actions → General разрешите используемые actions и права packages:write
для job publish. Это право уже задано в YAML; отдельный PAT для push не добавляйте.
Политики организации могут дополнительно ограничивать публикацию пакетов.

## 8. Отправить подготовленные файлы в GitHub

Файлы деплоя пока могут быть незакоммичены. Перенос архива на ВМ не отправлял их
в GitHub. В CI должен попасть тот же рабочий код, который вы развернули вручную.
Проверьте содержимое перед коммитом; .env, compose.env, data и SSH-ключей в нём быть не должно.

**На компьютере, WSL / Bash:**

```bash
cd /mnt/g/Edu/MacroDashboard
git branch --show-current
git status --short
git add .github .streamlit deploy docs scripts tests \
  Dockerfile .dockerignore .gitattributes compose.yaml compose.local.yaml \
  requirements.txt requirements.lock app.py config.py src/build_summary.py \
  src/fetch_nifd_report.py src/AGENTS.md .gitignore AGENTS.md README.md
git diff --cached --stat
git diff --cached --name-only
git ls-files -- .env compose.env data '*.key' '*.pem' '*.db'
```

Последняя команда не должна показывать приватные файлы. Если показывает —
не продолжайте коммит, сначала исправьте состав индекса. Не используйте git add .:
в рабочем дереве могут быть посторонние макеты и черновики.

Если текущая ветка codex/deployment, после проверки:

```bash
git commit -m "Prepare container deployment and GitHub Actions"
git push -u origin codex/deployment
```

Если GitHub-SSH из WSL ещё не настроен, push может потребовать отдельной настройки
доступа к репозиторию: это не ключ macrodashboard-actions для входа на ВМ.
В GitHub создайте Pull Request из codex/deployment в master. Дождитесь зелёной
job check, проверьте изменения, затем merge. PR только проверяет код, не деплоит.

## 9. Дождаться первого автоматического релиза

После merge в master откройте Actions → Check, build and deploy. Пойдут три job:
check собирает и проверяет образ, publish отправляет его в GHCR, deploy обновляет ВМ.
На первом запуске установка зависимостей и сборка могут занять несколько минут.

Если publish успешен, но deploy получает denied/unauthorized, проверьте права
package в GitHub Packages и docker login пользователя deploy на ВМ. Первый package
может оказаться приватным независимо от видимости репозитория. Исправьте права
и повторите только упавшие jobs через Re-run failed jobs.

После первого успешного релиза:

**На ВМ, пользователь deploy:**

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
readlink -f current
readlink -f previous
curl --fail http://127.0.0.1:8501/_stcore/health
curl --fail https://macro.example.com/_stcore/health
```

current должен указывать на новый releases/COMMIT-RUN-ATTEMPT, previous —
на manual-baseline. Приложение доступно по прежнему домену; данные остаются
в data/macro.db, Caddy продолжает работать в отдельном Compose-проекте.
После автоматического релиза больше не используйте прежнюю dc из ручного гайда:
она выбирает локальный образ, а не текущий digest из GHCR.

## 10. Обновления по кнопке и откат

Теперь обычный релиз — push или merge в master. Для ручного повторного запуска:
Actions → Check, build and deploy → Run workflow → master → Run workflow.
Для появления кнопки workflow с workflow_dispatch должен находиться в default branch;
при другой default branch согласуйте её с master в настройках и условиях YAML.
[Ручной запуск Actions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

После нового SSH-входа определите dc из шага 9 заново. Для backup:

**На ВМ, пользователь deploy:**

```bash
dc exec -T web python -m scripts.backup
```

Скрипт автоматически сохраняет backup перед заменой зарегистрированного релиза,
а при ошибке запуска пытается вернуть предыдущие контейнеры. База автоматически
не откатывается. Не удаляйте current, previous и Docker-образы, которые они используют.

Для ручного отката к previous временно отключите workflow через GitHub Actions,
дождитесь завершения текущего запуска и сделайте backup. Затем:

```bash
rollback_previous() {
  local root=/opt/macrodashboard
  local target
  target=$(readlink -f "$root/previous") || return 1
  case "$target" in
    "$root"/releases/*) ;;
    *) echo 'Некорректный путь previous' >&2; return 1 ;;
  esac
  test -f "$target/image" && test -f "$target/compose.yaml" || return 1
  MACRO_IMAGE=$(cat "$target/image") docker compose \
    --project-name macrodashboard --project-directory "$root" \
    --env-file "$root/compose.env" -f "$target/compose.yaml" \
    up -d --no-build --force-recreate --wait --wait-timeout 180 || return 1
  ln -sfn "$target" "$root/current.next" || return 1
  mv -Tf "$root/current.next" "$root/current"
}
rollback_previous
```

Этот способ работает и для локального manual-baseline: в нём нет GHCR digest
и scripts/deploy.sh, поэтому обычная команда отката из старого DEPLOYMENT.md
для этого baseline не подходит. После отката проверьте сайт, исправьте/revert код
в master и включите workflow. Несовместимые изменения SQLite требуют отдельного
плана восстановления данных, а не только смены образа.

## 11. Если что-то не работает

| Проблема | Проверка |
| --- | --- |
| Нет workflow в Actions | Файл .github/workflows/pipeline.yaml закоммичен и попал в GitHub |
| Нет Run workflow | workflow_dispatch есть в default branch; сначала выполнен merge |
| Job ожидает approval | Required reviewers или правила environment production |
| Environment недоступен | Тариф/видимость репозитория; вариант Repository secrets из шага 7 |
| Permission denied publickey | Публичный ключ добавлен пользователю deploy; secret содержит приватную часть |
| Host key verification failed | DEPLOY_KNOWN_HOSTS соответствует IP/порту и проверенному host key ВМ |
| Permission denied в /opt/macrodashboard | deploy владеет root-каталогом, env-файлами, releases и .deploy.lock |
| Permission denied в /app/data | Каталог данных и SQLite принадлежат UID/GID 10001:10001 |
| GHCR unauthorized | PAT classic read:packages, доступ к package, login под deploy без sudo |
| check красный | Откройте первую ошибку теста/сборки; publish и deploy при этом не выполняются |
| После релиза снова локальный образ | Использована старая dc из ручного гайда; определите функцию из шага 9 |

Для диагностики присылайте текст ошибки и название упавшей job, без приватных
ключей, токенов и содержимого .env. Входящие правила SSH оставляем по вашему выбору;
DNS, сертификаты Caddy и открытие внешнего порта 8501 не являются частью перехода.
