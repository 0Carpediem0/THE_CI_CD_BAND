CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  login TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'employee',
  account_no TEXT UNIQUE NOT NULL,
  balance_kop BIGINT NOT NULL DEFAULT 0,
  overdraft_limit_kop BIGINT NOT NULL DEFAULT 0,
  blocked BOOLEAN NOT NULL DEFAULT FALSE,
  session_version INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE products (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  price_kop BIGINT NOT NULL,
  cost_kop BIGINT NOT NULL,
  supplier_note TEXT,
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE promo_codes (
  code TEXT PRIMARY KEY,
  percent INT NOT NULL
);

CREATE TABLE operations (
  id SERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  from_user_id INT REFERENCES users(id),
  to_user_id INT REFERENCES users(id),
  amount_kop BIGINT NOT NULL,
  fee_kop BIGINT NOT NULL DEFAULT 0,
  memo TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  meta TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE cart_items (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  product_id INT NOT NULL REFERENCES products(id),
  qty INT NOT NULL DEFAULT 1
);

CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  status TEXT NOT NULL,
  total_kop BIGINT NOT NULL,
  lines_json TEXT NOT NULL,
  item_comment TEXT,
  refunded_kop BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE transfer_drafts (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  recipient_id INT NOT NULL REFERENCES users(id),
  amount_kop BIGINT NOT NULL,
  fee_kop BIGINT NOT NULL DEFAULT 0,
  memo TEXT,
  op_type TEXT NOT NULL DEFAULT 'transfer',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE password_resets (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  sms_code TEXT NOT NULL,
  used BOOLEAN NOT NULL DEFAULT FALSE,
  attempts INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sms_outbox (
  id SERIAL PRIMARY KEY,
  rid INT NOT NULL,
  user_id INT REFERENCES users(id),
  phone TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE checkout_quotes (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  total_kop BIGINT NOT NULL,
  promo_code TEXT NOT NULL DEFAULT '',
  tip_kop BIGINT NOT NULL DEFAULT 0,
  item_comment TEXT NOT NULL DEFAULT '',
  lines_json TEXT NOT NULL DEFAULT '',
  used BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE mail_outbox (
  id SERIAL PRIMARY KEY,
  recipient TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE notify_settings (
  user_id INT PRIMARY KEY REFERENCES users(id),
  notify_url TEXT NOT NULL DEFAULT ''
);

CREATE TABLE anomaly_log (
  id SERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
