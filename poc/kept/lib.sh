#!/usr/bin/env bash
# lib.sh — общие функции для stage_*.sh (доступы / деньги / данные).
# Подключается первой строкой каждого этапа:
#   . "$(dirname "$0")/lib.sh"
set -u

BASE="${BASE:-http://localhost:18081}"
JAR="${JAR:-/tmp/ow_stage.jar}"
REDFILE="/tmp/ow_req_redirect"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '\033[32m[+] %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
fail() { printf '\033[31m[-] %s\033[0m\n' "$*"; }

# say "строка" ["строка"...] — пояснение к шагу: что сейчас происходит и почему это опасно
say() { local l; for l in "$@"; do printf '    · %s\n' "$l"; done; }

# req "описание" <curl args...>
#   → печатает описание запроса,
#   ← печатает код ответа, редирект и начало тела,
#   тело ответа целиком уходит в stdout (для разбора),
#   URL редиректа пишется в файл $REDFILE (чтобы пережить подстановку $())
req() {
  local desc="$1"; shift
  printf '    \033[36m→ %s\033[0m\n' "$desc" >&2
  local tmp out code redir
  tmp=$(mktemp)
  out=$(curl -sS -o "$tmp" -w '%{http_code} %{redirect_url}' "$@")
  code=${out%% *}
  redir=${out#* }
  [ -z "$code" ] && code=000
  [ "$redir" = "$out" ] && redir=""
  printf '%s' "$redir" > "$REDFILE"
  printf '    \033[36m← HTTP %s' "$code" >&2
  [ -n "$redir" ] && printf ' redirect=%s' "$redir" >&2
  printf ' \033[0m' >&2
  head -c 240 "$tmp" | tr '\n\t' '  ' >&2
  [ "$(wc -c < "$tmp")" -gt 240 ] && printf '...' >&2
  printf '\n' >&2
  cat "$tmp"
  rm -f "$tmp"
}

# db "SQL" — запрос напрямую в базу стенда (пароль wallet/wallet из docker-compose.yml)
db() {
  docker exec office-wallet-main-db-1 psql -U wallet -d wallet -tAc "$1" 2>/dev/null
}

# login_as "логин" "пароль" [файл кук] — вход, код возврата 0 = сессия получена
login_as() {
  local login="$1" pass="$2" jar="${3:-$JAR}"
  rm -f "$jar"
  req "POST /login  login=$login (куки → $jar)" \
    -c "$jar" -b "$jar" -X POST \
    --data-urlencode "login=$login" --data-urlencode "password=$pass" \
    --data-urlencode "return=/" "$BASE/login" > /dev/null
  grep -q ow_session "$jar" 2>/dev/null
}

# balance — баланс текущего пользователя со стартовой страницы, в рублях
balance() {
  curl -s -b "$JAR" "$BASE/" | grep -o 'who-meta">[^<]*' | sed 's/.*· *//' | tr -d ' ₽'
}

# order_status N — номер и статус заказа из базы
order_status() { db "SELECT id||' '||status FROM orders WHERE id=$1;"; }

# new_order "комментарий" — создаёт заказ (товар за 450₽) с заданным item_comment:
# кладёт в корзину, делает котировку, подтверждает; ход запросов печатает в консоль,
# номер оформленного заказа отдаёт в stdout
new_order() {
  local comment="$1" q loc
  req "POST /cart/add  product_id=1 (товар за 450₽)" \
    -b "$JAR" -X POST -d 'product_id=1' "$BASE/cart/add" > /dev/null
  q=$(req "POST /checkout/quote  item_comment=$comment" \
        -b "$JAR" -X POST --data-urlencode "item_comment=$comment" \
        "$BASE/checkout/quote" \
        | grep -o 'name="quote_id" value="[0-9]*"' | grep -o '[0-9]*')
  req "POST /checkout/confirm  quote_id=$q" \
    -b "$JAR" -X POST -d "quote_id=$q" "$BASE/checkout/confirm" > /dev/null
  loc=$(cat "$REDFILE")
  echo "${loc##*/}"
}
