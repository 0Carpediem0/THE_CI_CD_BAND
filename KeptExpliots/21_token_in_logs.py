# -*- coding: utf-8 -*-
"""Битый JSON на регистрации роняет NewValidatorError.
Gin в debug пишет в журнал строку запроса вместе с access_token.

    python 21_token_in_logs.py
"""
import subprocess
import time
from pathlib import Path

from _http import Client, parser


def main():
    args = parser("Утечка access_token в журнал при панике").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    token = client.register(f"log{stamp}", f"log{stamp}@poc.local", "Passw0rd!log")
    status, _, blob = client.call(
        "POST",
        "/api/users?access_token=" + token,
        raw=b'{"user":{"username":1,"email":"a@b.co","password":"password1"}}',
        content_type="application/json",
    )
    if status != 500:
        raise SystemExit(f"паника не случилась, статус {status}: {blob[:200]!r}")

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["docker", "compose", "logs", "--tail", "80", "backend"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or "docker compose logs не выполнился")
    hits = [line for line in completed.stdout.splitlines() if token in line]
    if not hits:
        raise SystemExit("в последних строках журнала токена нет")
    print("OK токен есть в журнале backend")
    print(hits[-1].encode("ascii", "replace").decode())


if __name__ == "__main__":
    main()
