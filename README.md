# Office Wallet

Корпоративный кошелёк сотрудников (Go + PostgreSQL + Mailpit + внутренний notify-mock).

Репозиторий содержит только **wallet**: приложение, mock, compose и Helm-чарт.

## Реестр уязвимостей

Сверка с кодом на текущем дереве (ноябрь 2026). Строки OW-01…OW-36 — не дубликаты при общем CWE (разные поверхности). Пересечения: OW-07 ⊂ OW-40; OW-10 ← OW-39; OW-12 = XSS в истории и чаевых.

**Импакт:** ☑ — подтверждён вред по PoC или достижимому пути; ☐ — не подтверждён / теоретический / снят. Пересмотрены: OW-04, OW-24, OW-25, OW-36, OW-44 → ☐.

**Фикс:** ☑ — исправление описано в [docs/FIXES.md](docs/FIXES.md) и/или уже есть в коде. **Готово:** ☑ — внедрено в код и принято; ☐ — описание есть, в коде ещё нет (или нужна стендовая проверка).

| ID | Приоритет / CWE | Уязвимость | Место | Эксплоит | Импакт | Фикс | Артефакты | Готово | Основание |
| --- | --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| OW-01 | Высокий / CWE-190 | Переполнение при расчёте покупки | `handlers_shop.go` → `checkoutQuote` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; `dbSum` + `tipKop` без проверки переполнения |
| OW-02 | Высокий / CWE-841 | Оформление по несогласованной котировке | `handlers_shop.go` → `checkoutConfirm` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; сумма из котировки, позиции из живой корзины |
| OW-03 | Высокий / CWE-362 | Неатомарное оформление | `handlers_shop.go` → `checkoutConfirm` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; списание / `used` / INSERT без транзакции |
| OW-04 | Высокий / CWE-639 | Доступ к чужому заказу и его отмене | `handlers_shop.go` → `orderView` / `orderCancel` | ☑ | ☐ | ☑ | ☑ | ☐ | FIXES.md; владелец проверяется; атомарность — OW-06 |
| OW-05 | Высокий / CWE-20 | Некорректный размер возврата | `handlers_shop.go` → `orderReturn` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; `refund = total * qty` без границ |
| OW-06 | Высокий / CWE-362 | Неатомарные возвраты и отмены | `handlers_shop.go` → `orderCancel` / `orderReturn` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; статус, баланс и журнал раздельны |
| OW-07 | Средний / CWE-352 | Изменение статуса при GET | `handlers_shop.go` → `orderReceived`; `order.html` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; GET меняет статус; см. OW-40 |
| OW-08 | Критический / CWE-78 | Выполнение команд в превью | `handlers_shop.go` → `orderPreview` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; превью экранирует текст |
| OW-09 | Высокий / CWE-22 | Чтение файлов через экспорт | `handlers_shop.go` → `statementExport` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; CSV из операций пользователя |
| OW-10 | Средний / CWE-862 | Доступ к внутренней цене по общему токену | `handlers_shop.go` → `apiSupplyPricing` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; только канал, не роль; канал — OW-39 |
| OW-11 | Низкий / CWE-252 | Неактивные товары и ложный успех корзины | `handlers_shop.go` → `cartAdd` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; нет проверки `active` |
| OW-12 | Высокий / CWE-79 | Небезопасный вывод HTML | `handlers_money.go` → `history` / `tipsReceived`; `history.html` / `tips_view.html` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; `QRaw` / `TipHTML` |
| OW-13 | Высокий / CWE-862 | Избыточный доступ к операциям | `handlers_money.go` → `apiOpsFeed` / `operation` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; feed выдаёт grant на чужие операции |
| OW-14 | Критический / CWE-89 | SQL-инъекция при вводе суммы | `handlers_money.go` → `transferNew`; `render.go` → `parseRubToKop` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; сумма вне SQL |
| OW-15 | Высокий / CWE-362 | Неатомарное подтверждение перевода | `handlers_money.go` → `transferConfirm` | ☑ | ☑ | ☑ | ☑ | ☐ | В коде + FIXES.md; гонки на стенде не гонялись |
| OW-16 | Высокий / CWE-362 | Неатомарные чаевые | `handlers_money.go` → `tipsNew` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; баланс и журнал без транзакции |
| OW-17 | Высокий / CWE-294 | Повтор платежа и несвязанные параметры | `handlers_money.go` → `payReplay`; `pay.js` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; нет nonce/TTL; `to_login` |
| OW-18 | На проверке / CWE-918 | Проверка URL только до редиректа | `handlers_money.go` → `doNotify` | ☑ | ☐ | ☑ | ☑ | ☐ | FIXES.md; запрет следования внешним редиректам |
| OW-19 | Средний / CWE-20 | Отрицательное кассовое пополнение | `handlers_accounting.go` → `cashierTopup` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; отклонять `amount <= 0` |
| OW-20 | Высокий / CWE-841 | Возврат денег в обработчике выдачи | `handlers_accounting.go` → `cashierFulfill` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; только `paid → delivered` |
| OW-21 | Критический / CWE-89 | SQL-инъекция в сверке | `handlers_accounting.go` → `accountingReconcile` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; фильтры параметризованы |
| OW-22 | Средний / CWE-252 | Неатомарная бухгалтерская корректировка | `handlers_accounting.go` → `accountingAdjust` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; одна транзакция |
| OW-23 | Средний / CWE-307 | Неограниченные попытки входа | `handlers_auth.go` → `login` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; rate limit |
| OW-24 | Низкий / CWE-252 | Ошибки хеширования при регистрации | `handlers_auth.go` → `register` | ☑ | ☐ | ☑ | ☑ | ☐ | FIXES.md; не игнорировать ошибку bcrypt |
| OW-25 | Средний / CWE-330 | Предсказуемый запасной источник кода | `handlers_auth.go` → `randomSMSCode` | ☑ | ☐ | ☑ | ☑ | ☐ | FIXES.md; отказ при сбое `crypto/rand` |
| OW-26 | Высокий / CWE-640 | Сброс пароля без срока и атомарного погашения | `handlers_auth.go` → `passwordReset` / `passwordForgot` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; TTL есть, добавить лимит попыток |
| OW-27 | Высокий / CWE-862 | Общая почта доступна сотрудникам | `handlers_auth.go` → `mailBox` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; outbox только admin |
| OW-28 | Высокий / CWE-285 | Роль из cookie и обход блокировки | `auth.go` → `currentUser` / `requireUser` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; проверять `blocked` в сессии |
| OW-29 | Высокий / CWE-613 | Сессии без отзыва и срока на сервере | `auth.go` → `signSession` / `setSession` / `clearSession` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; expiry / revoke |
| OW-30 | Средний / CWE-1004 | Недостаточные флаги cookie | `auth.go` → `setSession`; `handlers_money.go` → `apiOpsFeed` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; Secure + HttpOnly для grant |
| OW-31 | Высокий / CWE-190 | Переполнение при переводе рублей в копейки | `render.go` → `parseRubToKop`; `render_test.go` | ☑ | ☑ | ☑ | ☑ | ☐ | В коде + FIXES.md; нужен прогон тестов в CI |
| OW-32 | Средний / CWE-400 | Неограниченный пул БД | `server.go` → `New` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; лимиты пула заданы |
| OW-33 | Средний / CWE-400 | Нет HTTP-таймаутов | `server.go` → `ListenAndServe` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; таймауты заданы |
| OW-34 | Высокий / CWE-319 | Транспорт и секреты PostgreSQL | `docker-compose.yml`; `cmd/wallet/main.go`; Helm values | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; secret + TLS |
| OW-35 | Критический / CWE-321 | Демонстрационные HMAC-ключи | `server.go` → `New`; `static/wallet.js` / `legacy-sync.js` / `pay.js` | ☑ | ☑ | ☑ | ☑ | ☑ | В коде; demo-ключи отклоняются |
| OW-36 | Высокий / CWE-532 | Секреты в логах CI | `ci/app-credentials.sh` | ☑ | ☐ | ☑ | ☑ | ☐ | FIXES.md; ротация старых секретов |
| OW-37 | Высокий / CWE-862 | Журнал `/ops/journal` без разграничения ролей | `handlers_accounting.go` → `opsJournal` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; только admin |
| OW-38 | Средний / CWE-78 | Shell в обработчике уведомлений | `handlers_money.go` → `notifySettings` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; убрать `exec.Command` |
| OW-39 | Средний / CWE-200 | Утечка supply-канала через каталог | `handlers_shop.go` → `apiCatalog`; `legacy-sync.js` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; не отдавать канал в catalog |
| OW-40 | Средний / CWE-352 | Нет CSRF-защиты на POST | формы в `templates/*.html`; `route` без проверки Origin | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; CSRF-токен + Origin |
| OW-41 | Средний / CWE-693 | Нет CSP / frame / nosniff заголовков | `render.go` → `render`; `templates/layout.html` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; security headers |
| OW-42 | Средний / CWE-250 | Контейнер приложения от root | `app/Dockerfile` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; `USER` non-root |
| OW-43 | Низкий / CWE-209 | Ошибки БД в ответах клиенту | `handlers_auth.go` → `login`; `handlers_money.go` → `history` / `tipsReceived` / `transferNew` | ☑ | ☑ | ☑ | ☑ | ☐ | FIXES.md; нейтральные 500 |
| OW-44 | Средний / CWE-345 | Подмена `op_type` при подтверждении перевода | `handlers_money.go` → `transferConfirm`; `transfer_confirm.html` | ☑ | ☐ | ☑ | ☑ | ☐ | FIXES.md; `op_type` только из draft |

[Дополнительные наблюдения и находки по зависимостям](docs/Уязвимости%20Office%20Wallet.md) · [План фиксов](docs/FIXES.md)

## Состав

| Путь | Назначение |
|------|------------|
| `app/` | Go-приложение (Dockerfile) |
| `mock/` | Внутренний HTTP-сервис уведомлений |
| `docker-compose.yml` | Локальный запуск |
| `charts/office-wallet/` | Helm-чарт для Kubernetes |
| `docs/student/` | Краткое описание для практики |

## Локально (Docker Compose)

Перед запуском добавьте в локальный `.env` переменные `SESSION_KEY` и
`PAYMENT_KEY`. Для каждой возьмите отдельное значение из `openssl rand -hex 32`.

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
| `SESSION_KEY` / `PAYMENT_KEY` | Ключи подписи | Обязательные, без значений по умолчанию |
