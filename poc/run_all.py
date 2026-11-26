#!/usr/bin/env python3
"""
run_all.py — запускает всю цепочку по категориям, по порядку.

    python3 poc/run_all.py          # доступы + деньги + данные + XSS
    python3 poc/run_all.py --dos    # + медленные заголовки и отказ БД
                                     #   (портит сервис примерно на 45 секунд)

Каждый этап — отдельный скрипт, запускается и сам:
    python3 poc/stage_access.py     # Доступы: пароли, роли, обход блокировки, перебор
    python3 poc/stage_money.py      # Деньги: инъекция, replay, возвраты, чужие заказы
    python3 poc/stage_data.py       # Данные: RCE, дампы, файлы, почта, чужие операции
    python3 poc/stage_xss.py        # XSS: обходы санитайзера и кража сессии

Перед каждым запросом печатается, что отправляем (→) и что пришло (←),
перед каждым шагом — пояснение, что сейчас происходит и почему это опасно.
Пошаговая расшифровка каждого пункта — в poc/STEPS.md, теория — в SECURITY.md.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("BASE", "http://localhost:18081")

STAGES = [
    "stage_access.py",
    "stage_money.py",
    "stage_data.py",
    "stage_xss.py",
]


def banner(text):
    print("\n\033[1m########## %s ##########\033[0m" % text)


def run(script, *args):
    """Запускает питон-скрипт тем же интерпретатором; код возврата = его код."""
    return subprocess.call([sys.executable, os.path.join(HERE, script), *args])


def main():
    for stage in STAGES:
        banner(stage)
        code = run(stage)
        if code != 0:
            print("\033[31mэтап %s упал, дальше не идём\033[0m" % stage)
            return code

    if "--dos" in sys.argv[1:]:
        banner("DoS: 03_slowloris + 04_unlimited_db_pool")
        code = run("03_slowloris.py", BASE, "30", "300")
        if code != 0:
            return code
        code = run("04_unlimited_db_pool.py", BASE, "150", "45")
        if code != 0:
            return code

    print("\n\033[1mГотово.\033[0m Что делал каждый шаг — в poc/STEPS.md, "
          "разбор уязвимостей — в SECURITY.md")
    print("Сброс стенда: docker compose down -v && docker compose up -d --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
