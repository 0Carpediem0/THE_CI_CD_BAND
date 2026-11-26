# -*- coding: utf-8 -*-
"""V-17. Раскрытие внутренней информации в сообщениях об ошибке.

handlers_money.go / handlers_accounting.go возвращают пользователю сырой текст
ошибки драйвера Postgres вместе с SQL-запросом. Это утечка схемы/СУБД (CWE-209)
и одновременно индикатор SQL-инъекции.
"""
from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("Раскрытие ошибок БД").parse_args()
    c = Client(a.base)
    c.login("ivanov", "workplace1")

    body = c.post_form("/transfer/new", {
        "recipient": "ivanov", "amount_rub": "not_a_number)", "memo": "x"})[2]
    txt = body.decode("utf-8", "replace")
    leaked = [s for s in ("pq:", "SELECT", "::bigint", "syntax error") if s in txt]
    banner(f"в ответе утекло: {leaked}")
    if not leaked:
        fail("ошибка БД не раскрыта")
    ok("сырой текст ошибки СУБД и SQL-запрос возвращаются пользователю")


if __name__ == "__main__":
    main()
