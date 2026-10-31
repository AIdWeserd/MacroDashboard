# Контекст GitHub Actions

`workflows/pipeline.yaml`: PR/push → check; успешный master → publish проверенного
образа → deploy через production. Ручной запуск другой ветки только проверяет код.
Переход с уже работающей ВМ: docs/GITHUB_ACTIONS_MIGRATION.md (HTML: github-actions.html).

- Не использовать pull_request_target для исполнения кода PR.
- Только publish имеет packages:write; push использует GITHUB_TOKEN.
- Деплой использует проверенный SSH host key и digest, а не latest.
- Не пересобирать образ после тестов, не включать API-ключи в build context.
- Сохранять таймауты и сериализацию деплоев. На ВМ дополнительный flock.
- Переименование master согласовывать со всеми условиями workflow и docs.
