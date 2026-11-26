INSERT INTO users (id, login, password_hash, display_name, email, phone, role, account_no, balance_kop, overdraft_limit_kop, blocked) VALUES
(1, 'ivanov', '$2a$10$DQdYa8ulSNI7ufNE7g.wIOwauAGuRjefvh4HpI6l5.yBULozjV9uy', 'Иван Иванов', 'ivanov@office.local', '+79001110001', 'employee', '40817810000000000001', 15000, 0, FALSE),
(2, 'petrova', '$2a$10$3yRGTpVXg0YsQZZy7iVH4.CZu/fQwEjG2au0j9ZHnqc8oOZNL0xeS', 'Анна Петрова', 'petrova@office.local', '+79001110002', 'employee', '40817810000000000002', 22000, 0, FALSE),
(3, 'sidorov', '$2a$10$m.GFGJUh6MIMPjuXqqUG6OlDSVgLYED4vUea1VbEvQKSUnxsTtzTG', 'Сергей Сидоров', 'sidorov@office.local', '+79001110003', 'employee', '40817810000000000003', 8000, 0, FALSE),
(4, 'kassa', '$2a$10$Zssjo8K34d6BwzSaBwQ/IuwnAxvmun.Mcb8Qfa/Olpbru6qB2/R4S', 'Касса Офиса', 'kassa@office.local', '+79001110004', 'cashier', '40817810000000000004', 500000, 0, FALSE),
(5, 'buch', '$2a$10$k2hQU0/WUG56ehd238qLE.vYvd8aynYmHmAGCEFNfj3cUgueODZYy', 'Ольга Бухгалтерова', 'buch@office.local', '+79001110005', 'accountant', '40817810000000000005', 12000, 0, FALSE),
(6, 'adminw', '$2a$10$UKDcboHEefrpXM.hsGGCgeF5Ulcc4wcU7xR2OM2egSvgyjMVLlFti', 'Админ Кошелька', 'adminw@office.local', '+79001110006', 'admin', '40817810000000000006', 30000, 0, FALSE);

SELECT setval('users_id_seq', 6);

INSERT INTO products (id, code, title, price_kop, cost_kop, supplier_note, active) VALUES
(1, 'COFFEE', 'Кофе в зернах 250г', 45000, 28000, 'Поставщик: RoastLab, скидка при опте', TRUE),
(2, 'TEA', 'Чай листовой', 32000, 19000, 'Поставщик: LeafCo', TRUE),
(3, 'SNACK', 'Набор снеков', 27000, 15000, 'Склад B-2', TRUE),
(4, 'MUG', 'Кружка Office', 60000, 35000, 'Тираж ограничен', TRUE);

SELECT setval('products_id_seq', 4);

INSERT INTO promo_codes (code, percent) VALUES
('OFFICE10', 10),
('TEAM5', 5);

INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, fee_kop, memo, status) VALUES
('transfer', 2, 1, 500, 0, 'За обед', 'ok'),
('transfer', 1, 3, 300, 0, 'Чаевые за помощь', 'ok'),
('topup', NULL, 1, 15000, 0, 'Стартовое пополнение', 'ok'),
('transfer', 3, 2, 200, 0, 'Служебная сверка desk-memo', 'ok');

INSERT INTO orders (user_id, status, total_kop, lines_json, item_comment) VALUES
(2, 'delivered', 45000, '[{"product_id":1,"title":"Кофе в зернах 250г","qty":1,"price_kop":45000}]', ''),
(3, 'paid', 32000, '[{"product_id":2,"title":"Чай листовой","qty":1,"price_kop":32000}]', '');

INSERT INTO notify_settings (user_id, notify_url) VALUES (1, '');
