# -*- coding: utf-8 -*-
"""Пароли seed лежат в слое образа contest-seed:local, не только в исходниках.

    python 25_seed_image.py
"""
import json
import subprocess


def main():
    completed = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", "contest-seed:local", "/seed/data/seed.json"],
        capture_output=True,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.decode("utf-8", "replace") or "образ contest-seed:local не прочитан")
    data = json.loads(completed.stdout.decode("utf-8"))
    users = data.get("users") or []
    if not users or "password" not in users[0]:
        raise SystemExit("в образе нет паролей пользователей")
    print(f"OK в слое образа {len(users)} учёток с паролями")
    for user in users:
        print(f"{user['username']}\t{user['email']}\t{user['password']}")


if __name__ == "__main__":
    main()
