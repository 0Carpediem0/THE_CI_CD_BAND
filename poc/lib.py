#!/usr/bin/env python3
"""
lib.py — общие функции для stage_*.py (доступы / деньги / данные / XSS).

Подключается первой строкой каждого этапа:
    from lib import *

Что умеет:
    step/ok/info/fail/say — подсветка консоли и пояснения «·» к каждому шагу;
    req(...)               — один запрос: печатает «→ описание» и «← HTTP код,
                             редирект, начало тела», отдаёт объект Resp;
    login_as(...)          — вход, возвращает Client со своей кукой;
    db(...)                — запрос в базу стенда через docker exec … psql;
    balance(...)           — баланс текущего пользователя со стартовой страницы;
    new_order(...)         — весь цикл заказа: корзина → котировка → подтверждение.

Всё только ходит по HTTP и по базе — код приложения не меняется.
"""
import hashlib
import hmac
import http.cookiejar
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE", "http://localhost:18081")
DB_CONTAINER = os.environ.get("DB_CONTAINER", "office-wallet-main-db-1")

BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"
RESET = "\033[0m"


# ---------------------------------------------------------------- вывод ----
def step(*args):
    print("\n%s== %s ==%s" % (BOLD, " ".join(args), RESET))


def ok(*args):
    print("%s[+] %s%s" % (GREEN, " ".join(args), RESET))


def fail(*args):
    print("%s[-] %s%s" % (RED, " ".join(args), RESET))


def info(*args):
    print("    " + " ".join(args))


def say(*args):
    """Пояснение к шагу: что сейчас происходит и почему это опасно."""
    for line in args:
        print("    · %s" % line)


def artifact(title, *lines):
    """Печатает компактный блок проверяемого результата PoC."""
    print("    ┌─ АРТЕФАКТ · %s" % title)
    for line in lines:
        print("    │ %s" % line)
    print("    └─")


