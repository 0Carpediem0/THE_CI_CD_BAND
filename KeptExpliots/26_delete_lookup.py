# -*- coding: utf-8 -*-
"""Чужое удаление не проходит, пока поиск записи успешен.

    python 26_delete_lookup.py
"""
import time

from _http import Client, parser


def main():
    args = parser("Граница удаления чужих статей и комментариев").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    author = client.register(f"delauth{stamp}", f"delauth{stamp}@poc.local", "Passw0rd!delauth")
    other = client.register(f"delother{stamp}", f"delother{stamp}@poc.local", "Passw0rd!delother")
    status, created, blob = client.call(
        "POST",
        "/api/articles",
        token=author,
        body={
            "article": {
                "title": f"Keep me {stamp}",
                "description": "stay",
                "body": f"KEEP-{stamp}",
                "tagList": ["poc"],
            }
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"статья не создана: {status} {blob[:200]!r}")
    slug = created["article"]["slug"]
    status, _, blob = client.call("DELETE", f"/api/articles/{slug}", token=other)
    if status != 403:
        raise SystemExit(f"чужая статья удалилась: {status} {blob[:200]!r}")
    status, comment, blob = client.call(
        "POST",
        f"/api/articles/{slug}/comments",
        token=author,
        body={"comment": {"body": f"keep-comment-{stamp}"}},
    )
    if status not in (200, 201):
        raise SystemExit(f"комментарий не создан: {status} {blob[:200]!r}")
    cid = comment["comment"]["id"]
    status, _, blob = client.call("DELETE", f"/api/articles/{slug}/comments/{cid}", token=other)
    if status != 403:
        raise SystemExit(f"чужой комментарий удалился: {status} {blob[:200]!r}")
    status, _, blob = client.call("DELETE", f"/api/articles/missing-{stamp}", token=other)
    if status != 200:
        raise SystemExit(f"пустой slug не дал 200: {status} {blob[:200]!r}")
    status, still, blob = client.call("GET", f"/api/articles/{slug}")
    if status != 200 or still["article"]["body"] != f"KEEP-{stamp}":
        raise SystemExit(f"статья пропала: {status} {blob[:200]!r}")
    print(f"OK чужие DELETE статьи и комментария {cid} -> 403, запись {slug} на месте")


if __name__ == "__main__":
    main()
