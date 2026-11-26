#!/usr/bin/env python3
"""Прогон проверок реестра и печать отдельных карточек OW-01…OW-44 по порядку.

Запуск: python3 poc/test_registry.py
OW-32/33 — короткие локальные DoS-тесты (временно занимают соединения/сокеты).
Каждая карточка выводит запросы, SQL/ответы, наблюдаемое изменение и статус.

Дополнительно каждая карточка сохраняется отдельным файлом в poc/shots/:
    poc/shots/OW-01.txt … OW-44.txt  — по файлу на уязвимость (удобно скринить)
    poc/shots/ALL.txt                 — все карточки одним файлом по порядку
    poc/shots/INDEX.md                — индекс: ID, заголовок, статус, файл
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


def _card_title(section):
    """Заголовок проверки: первая строка секции без служебных == и OW-ID."""
    first = section.splitlines()[0] if section else ""
    first = re.sub(r"^==\s*", "", first).rstrip("=").strip()
    first = OW_IN_TEXT.sub("", first).lstrip(" :-·").strip()
    return first[:70] or "(без заголовка)"


def _card_status(sections):
    """Статус карточки по маркерам: есть [+] и нет [-] — подтверждено."""
    body = "\n".join(sections)
    if "[-]" in body:
        return "ЕСТЬ [-]"
    if "[+]" in body:
        return "подтверждено"
    return "без маркера"


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

    # Отдельная папка со «скинами»: по файлу на уязвимость + общий сводный файл.
    shots_dir = os.path.join(HERE, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    index_rows = []

    missing = []
    for ow in OW_IDS:
        header = "#" * 96 + "\n# %s\n" % ow + "#" * 96
        print("\n" + header)
        sections = results[ow]
        body = []
        if not sections:
            missing.append(ow)
            line = "[!] ТЕСТ/АРТЕФАКТ НЕ НАЙДЕН. Галку Эксплоит не считать подтверждённой."
            print(line)
            body.append(line)
            title, status = "(тест не найден)", "НЕТ ТЕСТА"
        else:
            title = _card_title(sections[0])
            status = _card_status(sections)
            for idx, section in enumerate(sections, 1):
                prefix = ("\n--- проверка %d/%d ---" % (idx, len(sections))) if len(sections) > 1 else ""
                print(prefix)
                print(section)
                body.append(prefix + "\n" + section if prefix else section)

        card_text = "OFFICE WALLET · АРТЕФАКТ ПО РЕЕСТРУ\n" + header + "\n" + \
                    "\n".join(body).strip() + "\n"
        with open(os.path.join(shots_dir, "%s.txt" % ow), "w", encoding="utf-8") as fp:
            fp.write(card_text)
        index_rows.append((ow, title, status, "%s.txt" % ow))

    # Общий файл: все 44 карточки строго по порядку.
    with open(os.path.join(shots_dir, "ALL.txt"), "w", encoding="utf-8") as fp:
        for ow in OW_IDS:
            fp.write("\n" + "=" * 96 + "\n")
            fp.write(open(os.path.join(shots_dir, "%s.txt" % ow), encoding="utf-8").read())

    # Индекс: быстрый обзор, что в каком файле и чем закончилось.
    with open(os.path.join(shots_dir, "INDEX.md"), "w", encoding="utf-8") as fp:
        fp.write("# Скины уязвимостей Office Wallet\n\n")
        fp.write("Прогон: `python3 poc/test_registry.py` · карточки OW-01…OW-44 по порядку.\n\n")
        fp.write("| ID | Проверка | Статус | Файл |\n|---|---|---|---|\n")
        for ow, title, status, fname in index_rows:
            fp.write("| %s | %s | %s | [%s](%s) |\n" % (ow, title, status, fname, fname))
        fp.write("\nСводный файл всех карточек: [ALL.txt](ALL.txt)\n")

    print("\n" + "=" * 96)
    print("Скины сохранены: %s/ (44 файла + ALL.txt + INDEX.md)" % shots_dir)
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
