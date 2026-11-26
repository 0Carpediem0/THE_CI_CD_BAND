#!/usr/bin/env bash
# run_all.sh — запускает всю цепочку по категориям, по порядку.
#
#   sh poc/run_all.sh          # доступы + деньги + данные
#   sh poc/run_all.sh --dos    # + медленные заголовки и отказ БД (портит сервис на ~45с)
#
# Каждый этап — отдельный скрипт, запускается и сам:
#   sh poc/stage_access.sh     # Доступы: пароли, роли, обход блокировки, перебор
#   sh poc/stage_money.sh      # Деньги: инъекция, replay, возвраты, чужие заказы
#   sh poc/stage_data.sh       # Данные: RCE, дампы, файлы, почта, чужие операции
#
# Перед каждым запросом печатается, что отправляем (→) и что пришло (←),
# перед каждым шагом — пояснение, что сейчас происходит и почему это опасно.
# Пошаговая расшифровка каждого пункта — в poc/STEPS.md, теория — в SECURITY.md.
set -u
cd "$(dirname "$0")" || exit 1
BASE="${BASE:-http://localhost:18081}"

for s in stage_access.sh stage_money.sh stage_data.sh; do
  printf '\n\033[1m########## %s ##########\033[0m\n' "$s"
  sh "$s" || { printf '\033[31mэтап %s упал, дальше не идём\033[0m\n' "$s"; exit 1; }
done

if [ "${1:-}" = "--dos" ]; then
  printf '\n\033[1m########## DoS: 03_slowloris + 04_unlimited_db_pool ##########\033[0m\n'
  python3 03_slowloris.py "$BASE" 30 300 || exit 1
  python3 04_unlimited_db_pool.py "$BASE" 150 45 || exit 1
fi

printf '\n\033[1mГотово.\033[0m Что делал каждый шаг — в poc/STEPS.md, разбор уязвимостей — в SECURITY.md\n'
printf 'Сброс стенда: docker compose down -v && docker compose up -d --build\n'
