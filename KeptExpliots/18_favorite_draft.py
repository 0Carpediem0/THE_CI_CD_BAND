# -*- coding: utf-8 -*-
"""Черновик читается через избранное: favorite и unfavorite не смотрят на published.

    python 18_favorite_draft.py
"""
import time

from _http import Client, parser


def main():
    args = parser("Чтение чужого черновика через избранное").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    secret = f"FAVSECRET-{stamp}"
    author = client.register(f"favauth{stamp}", f"favauth{stamp}@poc.local", "Passw0rd!favauth")
    reader = client.register(f"favread{stamp}", f"favread{stamp}@poc.local", "Passw0rd!favread")
    status, created, blob = client.call(
        "POST",
        "/api/articles",
        token=author,
        body={
            "article": {
                "title": f"Secret fav {stamp}",
                "description": "hidden",
                "body": secret,
                "tagList": ["poc"],
                "published": False,
            }
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"черновик не создан: {status} {blob[:200]!r}")
    slug = created["article"]["slug"]

    status, _, blob = client.call("GET", f"/api/articles/{slug}")
    if status != 404:
        raise SystemExit(f"аноним и так видит черновик: {status}")

    status, favored, blob = client.call("POST", f"/api/articles/{slug}/favorite", token=reader)
    if status != 200 or favored["article"]["body"] != secret:
        raise SystemExit(f"favorite не отдал тело: {status} {blob[:300]!r}")
    if favored["article"]["favoritesCount"] < 1:
        raise SystemExit("счётчик избранного не вырос")

    status, cleared, blob = client.call("DELETE", f"/api/articles/{slug}/favorite", token=reader)
    if status != 200 or cleared["article"]["body"] != secret:
        raise SystemExit(f"unfavorite не отдал тело: {status} {blob[:300]!r}")

    print(f"OK slug={slug}")
    print(f"favorite вернул body={secret} favoritesCount={favored['article']['favoritesCount']}")
    print("unfavorite тоже вернул тело черновика")


if __name__ == "__main__":
    main()
