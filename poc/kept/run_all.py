# -*- coding: utf-8 -*-
"""Прогон всех PoC по стенду Office Wallet.

  docker run --rm --network work_default -v <poc>:/poc -w /poc python:3-alpine \
      python run_all.py --base http://app:8080

Каждый скрипт самопроверяется и возвращает код выхода. Логи этого прогона
используются как артефакты в отчёте.
"""
import subprocess
import sys
from pathlib import Path

from wallet_client import parser

SCRIPTS = [
    "01_key_leak_static_js.py",
    "02_session_forge_admin.py",
    "03_role_forge_money.py",
    "04_sqli_transfer_errorbased.py",
    "05_sqli_reconcile_union.py",
    "06_ssti_rce.py",
    "07_path_traversal.py",
    "08_order_return_inflation.py",
    "09_idor_order_view.py",
    "10_idor_ops_feed.py",
    "11_supply_pricing_leak.py",
    "12_payment_replay_forge.py",
    "13_reflected_xss.py",
    "14_stored_xss_tip.py",
    "15_password_reset_ato.py",
    "16_user_enumeration.py",
    "17_info_disclosure_errors.py",
]


def main():
    base = parser("Прогнать все PoC").parse_args().base
    root = Path(__file__).resolve().parent
    failed = []
    for name in SCRIPTS:
        print(f"\n===== {name} =====", flush=True)
        r = subprocess.run([sys.executable, str(root / name), "--base", base])
        if r.returncode != 0:
            failed.append(name)
    print("\n" + "-" * 40, flush=True)
    if failed:
        print("С ОШИБКОЙ: " + ", ".join(failed))
        raise SystemExit(1)
    print(f"OK {len(SCRIPTS)}/{len(SCRIPTS)} PoC подтверждены")


if __name__ == "__main__":
    main()
