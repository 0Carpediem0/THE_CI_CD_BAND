#!/usr/bin/env python3
"""Проверки реестра, которым нужны отдельные точные артефакты OW-10/18/20/22/36-44."""
from lib import *  # noqa: F401,F403
import json
import tempfile
import threading
import time


def snippet(text, limit=240):
    return re.sub(r"\s+", " ", text[:limit]) + ("..." if len(text) > limit else "")


def card(ow, title):
    step("%s · %s" % (ow, title))


def post_raw(path, data, cookie, barrier=None):
    if barrier:
        barrier.wait()
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        BASE + path, data=body, headers={"Cookie": "ow_session=" + cookie}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.geturl(), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.geturl(), error.read().decode("utf-8", "replace")


def concurrent_posts(path, data, cookie, count=8):
    barrier = threading.Barrier(count)
    results = []
    lock = threading.Lock()

    def worker():
        result = post_raw(path, data, cookie, barrier)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(40)
    return results


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client = login_as("ivanov", "workplace1")
    if not client:
        fail("OW extra tests: не удалось войти")
        return 1

    card("OW-35", "секрет подписи сессии извлекается из публичной статики")
    wallet_js = req("GET /static/wallet.js", "/static/wallet.js")
    legacy_js = req("GET /static/legacy-sync.js", "/static/legacy-sync.js")
    key_parts = re.search(r'keyParts:\s*\[([^\]]+)\]', wallet_js.text)
    tail_parts = re.search(r'__SK_TAIL__\s*=\s*\[([^\]]+)\]', legacy_js.text)
    if key_parts and tail_parts:
        def js_strings(raw):
            return "".join(re.findall(r'"([^"]*)"', raw))
        recovered = js_strings(key_parts.group(1)) + js_strings(tail_parts.group(1))
        forged = sign(recovered, "6:admin")
        admin_probe = req("GET /admin/secrets с OW-35 HMAC", "/admin/secrets",
                          cookie="ow_session=ow.6.admin." + forged)
        if recovered == SESSION_KEY and "Админ Кошелька" in admin_probe.text:
            artifact("OW-35 · публичная статика раскрыла ключ подписи",
                     "GET /static/wallet.js → HTTP %s; keyParts=%s" %
                     (wallet_js.status, key_parts.group(1)),
                     "GET /static/legacy-sync.js → HTTP %s; tail=%s" %
                     (legacy_js.status, tail_parts.group(1)),
                     "собран SESSION_KEY=%s; поддельная admin cookie → HTTP %s" %
                     (recovered, admin_probe.status))
            ok("секрет из публичных JS позволяет подписать admin cookie")
        else:
            fail("ключ из статики не совпал или поддельная cookie отклонена")
    else:
        fail("не найдены сегменты SESSION_KEY в публичной статике")

    card("OW-26", "reset code не истекает и не гасится после использования")
    victim_hash = db("SELECT password_hash FROM users WHERE login='adminw'")
    forgot = req("POST /password/forgot login=adminw", "/password/forgot", client=client,
                 data={"login": "adminw"})
    reset_meta = db("SELECT id||'|'||sms_code FROM password_resets WHERE user_id="
                    "(SELECT id FROM users WHERE login='adminw') ORDER BY id DESC LIMIT 1")
    if reset_meta:
        reset_id, reset_code = reset_meta.split("|", 1)
        db("UPDATE password_resets SET created_at='2000-01-01', used=FALSE WHERE id=%s" % reset_id)
        stale_pass = "OW26-Stale-" + str(int(time.time()))
        stale = req("POST /password/reset with 26-year-old reset code rid=%s" % reset_id,
                    "/password/reset", data={"rid": reset_id, "sms_code": reset_code,
                                              "password": stale_pass})
        stale_login = login_as("adminw", stale_pass)
        used_after = db("SELECT used FROM password_resets WHERE id=%s" % reset_id)
        reuse_pass = stale_pass + "-reuse"
        reuse = req("POST same /password/reset rid=%s again" % reset_id,
                    "/password/reset", data={"rid": reset_id, "sms_code": reset_code,
                                              "password": reuse_pass})
        reuse_login = login_as("adminw", reuse_pass)
        if stale_login and used_after == "t" and not reuse_login:
            artifact("OW-26 · просроченный reset принят",
                     "password_resets.created_at=2000-01-01; запрос не проверил срок",
                     "первый POST /password/reset → HTTP %s; новый пароль принят" % stale.status,
                     "после первого использования used=%s; повторный POST → HTTP %s, второй пароль отклонён" %
                     (used_after, reuse.status))
            ok("старый reset не истекает; после использования код помечается использованным")
        else:
            fail("OW-26 не подтверждено: stale login=%s used=%s reuse login=%s" %
                 (bool(stale_login), used_after, bool(reuse_login)))
        db("UPDATE users SET password_hash='%s' WHERE login='adminw'" % victim_hash)
        db("DELETE FROM password_resets WHERE id=%s" % reset_id)
        db("DELETE FROM sms_outbox WHERE rid=%s" % reset_id)
        db("DELETE FROM mail_outbox WHERE body LIKE '%%rid=%s%%'" % reset_id)
        info("OW-26: исходный password_hash восстановлен; reset/outbox записи удалены")
    else:
        fail("OW-26 setup: password reset row не создан, HTTP forgot=%s" % forgot.status)

    card("OW-27", "сотрудник читает письма чужих адресатов")
    mailbox = req("GET /mail as employee", "/mail", client=client)
    recipients = re.findall(r"<td>([^<]+@[^<]+)</td>", mailbox.text)
    own_email = db("SELECT email FROM users WHERE login='ivanov'")
    foreign = [address.strip() for address in recipients if address.strip() != own_email]
    if mailbox.status == 200 and foreign:
        artifact("OW-27 · общий outbox показывает чужие письма",
                 "GET /mail under ivanov <%s> → HTTP %s" % (own_email, mailbox.status),
                 "чужие recipient в HTML: %s" % ", ".join(foreign[:6]))
        ok("employee видит сообщения не своего почтового адреса")
    else:
        fail("чужие recipient не найдены: %s" % recipients[:6])

    # OW-10 / OW-39: раскрытый токен из двух частей каталога позволяет получить cost.
    card("OW-39", "канал supply раскрывается в каталоге")
    catalog = req("GET /api/catalog (JSON + заголовок второй половины канала)",
                  "/api/catalog", client=client)
    try:
        ch_first = json.loads(catalog.text)["meta"]["ch_pref"]
        ch_second = catalog.headers.get("X-Wallet-Sync-Part", "")
        channel = ch_first + ch_second
    except Exception:
        channel = ""
    if catalog.status == 200 and channel:
        artifact("OW-39 · собран секретный supply-channel",
                 "GET /api/catalog → HTTP %s" % catalog.status,
                 "JSON meta.ch_pref=%s; X-Wallet-Sync-Part=%s" % (ch_first, ch_second),
                 "собранный X-Wallet-Channel=%s" % channel)
        ok("две части внутреннего токена доступны без отдельной авторизации")
    else:
        fail("не удалось собрать supply-channel из ответа каталога")

    card("OW-10", "внутренняя цена доступна с токеном из каталога")
    no_channel = req("GET /api/v2/supply/pricing без токена", "/api/v2/supply/pricing",
                     client=client)
    priced = req("GET /api/v2/supply/pricing с X-Wallet-Channel", "/api/v2/supply/pricing",
                 client=client, headers={"X-Wallet-Channel": channel}) if channel else Resp(0, "", "", None)
    if no_channel.status == 403 and priced.status == 200 and "cost_kop" in priced.text:
        artifact("OW-10 · раскрытие закупочной цены",
                 "без токена: HTTP %s; с токеном из OW-39: HTTP %s" %
                 (no_channel.status, priced.status),
                 "ответ содержит cost_kop/supplier_note: %s" % snippet(priced.text, 260))
        ok("общий supply-token открыл внутренние цены обычной сессии")
    else:
        fail("ценовой endpoint не раскрыл данные: HTTP %s / %s" %
             (no_channel.status, priced.status))

    # OW-18 / OW-38: адрес разрешён, redirect-following уводит запрос на status.
    card("OW-18", "проверка URL обходится внутренним redirect")
    notify_url = "http://notify-mock/hooks/verify"
    notify = req("POST /settings/notify notify_url=%s" % notify_url,
                 "/settings/notify", client=client, data={"notify_url": notify_url})
    journal_row = db("SELECT count(*) FROM notify_settings WHERE user_id="
                     "(SELECT id FROM users WHERE login='ivanov') AND notify_url='%s'" % notify_url)
    if notify.status == 200 and "ticket=wallet-ops-9c2e" in notify.text and "journal updated" in notify.text:
        artifact("OW-18 · redirect пересёк URL allowlist",
                 "разрешённый URL: %s → mock отвечает 302 /service/status" % notify_url,
                 "GET после redirect вернул service=ok и ticket=wallet-ops-9c2e",
                 "POST /settings/notify → HTTP %s; сохранённая настройка count=%s" %
                 (notify.status, journal_row))
        ok("http.Client последовал редиректу за пределы проверенного /hooks/")
    else:
        fail("redirect SSRF не подтвердился: HTTP %s, тело=%s" %
             (notify.status, snippet(notify.text, 160)))

    card("OW-38", "в обработчике уведомлений запускается shell-команда")
    journal = req("GET /ops/journal (результат notify redeem)", "/ops/journal", client=client)
    journal_match = re.search(r"notify-redeem wallet-ops-9c2e: ([^<\n]+)", journal.text)
    if "journal updated" in notify.text and journal_match:
        artifact("OW-38 · shell-вызов оставил артефакт в журнале",
                 "код handler вызывает sh -c 'uname -a' после ticket из redirect",
                 "GET /ops/journal → HTTP %s" % journal.status,
                 "вывод команды: %s" % journal_match.group(1))
        ok("обработчик вызвал shell и записал вывод команды в ops.log")
    else:
        fail("выполненный shell-вывод не найден в журнале")

    card("OW-37", "журнал операций доступен роли employee")
    role_before = db("SELECT role FROM users WHERE login='ivanov'")
    if role_before != "employee":
        db("UPDATE users SET role='employee' WHERE login='ivanov' RETURNING role;")
        client = login_as("ivanov", "workplace1")
    employee_journal = req("GET /ops/journal под role=employee", "/ops/journal", client=client)
    if employee_journal.status == 200 and "notify-redeem wallet-ops-9c2e" in employee_journal.text:
        artifact("OW-37 · employee прочитал служебный ops.log",
                 "users.role=employee; GET /ops/journal → HTTP %s" % employee_journal.status,
                 "в ответе присутствует notify-redeem wallet-ops-9c2e и uname output")
        ok("служебный журнал доступен без admin-роли")
    else:
        fail("employee не прочитал журнал: HTTP %s" % employee_journal.status)
    if role_before != "employee":
        db("UPDATE users SET role='%s' WHERE login='ivanov' RETURNING role;" % role_before)
        client = login_as("ivanov", "workplace1")

    # OW-20: received-order fulfillment performs an extra credit.
    card("OW-20", "выдача заказа со статусом received повторно начисляет возврат")
    owner = db("SELECT id FROM users WHERE login='petrova'")
    order_id = db("INSERT INTO orders (user_id,status,total_kop,lines_json,item_comment) "
                  "VALUES (%s,'received',12345,'[]','OW-20 test') RETURNING id" % owner)
    balance_before = user_balance_kop("petrova")
    fulfill = req("POST /cashier/fulfill/%s со статусом received" % order_id,
                  "/cashier/fulfill/%s" % order_id, client=client, data={})
    balance_after = user_balance_kop("petrova")
    final_status = order_status(order_id)
    refund_op = db("SELECT count(*) FROM operations WHERE kind='refund' AND memo='Корректировка выдачи #%s'" % order_id)
    if balance_before and balance_after and int(balance_after)-int(balance_before) == 12345 \
            and "fulfilled_refund" in final_status and refund_op == "1":
        artifact("OW-20 · повторное зачисление на выдаче",
                 "заказ #%s received → fulfilled_refund; POST вернул HTTP %s" % (order_id, fulfill.status),
                 "petrova balance_kop: %s → %s (+12345)" % (balance_before, balance_after),
                 "операция refund создана: count=%s" % refund_op)
        ok("cashierFulfill начислил деньги заказу, который уже received")
    else:
        fail("повторный возврат не подтверждён: balance %s→%s status=%s refund=%s" %
             (balance_before, balance_after, final_status, refund_op))
    db("DELETE FROM operations WHERE memo='Корректировка выдачи #%s'" % order_id)
    db("DELETE FROM anomaly_log WHERE detail LIKE 'order=%s %%'" % order_id)
    db("DELETE FROM orders WHERE id=%s" % order_id)
    if balance_before:
        db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % balance_before)
    info("OW-20: тестовый заказ/операция удалены, баланс восстановлен")

    # OW-22: provoke an UPDATE failure at BIGINT limit, then observe independent INSERT.
    card("OW-22", "ошибка UPDATE не откатывает запись корректировки")
    old_balance = user_balance_kop("petrova")
    max_i64 = "9223372036854775807"
    db("UPDATE users SET balance_kop=%s WHERE login='petrova' RETURNING balance_kop;" % max_i64)
    adjust = req("POST /accounting/adjust delta_rub=1 while balance is BIGINT max",
                 "/accounting/adjust", client=client,
                 data={"login": "petrova", "delta_rub": "1", "reason": "OW-22 split write"})
    new_balance = user_balance_kop("petrova")
    adjust_row = db("SELECT id||'|'||amount_kop||'|'||memo FROM operations "
                    "WHERE kind='adjust' AND memo='OW-22 split write' ORDER BY id DESC LIMIT 1")
    if new_balance == max_i64 and adjust_row and "100" in adjust_row:
        artifact("OW-22 · частичный результат без транзакции",
                 "balance_kop перед: %s; UPDATE +100 коп упёрся в BIGINT max" % max_i64,
                 "balance_kop после: %s (не изменился)" % new_balance,
                 "INSERT operations выполнен отдельно: %s; HTTP %s" % (adjust_row, adjust.status))
        ok("ошибка первого SQL не помешала второму INSERT создать ложный журнал")
    else:
        fail("частичное выполнение корректировки не подтверждено: balance=%s op=%s" %
             (new_balance, adjust_row))
    db("DELETE FROM operations WHERE kind='adjust' AND memo='OW-22 split write'")
    if old_balance:
        db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % old_balance)
    info("OW-22: баланс восстановлен; тестовая операция удалена")

    # OW-40: a cross-site Origin still mutates a browser-authenticated profile.
    card("OW-40", "POST без CSRF-токена принимается с посторонним Origin")
    profile_before = db("SELECT display_name||'|'||email FROM users WHERE login='ivanov'")
    csrf = req("POST /profile Origin=https://attacker.invalid (без токена)", "/profile",
               client=client, data={"display_name": "OW40-CSRF", "email": "ivanov@x.local"},
               headers={"Origin": "https://attacker.invalid", "Referer": "https://attacker.invalid/poc"})
    profile_after = db("SELECT display_name||'|'||email FROM users WHERE login='ivanov'")
    if profile_after.startswith("OW40-CSRF|"):
        artifact("OW-40 · чужой Origin изменил профиль",
                 "Origin=https://attacker.invalid, POST /profile без CSRF token → HTTP %s" % csrf.status,
                 "users.display_name|email: %s → %s" % (profile_before, profile_after))
        ok("сервер принял state-changing POST без CSRF-защиты")
    else:
        fail("CSRF не подтверждён: профиль %s → %s" % (profile_before, profile_after))
    if profile_before and "|" in profile_before:
        old_name, old_email = profile_before.split("|", 1)
        db("UPDATE users SET display_name='%s', email='%s' WHERE login='ivanov'" %
           (old_name.replace("'", "''"), old_email.replace("'", "''")))

    # OW-41 security response headers.
    card("OW-41", "ответ HTML не содержит базовые security headers")
    page = req("GET / для проверки заголовков", "/", client=client)
    required = ["Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options"]
    absent = [name for name in required if name not in page.headers]
    artifact("OW-41 · заголовки ответа",
             "GET / → HTTP %s" % page.status,
             "проверялись: %s" % ", ".join(required),
             "отсутствуют: %s" % (", ".join(absent) if absent else "нет"))
    if absent:
        ok("ответ не задаёт ожидаемые security headers")
    else:
        fail("все проверяемые security headers присутствуют")

    # OW-42 root in the running app container.
    card("OW-42", "контейнер приложения запущен от root")
    identity = subprocess.run(["docker", "exec", "office-wallet-main-app-1", "id", "-u"],
                              capture_output=True, text=True)
    uid_out = identity.stdout.strip()
    artifact("OW-42 · UID процесса контейнера",
             "docker exec office-wallet-main-app-1 id -u → exit=%s stdout=%s stderr=%s" %
             (identity.returncode, uid_out, identity.stderr.strip() or "(пусто)"))
    if identity.returncode == 0 and uid_out == "0":
        ok("приложение работает с UID 0")
    else:
        fail("UID не root или docker exec завершился с ошибкой")

    # OW-43 database errors are reflected in the HTML response.
    card("OW-43", "ответ пользователю раскрывает ошибку PostgreSQL")
    db_error = req("POST /transfer/new amount_rub='1;SELECT 1/0;--'",
                   "/transfer/new", client=client,
                   data={"recipient": "petrova", "amount_rub": "1;SELECT 1/0;--", "memo": "OW-43"})
    evidence = next((line for line in db_error.text.splitlines()
                     if "division by zero" in line.lower() or "SELECT 1/0" in line), "")
    if evidence:
        artifact("OW-43 · сообщение БД попало в HTML",
                 "POST /transfer/new → HTTP %s" % db_error.status,
                 "ответ содержит диагностический текст: %s" % re.sub(r"<[^>]+>", " ", evidence).strip()[:200])
        ok("клиенту возвращена подробная ошибка SQL/драйвера")
    else:
        fail("диагностика БД в ответе не найдена: %s" % snippet(db_error.text, 220))

    # OW-44 mutates operation type independently of its draft.
    card("OW-44", "op_type из POST переопределяет тип transfer_draft")
    draft_resp = req("POST /transfer/new recipient=petrova amount=1 memo=OW44",
                     "/transfer/new", client=client,
                     data={"recipient": "petrova", "amount_rub": "1", "memo": "OW-44"})
    draft_match = re.search(r"draft_id=(\d+)", draft_resp.url)
    if not draft_match:
        fail("черновик OW-44 не создался: HTTP %s %s" % (draft_resp.status, draft_resp.url))
        return 1
    draft_id = draft_match.group(1)
    draft_type = db("SELECT op_type FROM transfer_drafts WHERE id=%s" % draft_id)
    source_before = user_balance_kop("ivanov")
    target_before = user_balance_kop("petrova")
    confirmed = req("POST /transfer/confirm draft_id=%s op_type=tip_boss" % draft_id,
                    "/transfer/confirm", client=client,
                    data={"draft_id": draft_id, "op_type": "tip_boss"})
    op_row = db("SELECT id||'|'||kind||'|'||amount_kop||'|'||memo FROM operations "
                "WHERE memo='OW-44' ORDER BY id DESC LIMIT 1")
    source_after = user_balance_kop("ivanov")
    target_after = user_balance_kop("petrova")
    artifact("OW-44 · POST заменил вид операции",
             "transfer_drafts.op_type перед подтверждением: %s" % draft_type,
             "POST op_type=tip_boss → HTTP %s; operation row=%s" % (confirmed.status, op_row),
             "balances ivanov %s→%s; petrova %s→%s" %
             (source_before, source_after, target_before, target_after))
    if draft_type == "transfer" and "|tip_boss|" in ("|" + op_row + "|"):
        ok("операция записана как tip_boss хотя draft был transfer")
    else:
        fail("op_type подмена не подтвердилась")
    if op_row:
        op_id = op_row.split("|", 1)[0]
        db("DELETE FROM operations WHERE id=%s" % op_id)
        if source_before:
            db("UPDATE users SET balance_kop=%s WHERE login='ivanov'" % source_before)
        if target_before:
            db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % target_before)
    info("OW-44: тестовая операция удалена, балансы восстановлены")

    # OW-03: many confirmations compete to consume one checkout quote.
    card("OW-03", "гонка повторного использования quote при checkout")
    source_before = user_balance_kop("ivanov")
    db("DELETE FROM cart_items WHERE user_id=(SELECT id FROM users WHERE login='ivanov')")
    req("POST /cart/add product_id=3 for OW-03", "/cart/add", client=client,
        data={"product_id": "3"})
    marker03 = "OW03-race-%d" % int(time.time())
    quote_resp = req("POST /checkout/quote item_comment=%s" % marker03, "/checkout/quote",
                     client=client, data={"item_comment": marker03, "tip_kop": "0", "promo_code": ""})
    quote_match = re.search(r'name="quote_id" value="(\d+)"', quote_resp.text)
    if quote_match:
        qid = quote_match.group(1)
        quote_total = db("SELECT total_kop FROM checkout_quotes WHERE id=%s" % qid)
        db("UPDATE users SET balance_kop=GREATEST(balance_kop,%s) WHERE login='ivanov'" % quote_total)
        before_orders = db("SELECT count(*) FROM orders WHERE item_comment='%s'" % marker03)
        race03 = concurrent_posts("/checkout/confirm", {"quote_id": qid}, client.session(), 12)
        after_orders = db("SELECT count(*) FROM orders WHERE item_comment='%s'" % marker03)
        quote_state = db("SELECT used FROM checkout_quotes WHERE id=%s" % qid)
        artifact("OW-03 · гонка на одной checkout quote",
                 "quote #%s total_kop=%s used_after=%s; параллельных POST=%s" %
                 (qid, quote_total, quote_state, len(race03)),
                 "orders с marker %s: %s → %s" % (marker03, before_orders, after_orders),
                 "HTTP-коды: %s" % ", ".join(str(item[0]) for item in race03))
        if after_orders and int(after_orders) - int(before_orders) > 1:
            ok("одна котировка создала несколько заказов")
        else:
            fail("гонка воспроизведена не была (это не доказывает атомарность)")
        db("DELETE FROM orders WHERE item_comment='%s'" % marker03)
        db("DELETE FROM checkout_quotes WHERE id=%s" % qid)
        db("DELETE FROM cart_items WHERE user_id=(SELECT id FROM users WHERE login='ivanov')")
        if source_before:
            db("UPDATE users SET balance_kop=%s WHERE login='ivanov'" % source_before)
    else:
        fail("OW-03 setup: quote id не извлечён из HTTP ответа")

    # OW-06: races can apply multiple refunds before the order status flips.
    card("OW-06", "гонка возврата/отмены между чтением статуса и записью")
    owner_id = db("SELECT id FROM users WHERE login='ivanov'")
    baseline = user_balance_kop("ivanov")
    race_order = db("INSERT INTO orders(user_id,status,total_kop,lines_json,item_comment) "
                    "VALUES(%s,'paid',5000,'[]','OW-06 return race') RETURNING id" % owner_id)
    before_ops = db("SELECT count(*) FROM operations WHERE memo='Возврат заказа #%s'" % race_order)
    return_race = concurrent_posts("/orders/%s/return" % race_order, {"qty": "1"},
                                   client.session(), 12)
    after_ops = db("SELECT count(*) FROM operations WHERE memo='Возврат заказа #%s'" % race_order)
    after_balance = user_balance_kop("ivanov")
    artifact("OW-06 · конкурентный возврат",
             "заказ #%s total_kop=5000; параллельных POST=%d" % (race_order, len(return_race)),
             "refund operations: %s → %s; balance_kop: %s → %s" %
             (before_ops, after_ops, baseline, after_balance),
             "ответы HTTP: %s" % ", ".join(str(item[0]) for item in return_race))
    if after_ops and before_ops and int(after_ops) - int(before_ops) > 1:
        ok("несколько конкурентных возвратов прошло для одного заказа")
    else:
        fail("лишний возврат не воспроизведён в этой гонке")
    db("DELETE FROM operations WHERE memo='Возврат заказа #%s'" % race_order)
    db("DELETE FROM orders WHERE id=%s" % race_order)
    if baseline and after_balance:
        db("UPDATE users SET balance_kop=%s WHERE login='ivanov'" % baseline)
    info("OW-06: тестовый заказ/операции удалены, баланс восстановлен")

    # OW-15: duplicate confirms should both pass the draft read/check window.
    card("OW-15", "параллельное подтверждение одного transfer draft")
    source_before = user_balance_kop("ivanov")
    target_before = user_balance_kop("petrova")
    draft_create = req("POST /transfer/new amount=1 for OW-15", "/transfer/new", client=client,
                       data={"recipient": "petrova", "amount_rub": "1", "memo": "OW-15 race"})
    draft_match = re.search(r"draft_id=(\d+)", draft_create.url)
    if draft_match:
        draft_id = draft_match.group(1)
        amount15 = db("SELECT amount_kop FROM transfer_drafts WHERE id=%s" % draft_id)
        db("UPDATE transfer_drafts SET amount_kop=GREATEST(amount_kop,50000) WHERE id=%s" % draft_id)
        amount15 = db("SELECT amount_kop FROM transfer_drafts WHERE id=%s" % draft_id)
        before_ops = db("SELECT count(*) FROM operations WHERE memo='OW-15 race'")
        race15 = concurrent_posts("/transfer/confirm", {"draft_id": draft_id}, client.session(), 12)
        after_ops = db("SELECT count(*) FROM operations WHERE memo='OW-15 race'")
        source_after = user_balance_kop("ivanov")
        target_after = user_balance_kop("petrova")
        artifact("OW-15 · параллельные подтверждения draft",
                 "draft #%s amount_kop=%s; confirmations=%d" % (draft_id, amount15, len(race15)),
                 "operations с memo OW-15 race: %s → %s" % (before_ops, after_ops),
                 "ivanov balance: %s → %s; petrova: %s → %s" %
                 (source_before, source_after, target_before, target_after),
                 "HTTP: %s" % ", ".join(str(item[0]) for item in race15))
        if before_ops and after_ops and int(after_ops) - int(before_ops) > 1:
            ok("один draft был списан/зачислен более одного раза")
        else:
            fail("двойное подтверждение не воспроизведено на этом запуске")
        db("DELETE FROM operations WHERE memo='OW-15 race'")
        db("DELETE FROM transfer_drafts WHERE id=%s" % draft_id)
        if source_before:
            db("UPDATE users SET balance_kop=%s WHERE login='ivanov'" % source_before)
        if target_before:
            db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % target_before)
    else:
        fail("OW-15 setup: draft_id не создан")

    # OW-16: two concurrent tips can both pass the same balance check.
    card("OW-16", "конкурентные чаевые проходят одну и ту же проверку баланса")
    source_before = user_balance_kop("ivanov")
    target_before = user_balance_kop("petrova")
    if source_before and int(source_before) >= 20000:
        amount_rub = str(max(1, int(source_before) // 100 // 2 + 1))
        memo16 = "OW-16 race %d" % int(time.time())
        before_ops = db("SELECT count(*) FROM operations WHERE memo='%s'" % memo16)
        race16 = concurrent_posts("/tips/new", {"recipient": "petrova", "amount_rub": amount_rub,
                                    "comment": memo16}, client.session(), 12)
        after_ops = db("SELECT count(*) FROM operations WHERE memo='%s'" % memo16)
        source_after = user_balance_kop("ivanov")
        target_after = user_balance_kop("petrova")
        expected_kop = int(amount_rub) * 100
        artifact("OW-16 · гонка проверки баланса чаевых",
                 "balance before=%s; amount per request=%s RUB; parallel POST=%d" %
                 (source_before, amount_rub, len(race16)),
                 "tip operations: %s → %s; expected amount_kop each=%s" %
                 (before_ops, after_ops, expected_kop),
                 "ivanov: %s → %s; petrova: %s → %s" %
                 (source_before, source_after, target_before, target_after))
        if after_ops and before_ops and int(after_ops)-int(before_ops) > 1:
            ok("несколько чаевых прошли по одному старому балансу")
        else:
            fail("гонка чаевых не воспроизведена на этом запуске")
        db("DELETE FROM operations WHERE memo='%s'" % memo16)
        if source_before:
            db("UPDATE users SET balance_kop=%s WHERE login='ivanov'" % source_before)
        if target_before:
            db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % target_before)
    else:
        fail("недостаточно тестового баланса для гонки чаевых")

    # OW-25: replace crypto/rand.Reader in a temporary isolated Go test.
    card("OW-25", "fallback randomSMSCode требует fault injection crypto/rand")
    app_dir = os.path.join(repo, "app")
    temp_test = os.path.join(app_dir, "internal", "app", "ow25_poc_temp_test.go")
    if os.path.exists(temp_test):
        fail("OW-25 temp test already exists; refusing to overwrite")
    else:
        source = r'''package app
import (
  "crypto/rand"
  "errors"
  "fmt"
  "testing"
  "time"
)
type ow25FailReader struct{}
func (ow25FailReader) Read([]byte) (int, error) { return 0, errors.New("forced crypto/rand failure") }
func TestOW25FallbackPoc(t *testing.T) {
  old := rand.Reader
  rand.Reader = ow25FailReader{}
  defer func(){ rand.Reader = old }()
  want := fmt.Sprintf("%06d", time.Now().Unix()%1000000)
  got := randomSMSCode()
  if got != want { t.Fatalf("fallback mismatch: got %s want %s", got, want) }
  t.Logf("forced rand.Reader failure => predictable fallback code %s", got)
}
'''
        with open(temp_test, "x", encoding="utf-8") as fp:
            fp.write(source)
        try:
            test25 = subprocess.run(["go", "test", "./internal/app", "-run",
                                     "TestOW25FallbackPoc", "-v"], cwd=app_dir,
                                    capture_output=True, text=True, timeout=120)
        finally:
            os.unlink(temp_test)
        if test25.returncode == 0 and "forced rand.Reader failure" in test25.stdout:
            log_line = next((line.strip() for line in test25.stdout.splitlines()
                             if "forced rand.Reader failure" in line), "fallback reproduced")
            artifact("OW-25 · отказ crypto/rand воспроизводит предсказуемый код",
                     "временный Go test заменил rand.Reader на ошибающийся reader; файл PoC удалён после теста",
                     log_line,
                     "runtime fault injection; код не отправлялся и не применялся")
            ok("randomSMSCode вернул time-based fallback после отказа rand.Reader")
        else:
            fail("fault-injection test failed: %s" % snippet(test25.stdout + test25.stderr, 260))

    # OW-36: уязвимая версия CI helper (печатает секреты) живёт в истории git —
    # на масте её уже заменили фиксом. Запускаем ОБЕ: уязвимую (из коммита до
    # фикса) — она должна засветить секреты в stdout; текущую — она печатать
    # не должна. Это и есть доказательство OW-36 + подтверждение закрытия.
    card("OW-36", "CI helper печатает созданные секреты в job stdout")
    vuln_commit = "5c6b209"
    vuln_src = subprocess.run(
        ["git", "show", "%s:ci/app-credentials.sh" % vuln_commit],
        cwd=repo, capture_output=True, text=True)
    if vuln_src.returncode != 0:
        fail("не удалось достать уязвимую версию ci/app-credentials.sh из истории: %s"
             % vuln_src.stderr.strip())
    with tempfile.TemporaryDirectory(prefix="ow36-") as tmp:
        fakebin = os.path.join(tmp, "bin")
        os.makedirs(fakebin)
        kubectl = os.path.join(fakebin, "kubectl")
        with open(kubectl, "w", encoding="utf-8") as fp:
            fp.write("#!/bin/sh\necho 'Error from server (NotFound): secrets not found' >&2\nexit 1\n")
        os.chmod(kubectl, 0o755)
        env = dict(os.environ, PATH=fakebin + os.pathsep + os.environ.get("PATH", ""),
                   K8S_NAMESPACE="ow-test")
        # уязвимая версия: секреты печатаются в stdout job'а
        vuln_script = os.path.join(tmp, "app-credentials-vuln.sh")
        with open(vuln_script, "w", encoding="utf-8") as fp:
            fp.write(vuln_src.stdout)
        proc_v = subprocess.run(["sh", vuln_script], capture_output=True, text=True, env=env)
        # текущая версия в дереве: печатать не должна (фикс с мастера)
        proc_c = subprocess.run(
            ["sh", os.path.join(repo, "ci", "app-credentials.sh")],
            capture_output=True, text=True, env=env)
    secret_lines = [line for line in proc_v.stdout.splitlines()
                    if line.startswith(("DB_PASSWORD=", "APP_SESSION_KEY=", "APP_PAYMENT_KEY="))]
    current_lines = [line for line in proc_c.stdout.splitlines()
                     if line.startswith(("DB_PASSWORD=", "APP_SESSION_KEY=", "APP_PAYMENT_KEY="))]
    if proc_v.returncode == 0 and len(secret_lines) == 3 and not current_lines:
        artifact("OW-36 · секреты выведены в stdout CI job",
                 "git show %s:ci/app-credentials.sh (версия до фикса) + fake kubectl; exit=%s"
                 % (vuln_commit, proc_v.returncode),
                 *["%s=<секрет напечатан в stdout>" % line.split("=", 1)[0] for line in secret_lines],
                 "текущая версия в дереве: секретов в stdout нет (0 строк) — закрыто фиксом",
                 "секретные значения в артефакт не выводятся; важен сам факт печати в job log")
        ok("до фикса helper печатал 3 секрета в job stdout; текущая версия не печатает")
    else:
        fail("CI secret leak не подтверждён: vuln exit=%s lines=%d; current lines=%d; stderr=%s" %
             (proc_v.returncode, len(secret_lines), len(current_lines),
              snippet(proc_v.stderr, 160)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
