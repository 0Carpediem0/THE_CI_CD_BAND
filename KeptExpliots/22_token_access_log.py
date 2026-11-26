# -*- coding: utf-8 -*-
"""Токен в query попадает в обычный журнал Gin, без паники.

    python 22_token_access_log.py
"""
import subprocess
import time
from pathlib import Path

from _http import Client, parser


def main():
    args = parser("access_token в журнале успешного запроса").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    token = client.register(f"alog{stamp}", f"alog{stamp}@poc.local", "Passw0rd!alog")
    status, data, blob = client.call("GET", "/api/user?access_token=" + token)
    if status != 200 or not data or data["user"]["email"] != f"alog{stamp}@poc.local":
        raise SystemExit(f"запрос с access_token не вошёл: {status} {blob[:200]!r}")

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["docker", "compose", "logs", "--tail", "60", "backend"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or "docker compose logs не выполнился")
    hits = [line for line in completed.stdout.splitlines() if token in line and " 200 " in line]
    if not hits:
        raise SystemExit("в журнале нет успешной строки с этим токеном")
    print("OK токен в строке доступа со статусом 200")
    print(hits[-1].encode("ascii", "replace").decode())


if __name__ == "__main__":
    main()
