# -*- coding: utf-8 -*-
"""F-20. При GIN_MODE=debug /api/debug/pprof доступен без входа."""
from _http import Client, parser


def main():
    p = parser("Открытый pprof")
    args = p.parse_args()
    client = Client(args.base)
    status, _, raw = client.call("GET", "/api/debug/pprof/")
    text = raw.decode("utf-8", "replace")
    if status != 200 or "/debug/pprof/" not in text or "heap" not in text:
        raise SystemExit(f"индекс pprof недоступен: {status} {text[:160]!r}")
    status, _, cmd = client.call("GET", "/api/debug/pprof/cmdline")
    cmdline = cmd.decode("utf-8", "replace").strip("\x00")
    if status != 200 or "contest" not in cmdline:
        raise SystemExit(f"cmdline не прочитан: {status} {cmd[:80]!r}")
    print(f"OK pprof index, cmdline={cmdline}")


if __name__ == "__main__":
    main()
