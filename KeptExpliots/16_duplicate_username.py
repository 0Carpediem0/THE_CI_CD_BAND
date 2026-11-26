# -*- coding: utf-8 -*-
"""F-16. Одинаковый username разрешён. Файл экспорта один на имя,
вторая учётка читает email первой через GET /api/user/export.
"""
import time

from _http import Client, parser


def main():
    p = parser("Чужой экспорт при совпадении username")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    username = f"dup{stamp}"
    first_email = f"dup1{stamp}@poc.local"
    second_email = f"dup2{stamp}@poc.local"
    first = client.register(username, first_email, "Passw0rd!dup1")
    second = client.register(username, second_email, "Passw0rd!dup2")
    status, _, raw = client.call("POST", "/api/user/export", token=first)
    if status != 201:
        raise SystemExit(f"экспорт первой учётки не создан: {status} {raw[:200]!r}")
    status, data, raw = client.call("GET", "/api/user/export", token=second)
    if status != 200 or not data or data.get("user", {}).get("email") != first_email:
        raise SystemExit(f"вторая учётка не прочитала чужой экспорт: {status} {raw[:300]!r}")
    print(f"OK {username}: вторая учётка получила email {first_email}")


if __name__ == "__main__":
    main()