# --------------------------------------------------------------- клиент ----
class _Tracer(urllib.request.HTTPRedirectHandler):
    """Запоминает код и адрес последнего редиректа, чтобы напечатать их,
    плюс заголовки Set-Cookie самого редиректа (именно он и ставит куку)."""

    def __init__(self):
        self.last = None
        self.set_cookie = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.last = (code, newurl)
        self.set_cookie = headers.get_all("Set-Cookie") or []
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    """Отдельная сессия: свои куки, свой редирект-трекер, свой opener."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.tracer = _Tracer()
        self.opener = urllib.request.build_opener(
            self.tracer, urllib.request.HTTPCookieProcessor(self.jar)
        )

    def session(self):
        """Значение ow_session или None, если вход не состоялся."""
        for c in self.jar:
            if c.name == "ow_session":
                return c.value
        return None

    def has_httponly(self):
        """Стоит ли у куки сессии флаг HttpOnly (у стенда — не стоит)."""
        for c in self.jar:
            if c.name == "ow_session":
                return c.has_nonstandard_attr("HttpOnly")
        return False


_ANON = Client()


# --------------------------------------------------------------- запрос ----
class Resp:
    """Ответ сервера: статус, тело, адрес после редиректов."""

    __slots__ = ("status", "text", "url", "redirect", "headers")

    def __init__(self, status, text, url, redirect, headers=None):
        self.status = status
        self.text = text
        self.url = url
        self.redirect = redirect
        self.headers = dict(headers or {})

    def __contains__(self, needle):
        return needle in self.text

    def __str__(self):
        return self.text

    def search(self, pattern, flags=0):
        return re.search(pattern, self.text, flags)

    def findall(self, pattern, flags=0):
        return re.findall(pattern, self.text, flags)


def _snippet(text, limit=240):
    s = text[:limit].replace("\n", " ").replace("\t", " ")
    s = "".join(ch if (ch.isprintable() or ch == " ") else "." for ch in s)
    return s + ("..." if len(text) > limit else "")


def req(desc, path, client=None, data=None, params=None, cookie=None,
        headers=None, quiet=False, timeout=60):
    """
    Один запрос к стенду.

      desc   — что отправляем, печатается после «→»;
      path   — путь (/history) или полный URL;
      client — Client со своими куками; None = анонимный запрос;
      data   — dict → POST с form-кодированием; None = GET;
      params — dict → GET-параметры, закодируются как в --data-urlencode;
      cookie — строка Cookie целиком (для поддельных кук, важнее кук клиента);
      quiet  — не печатать след (полезно, когда ответ не показываем).

    Отдаёт Resp: .status, .text, .url, .redirect, плюс `in` и .search().
    """
    client = client or _ANON
    url = path if path.startswith("http") else BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    method = "POST" if data is not None else "GET"

    if not quiet:
        print("    %s→ %s%s" % (CYAN, desc, RESET))

    hdrs = {}
    if cookie is not None:
        hdrs["Cookie"] = cookie
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")

    request = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    client.tracer.last = None
    client.tracer.set_cookie = []
    status, raw, final, response_headers = 0, b"", url, {}
    try:
        with client.opener.open(request, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read()
            final = resp.geturl()
            response_headers = dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read() or b""
        final = e.geturl()
        response_headers = dict(e.headers.items())
    except Exception as e:  # сетевая ошибка — тоже печатаем, как падал curl
        if not quiet:
            print("    %s← ошибка: %s%s" % (RED, e, RESET))
        return Resp(0, str(e), url, None)

    redirect = client.tracer.last
    text = raw.decode("utf-8", "replace")

    if not quiet:
        # при редиректе печатаем его код (302), как это делал curl -w
        shown = redirect[0] if redirect else status
        line = "    %s← HTTP %d" % (CYAN, shown)
        if redirect:
            line += " redirect=%s" % redirect[1]
        line += "%s " % RESET
        print(line + _snippet(text))

    return Resp(status, text, final, redirect, response_headers)


# ------------------------------------------------------------- сервисы ----
_CMD_TAG = re.compile(
    r"^(?:INSERT \d+ \d+|UPDATE \d+|DELETE \d+|SELECT \d+|MOVE \d+|FETCH \d+|"
    r"COPY \d+|TRUNCATE TABLE|CREATE \w+|DROP \w+|ALTER \w+|GRANT|REVOKE)\b")


def _rows(out):
    """
    Отбирает строки результата: psql печатает в конце ещё и командную метку
    («INSERT 0 1», «UPDATE 1»). Для наглядности метку показываем, но в
    возвращаемое значение она не попадает — иначе из неё собирается кривой SQL.
    """
    lines = out.splitlines()
    while lines and _CMD_TAG.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).strip()


def db(sql, quiet=False):
    """
    Запрос в базу стенда: docker exec … psql -tAc (пароль wallet/wallet).
    Печатает сам SQL и ответ базы — так видно, что и где мы поменяли.
    Возвращает только строки результата (без командной метки psql).
    """
    if not quiet:
        print("    %s→ SQL%s %s" % (CYAN, RESET, sql))
    p = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "wallet", "-d", "wallet",
         "-tAc", sql],
        capture_output=True, text=True,
    )
    out = p.stdout.strip()
    if p.returncode != 0:
        fail("psql: %s" % (p.stderr.strip() or "пустой ответ"))
        return out
    if not quiet:
        body = "\n    ".join(out[:400].splitlines()) or "(пусто)"
        print("    %s← psql%s %s" % (CYAN, RESET, body))
    return _rows(out)


def login_as(login, password):
    """Вход под учёткой. Возвращает Client с кукой или None."""
    c = Client()
    req("POST /login  login=%s (куки → Client)" % login, "/login", client=c,
        data={"login": login, "password": password, "return": "/"})
    return c if c.session() else None


def balance(client):
    """Баланс текущего пользователя со стартовой страницы, в рублях (строка)."""
    r = req("GET /  (баланс со стартовой страницы)", "/", client=client,
            quiet=True)
    m = r.search(r'who-meta">(.*?)</div>')
    if not m:
        return None
    return m.group(1).split("·")[-1].replace(" ", "").replace("₽", "").strip()


def order_status(oid):
    """«<id> <status>» заказа из базы."""
    return db("SELECT id||' '||status FROM orders WHERE id=%s;" % oid)


def user_balance_kop(login):
    """Баланс пользователя в копейках — точное значение из БД."""
    return db("SELECT balance_kop FROM users WHERE login='%s';" % login.replace("'", "''"))


def set_cookie_lines(client):
    """Сырые заголовки Set-Cookie с последнего запроса (именно они ставят куку)."""
    return list(client.tracer.set_cookie)


def new_order(comment, client):
    """
    Оформляет заказ на 450₽ с комментарием item_comment.
    Возвращает номер заказа или None (если котировку не подтвердили).
    """
    req("POST /cart/add  product_id=1 (товар за 450₽)", "/cart/add",
        client=client, data={"product_id": "1"})
    r = req("POST /checkout/quote  item_comment=%s" % comment, "/checkout/quote",
            client=client, data={"item_comment": comment})
    m = r.search(r'name="quote_id" value="(\d+)"')
    if not m:
        return None
    r = req("POST /checkout/confirm  quote_id=%s" % m.group(1), "/checkout/confirm",
            client=client, data={"quote_id": m.group(1)})
    m = re.search(r"/orders/(\d+)", r.url)
    return m.group(1) if m else None


def sign(key, msg):
    """HMAC-SHA256 hex — так же сервер считает подписи сессий и платежей."""
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


# ключи стенда (в старом коде они лежат в статике, их же отдаёт /proc/1/environ)
SESSION_KEY = os.environ.get("SESSION_KEY", "office-wallet-session-key")
PAYMENT_KEY = os.environ.get("PAYMENT_KEY", "office-wallet-pay-key")
