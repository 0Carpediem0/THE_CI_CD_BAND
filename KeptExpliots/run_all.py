# -*- coding: utf-8 -*-
"""Прогон всех сценариев локального стенда по порядку отчёта.

    python run_all.py
    python run_all.py --base http://127.0.0.1:8080

01–25 подтверждают находки. 26 и 27 фиксируют границы, которые не стали эксплуатацией.
"""
import subprocess
import sys
from pathlib import Path

from _http import check_local, parser

SCRIPTS = [
    "01_password_reset.py",
    "02_email_oracle.py",
    "03_ssrf_jwt.py",
    "04_ssrf_ipv6.py",
    "05_role_rce.py",
    "06_nginx_backup.py",
    "07_shell_in_image.py",
    "08_environ_jwt.py",
    "09_path_read.py",
    "10_search_leak.py",
    "11_sqli_sort.py",
    "12_delete_account.py",
    "13_stored_xss.py",
    "14_comment_idor.py",
    "15_public_export.py",
    "16_duplicate_username.py",
    "17_draft_feed.py",
    "18_favorite_draft.py",
    "19_draft_comments.py",
    "20_pprof.py",
    "21_token_in_logs.py",
    "22_token_access_log.py",
    "23_login_redirect.py",
    "24_clickjack.py",
    "25_seed_image.py",
    "26_delete_lookup.py",
    "27_runtime_bounds.py",
]


def main():
    args = parser("Прогнать сценарии 01–27").parse_args()
    base = check_local(args.base)
    root = Path(__file__).resolve().parent
    failed = []
    for name in SCRIPTS:
        print(f"\n=== {name} ===", flush=True)
        cmd = [sys.executable, str(root / name)]
        if name != "25_seed_image.py":
            cmd.extend(["--base", base])
        completed = subprocess.run(cmd, cwd=root)
        if completed.returncode != 0:
            failed.append(name)
    print("\n---", flush=True)
    if failed:
        print("с ошибкой: " + ", ".join(failed))
        raise SystemExit(1)
    print(f"OK {len(SCRIPTS)}/{len(SCRIPTS)}")


if __name__ == "__main__":
    main()
