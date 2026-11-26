# Office Wallet

Корпоративный кошелёк сотрудников (Go + PostgreSQL + Mailpit + внутренний notify-mock).

Репозиторий содержит только **wallet**: приложение, mock, compose и Helm-чарт.

## Состав

| Путь | Назначение |
|------|------------|
| `app/` | Go-приложение (Dockerfile) |
| `mock/` | Внутренний HTTP-сервис уведомлений |
| `docker-compose.yml` | Локальный запуск |
| `charts/office-wallet/` | Helm-чарт для Kubernetes |
| `docs/student/` | Краткое описание для практики |

## Локально (Docker Compose)

```bash
docker compose up -d --build
```

| Сервис | URL |
|--------|-----|
| Приложение | http://localhost:18081 |
| Почта (Mailpit) | http://localhost:18025 |

Mailpit — **отдельный** сервис `mail` (образ `axllent/mailpit`), не входит в образ приложения.

Учётка для практики: `ivanov` / `workplace1` (остальные — в `docs/instructor/wallet.md`).

Остановка:

```bash
docker compose down
```

Сброс БД (пересоздать volume):

```bash
docker compose down -v
docker compose up -d --build
```

## Kubernetes (Helm)

### 1. Собрать образы

```bash
# Linux/macOS
./scripts/build-images.sh

# Windows PowerShell
./scripts/build-images.ps1
```

Переменные:

- `TAG` — тег образа (по умолчанию `1.0.0`)
- `REGISTRY` — префикс registry (опционально)
- `LOAD_KIND=1` — сразу загрузить образы в kind

Пример для kind:

```bash
LOAD_KIND=1 ./scripts/build-images.sh
# или
./scripts/build-images.ps1 -LoadKind
```

Для удалённого кластера — собрать, запушить в registry и указать `image.*.repository` / `tag` в values.

### 2. Установить чарт

```bash
kubectl create namespace office-wallet

helm upgrade --install office-wallet ./charts/office-wallet \
  -n office-wallet \
  -f ./charts/office-wallet/values-kind.yaml
```

Состав релиза:

| Компонент | Описание |
|-----------|----------|
| `*-app` | приложение |
| `*-postgres` | PostgreSQL |
| `*-mock` | notify-mock |
| `*-mail` | **Mailpit отдельным Deployment** (`mail.enabled=true` по умолчанию) |

Чтобы не ставить Mailpit из чарта (внешний SMTP/UI):

```bash
helm upgrade --install office-wallet ./charts/office-wallet \
  -n office-wallet \
  --set mail.enabled=false \
  --set app.mailHost=smtp.example.local \
  --set app.mailUi=https://mail.example.local
```

### 3. Доступ

С `values-kind.yaml` (ingress nginx):

| Сервис | URL |
|--------|-----|
| Приложение | http://office-wallet.local |
| Mailpit | http://office-wallet-mail.local |

Без ingress:

```bash
kubectl -n office-wallet port-forward svc/office-wallet-app 18081:8080
kubectl -n office-wallet port-forward svc/office-wallet-mail 18025:8025
```

### 4. Удаление

```bash
helm uninstall office-wallet -n office-wallet
kubectl delete namespace office-wallet
```

## Переменные окружения приложения

| Переменная | Назначение | По умолчанию |
|------------|------------|--------------|
| `DATABASE_URL` | PostgreSQL DSN | `postgres://wallet:wallet@db:5432/wallet?sslmode=disable` |
| `MAIL_HOST` / `MAIL_PORT` | SMTP Mailpit | `mail` / `1025` |
| `MAIL_UI` | Ссылка на UI почты | `http://localhost:18025` |
| `INTERNAL_NOTIFY_HOST` | Хост notify-mock | `notify-mock` |
| `PUBLIC_BASE` | Внешний URL приложения | `http://localhost:18081` |
| `SESSION_KEY` / `PAYMENT_KEY` | Ключи подписи | см. compose |
