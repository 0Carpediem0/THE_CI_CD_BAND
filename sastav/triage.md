# Предварительный триаж SASTAV

Исходный коммит `043f91c7e88d52e1b636ded66e2cca15e27eb4e8`. Все 185 записей в экспорте имеют статус VERIFY. Ниже аналитическая оценка фрагментов из JSON, а не изменение статусов в SASTAV или проверка эксплуатации. Реестр: [README](../README.md).

## Все 13 высоких сработок

| UUID | Правило | Место (строки baseline) | Оценка |
|---|---|---|---|
| 0ad542f3-795a-4fe7-b54e-eb9436431e65 | Stored_XSS_All_Clients | handlers_money.go:141, handlers_money.go:146 | Проверить Content-Type и контекст JSON; вероятный дубль d74999e4, XSS не доказан. |
| 35f93da9-2292-4721-820a-a1b02420fd31 | SQL_Injection | handlers_shop.go:187, handlers_shop.go:203, handlers_shop.go:202 | Кандидат в ложное срабатывание: проверить полный текст SQL и привязку параметров. |
| 4982f77e-6e00-4046-a479-9481d1217b14 | Reflected_XSS | transfer_new.html:27, transfer_new.html:31, transfer_new.html:33, transfer_new.html:34, transfer_new.html:35 | Проверить безопасные DOM API и присваивание свойств; добавление узла само по себе не XSS. |
| 58c88dd2-2e73-4acb-b876-82ef1a2fb853 | SQL_Injection | handlers_shop.go:187, handlers_shop.go:195 | Кандидат в ложное срабатывание: SELECT использует $1. |
| 5df9d0cd-c44f-4ab6-8dab-e39d72e491b7 | SQL_Injection | handlers_auth.go:143, handlers_auth.go:146 | Кандидат в ложное срабатывание: запрос использует $1 и $2; логика сброса пароля оценивается отдельно (OW-26). |
| 66447617-25c1-441c-b77e-9ab5994c58b8 | SQL_Injection | handlers_shop.go:192, handlers_shop.go:203, handlers_shop.go:202 | Кандидат в ложное срабатывание: проверить параметризацию INSERT; общий sink с 35f93da9. |
| 705f1954-655e-4ab6-83e0-4dc135b2b1a0 | SQL_Injection | handlers_accounting.go:104, handlers_accounting.go:107, handlers_accounting.go:109, handlers_accounting.go:115, handlers_accounting.go:116, handlers_accounting.go:120 | OW-21: совпадение с известной SQL-инъекцией в исходной версии; динамический SQL, требуется повторная проверка после исправления. |
| 778e82d0-49c1-4b63-8ddb-46633217a414 | Stored_XSS_All_Clients | handlers_money.go:333, handlers_money.go:344 | OW-12: прямое преобразование данных в template.HTML; кандидат на подтверждение по контексту шаблона. |
| 9c7913a0-1113-4881-9aa9-da4b3a5e5e57 | Reflected_XSS_All_Clients | handlers_money.go:37, handlers_money.go:60, handlers_money.go:17, handlers_money.go:19, handlers_money.go:29 | OW-12: template.HTML в истории; проверить sanitizeSearchDisplay и шаблон. |
| a13e1732-1f39-4711-9023-9744a5b48258 | SQL_Injection | handlers_money.go:162, handlers_money.go:195, handlers_money.go:194 | Кандидат в ложное срабатывание для memo в параметризованном INSERT; не считать подтверждением OW-14 без проверки отдельного SQL sink. |
| a1959b8f-2233-41d3-85d1-a29ae349aecf | Stored_XSS_All_Clients | handlers_shop.go:395, handlers_shop.go:399, handlers_shop.go:398, handlers_shop.go:419 | OW-08: пересечение с превью заказа; SASTAV пометил XSS, не подтверждает RCE сам по себе; общий sink с eb940c15. |
| d74999e4-a576-44ab-b2ce-0ecb9edd90ac | Stored_XSS_All_Clients | handlers_money.go:141, handlers_money.go:146 | Вероятный дубль 0ad542f3; проверить контекст JSON. |
| eb940c15-5b25-419a-afe6-d5bcb1bd37a9 | Stored_XSS_All_Clients | handlers_shop.go:395, handlers_shop.go:399, handlers_shop.go:398, handlers_shop.go:419 | Вероятный дубль a1959b8f; OW-08, проверять отдельно контекст шаблона. |

## Средние и низкие

| Группа | Количество | Решение |
|---|---:|---|
| Cookie Secure / HttpOnly / SameSite | 19 | OW-30/OW-40: разделить чувствительные cookies, flash и удаление cookies; не приравнивать каждое предупреждение к захвату сессии. |
| Resource exhaustion | 4 | Проверить ограничения ресурсов и запросов; не выполнять нагрузочные атаки на конкурсной инфраструктуре. |
| Path Traversal | 2 | Один и тот же участок экспорта, OW-09; не считать двумя независимыми дефектами. |
| Integer overflow | 2 | Проверить арифметику покупок/возвратов, OW-01/смежные записи. |
| SSRF | 1 | OW-18 — кандидат; проверить URL и редиректы по коду. |
| HSTS | 1 | Проверить HTTPS и заголовки на ingress, не только Go-код. |
| Improper_Error_Handling | 135 | Проверять в первую очередь операции с деньгами, транзакции и хеширование; OW-24 и смежные позиции. Не все игнорируемые ошибки имеют security-impact. |
| Прочие низкие | 8 | CSP / framing / clickjacking — OW-41; hardcoded domain, target blank и transport оценить в контексте. Helm helper распознан как PHP: проверить применимость правила. |

## Что осталось

Подтвердить кандидаты по полному коду baseline, сопоставить с исправлениями текущего main, повторить SASTAV на разрешённом архиве после исправлений, затем выставить статусы в интерфейсе. Не считать 185 подтверждёнными уязвимостями. Исходная выгрузка сохранена без изменения статусов.
