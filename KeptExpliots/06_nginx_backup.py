# -*- coding: utf-8 -*-
"""Том media смонтирован в nginx только на чтение, файлы создаются с правами 0644.
Имя бэкапа не чистится, поэтому копия базы кладётся в /uploads и отдаётся autoindex.

    python 06_nginx_backup.py
"""
import time

from _http import Client, parser


def main():
    args = parser("Чтение бэкапа через nginx").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    name = f"bak{stamp}"
    email = f"{name}@poc.local"
    password = "Passw0rd!bak"
    token = client.register(name, email, password)
    token = client.promote(token, name, email, password)

    filename = f"media-backup-{stamp}.db"
    status, data, blob = client.call(
        "POST",
        "/api/user/backup",
        token=token,
        body={"backup": {"name": f"../uploads/{filename}"}},
    )
    if status != 200:
        raise SystemExit(f"backup не выполнился: {status} {blob[:300]!r}")

    status, _, body = client.call("GET", f"/uploads/{filename}")
    if status != 200 or not body.startswith(b"SQLite format 3"):
        raise SystemExit(f"nginx не отдал копию базы: {status} {body[:40]!r}")

    status, _, listing = client.call("GET", "/uploads/")
    page = listing.decode("utf-8", "replace")
    if filename not in page:
        raise SystemExit("autoindex не показывает файл бэкапа")
    print(f"OK /uploads/{filename} bytes={len(body)} sqlite, есть в autoindex")


if __name__ == "__main__":
    main()
