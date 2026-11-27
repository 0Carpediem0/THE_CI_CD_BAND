# SASTAV — Office Wallet

Команда 3. Первичный статический анализ исходного конкурсного проекта. Архив загружен через веб-интерфейс SASTAV, без подключения GitHub. Набор правил Default, ядро SASTAV 1.0, ветка main, коммит `043f91c7e88d52e1b636ded66e2cca15e27eb4e8`.

27.11.2026 11:16:42–11:18:21 (время из экспорта, зона не указана). Анализ завершён. Интерфейс: риск 91%, 47,4 сработки на 1000 строк, 185 уникальных дефектов по метрике SASTAV. Риск — показатель сканера, не вероятность взлома.

| Критичность в UI | JSON | Количество |
|---|---|---:|
| Высокая | CRITICAL | 13 |
| Средняя | SERIOUS | 29 |
| Низкая | WARNING | 143 |
| Информационная | INFORMATION | 0 |
| Всего | | 185 |

Go: 178, JavaScript: 6, PHP: 1 (классификация движка, не доказательство PHP-компонента). 20 правил, 13 путей к файлам. Все записи VERIFY.

## Распределение по правилам

| Уровень | Правило | Сработки |
|---|---|---:|
| CRITICAL | Reflected_XSS | 1 |
| CRITICAL | Reflected_XSS_All_Clients | 1 |
| CRITICAL | SQL_Injection | 6 |
| CRITICAL | Stored_XSS_All_Clients | 5 |
| SERIOUS | Denial_Of_Service_Resource_Exhaustion | 4 |
| SERIOUS | Insecure_Value_of_the_SameSite_Cookie_Attribute_in_Code | 5 |
| SERIOUS | Integer_Overflow | 2 |
| SERIOUS | Missing_HSTS_Header | 1 |
| SERIOUS | Missing_HttpOnly_Cookie | 7 |
| SERIOUS | Missing_Secure_Cookie | 7 |
| SERIOUS | Reflected_Absolute_Path_Traversal | 1 |
| SERIOUS | Reflected_Relative_Path_Traversal | 1 |
| SERIOUS | SSRF | 1 |
| WARNING | Client_Hardcoded_Domain | 3 |
| WARNING | Improper_Error_Handling | 135 |
| WARNING | Missing_Content_Security_Policy | 1 |
| WARNING | Missing_Framing_Policy | 1 |
| WARNING | Plain_Text_Transport_Layer_in_Server | 1 |
| WARNING | Potential_Clickjacking_on_Legacy_Browsers | 1 |
| WARNING | Unsafe_Use_Of_Target_blank | 1 |

## Вывод

SASTAV дополняет Gosec и другие проверки: обнаружены кандидаты SQL injection, XSS, небезопасные cookie, обход путей, переполнения, SSRF и массовое игнорирование ошибок. Есть пересечения с OW-21, OW-12, OW-08, OW-09, OW-30, OW-18, OW-41. Часть сигналов дублирует один sink или относится к параметризованным запросам. Отдельно проверять фактический импакт и исправления; результаты относятся к baseline, не к последнему GitHub main.

## Артефакты

- [Исходный JSON](sastav-before.json)
- [Индекс всех сработок CSV](findings.csv)
- [Предварительный триаж](triage.md)
- [Контекст для отчёта и презентации](report-and-presentation.txt)

Статусы в SASTAV не менялись. Повторный анализ не выполнен. Исходный код и main не изменяются этой веткой.
