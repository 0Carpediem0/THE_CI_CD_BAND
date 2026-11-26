# -*- coding: utf-8 -*-
"""Страница входа встраивается в чужой iframe: нет X-Frame-Options и CSP.
HTML-пример: KeptExpliots/24_clickjack.html (открыть с другого порта, не с 8080).

    python 24_clickjack.py
"""
import urllib.request

from _http import Client, parser


def main():
    args = parser("Проверка заголовков против встраивания").parse_args()
    client = Client(args.base)
    status, _, blob = client.call("GET", "/login?redirectTo=javascript:document.title='XSS-OK'")
    req = urllib.request.Request(client.base + "/login")
    with urllib.request.urlopen(req, timeout=10) as resp:
        headers = {k.lower(): v for k, v in resp.headers.items()}
    missing = [name for name in ("x-frame-options", "content-security-policy") if name not in headers]
    if status != 200 or blob[:15].lower() != b"<!doctype html>" and b"<html" not in blob[:200].lower():
        pass
    if len(missing) != 2:
        raise SystemExit(f"защита от фрейма уже есть: {headers}")
    print("OK нет X-Frame-Options и Content-Security-Policy")
    print("страница входа открывается внутри iframe с другого порта")
    print("пример: KeptExpliots/24_clickjack.html на http://127.0.0.1:8765/")


if __name__ == "__main__":
    main()
