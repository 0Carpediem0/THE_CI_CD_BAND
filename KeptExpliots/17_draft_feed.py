# -*- coding: utf-8 -*-
"""F-17. Лента подписок не фильтрует published=false.
Публичный список по автору статью прячет, но articlesCount её считает.
"""
import time

from _http import Client, parser


def main():
    p = parser("Черновик виден подписчику")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    author_name = f"author{stamp}"
    secret = f"DRAFT-SECRET-{stamp}"
    author = client.register(author_name, f"{author_name}@poc.local", "Passw0rd!author")
    reader = client.register(f"reader{stamp}", f"reader{stamp}@poc.local", "Passw0rd!reader")
    status, data, raw = client.call(
        "POST",
        "/api/articles",
        token=author,
        body={
            "article": {
                "title": f"Hidden draft {stamp}",
                "description": "private",
                "body": secret,
                "tagList": ["poc"],
                "published": False,
            }
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"черновик не создан: {status} {raw[:200]!r}")
    slug = data["article"]["slug"]
    status, _, _ = client.call("GET", f"/api/articles/{slug}")
    if status != 404:
        raise SystemExit(f"аноним открыл черновик, статус {status}")
    status, listed, _ = client.call("GET", f"/api/articles?author={author_name}")
    if status != 200 or listed["articles"] or listed["articlesCount"] < 1:
        raise SystemExit(f"счётчик не выдал скрытую статью: {listed}")
    status, _, raw = client.call("POST", f"/api/profiles/{author_name}/follow", token=reader)
    if status != 200:
        raise SystemExit(f"подписка не прошла: {status} {raw[:200]!r}")
    status, feed, raw = client.call("GET", "/api/articles/feed", token=reader)
    bodies = [item["body"] for item in (feed or {}).get("articles", [])]
    if status != 200 or secret not in bodies:
        raise SystemExit(f"лента не содержит черновик: {status} {raw[:300]!r}")
    print(f"OK slug={slug} в списке автора articlesCount={listed['articlesCount']} при пустом массиве")
    print(f"OK лента подписчика вернула {secret}")


if __name__ == "__main__":
    main()
