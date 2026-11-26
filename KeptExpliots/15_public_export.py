# -*- coding: utf-8 -*-
"""F-15. Экспорт пишется в private/<username>.json,
nginx отдаёт его как /exports/<username>.json без сессии.
Плюс autoindex на /uploads/.
"""
import time

from _http import Client, parser


def main():
    p = parser("Публичный экспорт и листинг загрузок")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    name = f"export{stamp}"
    email = f"{name}@poc.local"
    token = client.register(name, email, "Passw0rd!export")
    status, _, raw = client.call("POST", "/api/user/export", token=token)
    if status != 201:
        raise SystemExit(f"экспорт не создан: {status} {raw[:200]!r}")
    status, data, raw = client.call("GET", f"/exports/{name}.json")
    if status != 200 or not data or data.get("user", {}).get("email") != email:
        raise SystemExit(f"анонимно файл не прочитан: {status} {raw[:200]!r}")
    status, _, listing = client.call("GET", "/uploads/")
    text = listing.decode("utf-8", "replace")
    if status != 200 or "Index of /uploads/" not in text:
        raise SystemExit(f"autoindex не открылся: {status} {text[:120]!r}")
    print(f"OK анонимный /exports/{name}.json email={email}")
    print("OK /uploads/ autoindex")


if __name__ == "__main__":
    main()
