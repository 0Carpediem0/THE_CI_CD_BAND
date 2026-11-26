#!/usr/bin/env python3
"""Прогон проверок реестра и печать отдельных карточек OW-01…OW-44 по порядку.

Запуск: python3 poc/test_registry.py
OW-32/33 — короткие локальные DoS-тесты (временно занимают соединения/сокеты).
Каждая карточка выводит запросы, SQL/ответы, наблюдаемое изменение и статус.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("BASE", "http://localhost:18081")
OW_IDS = ["OW-%02d" % i for i in range(1, 45)]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HEADING = re.compile(r"^==.*==\s*$")
OW_IN_TEXT = re.compile(r"OW-\d{2}")


def collect_sections(text):
    text = ANSI.sub("", text)
    sections = []
    current = []
    for line in text.splitlines():
        if HEADING.match(line.strip()) and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    result = {ow: [] for ow in OW_IDS}
    for section in sections:
        first = section.splitlines()[0] if section else ""
        ids = list(dict.fromkeys(OW_IN_TEXT.findall(first)))
        for ow in ids:
            if ow in result:
                result[ow].append(section)
    return result


def run(script, args=()):
    command = [sys.executable, os.path.join(HERE, script), *args]
    proc = subprocess.run(command, cwd=os.path.dirname(HERE),
                          capture_output=True, text=True, errors="replace")
    return proc.returncode, proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")


def main():
    # The suites mutate only disposable test records/data and restore what they change.
    jobs = [
        ("stage_access.py", ()),
        ("stage_money.py", ()),
        ("stage_data.py", ()),
        ("stage_xss.py", ()),
        ("stage_registry_extra.py", ()),
        # Short, explicit DoS probes required for OW-32/33; effects last seconds only.
        ("03_slowloris.py", (BASE, "6", "120")),
        ("04_unlimited_db_pool.py", (BASE, "110", "8")),
    ]
    results = {ow: [] for ow in OW_IDS}
    suite_errors = []
    for script, args in jobs:
        code, output = run(script, args)
        parsed = collect_sections(output)
        for ow in OW_IDS:
            results[ow].extend(parsed[ow])
        if code:
            suite_errors.append("%s exited %d" % (script, code))

    print("=" * 96)
    print("OFFICE WALLET · АРТЕФАКТЫ ПО РЕЕСТРУ · 44 ОТДЕЛЬНЫЕ КАРТОЧКИ")
    print("Запросы, HTTP/SQL и проверяемый результат внутри каждой карточки.")
    print("=" * 96)
    missing = []
    for ow in OW_IDS:
        print("\n" + "#" * 96)
        print("# %s" % ow)
        print("#" * 96)
        sections = results[ow]
        if not sections:
            missing.append(ow)
            print("[!] ТЕСТ/АРТЕФАКТ НЕ НАЙДЕН. Галку Эксплоит не считать подтверждённой.")
            continue
        for idx, section in enumerate(sections, 1):
            if len(sections) > 1:
                print("\n--- проверка %d/%d ---" % (idx, len(sections)))
            print(section)
    print("\n" + "=" * 96)
    print("ИТОГ")
    print("карточек с найденным тестом: %d/44" % (44 - len(missing)))
    if missing:
        print("без отдельного тестового блока: %s" % ", ".join(missing))
    if suite_errors:
        print("ошибки запуска: " + "; ".join(suite_errors))
    else:
        print("все тестовые скрипты завершились с exit=0; внутри карточек смотри [+]/[-]/INCONCLUSIVE")
    print("=" * 96)
    # Missing tests and failed suite process are real failures; individual inconclusive PoCs
    # are intentionally visible in their card and never silently treated as a pass.
    return 1 if missing or suite_errors else 0


if __name__ == "__main__":
    sys.exit(main())
