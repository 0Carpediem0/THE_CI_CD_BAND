# Office Wallet — патчи и хардеринг

Диффы приведены относительно исходного кода стенда. Нумерация совпадает с находками отчёта (V-xx).
Проверяемые целиком файлы лежат рядом: `Dockerfile.hardened`, `docker-compose.hardened.yml`,
`gitlab-ci.secure.yml`, `k8s-securitycontext.yaml`.

---

## V-01 / V-02 / V-09 / V-12 — ключи и роль из подписанной куки

`app/cmd/wallet/main.go` — не стартовать с пустыми/дефолтными ключами:

```go
sessionKey := mustSecret("SESSION_KEY")
paymentKey := mustSecret("PAYMENT_KEY")
...
func mustSecret(name string) string {
    v := os.Getenv(name)
    bad := map[string]bool{
        "": true,
        "office-wallet-session-key": true,
        "office-wallet-pay-key":     true,
    }
    if bad[v] || len(v) < 32 {
        log.Fatalf("%s must be set to a strong secret (>=32 bytes), not a default", name)
    }
    return v
}
```

`app/internal/app/auth.go` — роль берём ТОЛЬКО из БД, куку делаем HttpOnly+Secure,
подпись считаем от uid (без роли), чтобы роль нельзя было подменить:

```go
func (s *Server) currentUser(r *http.Request) *User {
    c, err := r.Cookie(sessionCookie)
    if err != nil || c.Value == "" {
        return nil
    }
    parts := strings.Split(c.Value, ".")
    if len(parts) != 3 || parts[0] != "ow" {   // ow.<uid>.<sig>
        return nil
    }
    uid, err := strconv.Atoi(parts[1])
    if err != nil {
        return nil
    }
    if !hmac.Equal([]byte(parts[2]), []byte(s.signSession(uid))) {
        return nil
    }
    u, err := s.getUserByID(uid)
    if err != nil || u == nil {
        return nil
    }
    return u // роль только из строки users, не из куки
}

func (s *Server) signSession(uid int) string {
    mac := hmac.New(sha256.New, []byte(s.cfg.SessionKey))
    mac.Write([]byte(strconv.Itoa(uid)))
    return hex.EncodeToString(mac.Sum(nil))
}

func (s *Server) setSession(w http.ResponseWriter, u *User) {
    val := "ow." + strconv.Itoa(u.ID) + "." + s.signSession(u.ID)
    http.SetCookie(w, &http.Cookie{
        Name: sessionCookie, Value: val, Path: "/",
        HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode,
    })
}
```

Удалить утечку ключей из статики: `app/static/pay.js`, `app/static/wallet.js`,
`app/static/legacy-sync.js` не должны содержать частей ключа. Канал `supplyChannel`
и `signOpGrant` — только серверные, наружу не отдавать (убрать заголовок
`X-Wallet-Sync-Part` и `meta.ch_pref` в `apiCatalog`).

---

## V-03 — SSTI/RCE в превью чека

`app/internal/app/handlers_shop.go`, `orderPreview`: убрать ветку `renderer=classic` и
функцию `exec`. Рендерить только безопасным `html/template` с данными, без склейки
пользовательского текста в исходник шаблона:

```go
func (s *Server) orderPreview(w http.ResponseWriter, r *http.Request, id int) {
    u := s.requireUser(w, r)
    if u == nil { return }
    var comment, lines string
    var uid int
    var total int64
    err := s.db.QueryRow(`SELECT user_id, total_kop, lines_json, COALESCE(item_comment,'') FROM orders WHERE id=$1`, id).
        Scan(&uid, &total, &lines, &comment)
    if err != nil || uid != u.ID {           // плюс проверка владельца (см. V-10)
        http.NotFound(w, r); return
    }
    out := fmt.Sprintf("Чек заказа #%d\nСумма: %s\nКомментарий: %s\n", id, formatRub(total), comment)
    s.render(w, r, "order_preview.html", Page{Title: "Превью чека", User: u,
        Preview: template.HTML("<pre class=\"receipt-preview\">" + template.HTMLEscapeString(out) + "</pre>"),
        Data: map[string]any{"ID": id}})
}
```

Аналогично убрать `exec.Command("sh","-c",...)` из `notifySettings` (V-20).

---

## V-04 / V-05 / V-24 — SQL-инъекции и утечка ошибок

`app/internal/app/handlers_money.go`, `transferNew`: не класть сумму в SQL. Парсить число в Go,
при ошибке — общий текст:

```go
amountKop, err = parseRubToKop(amountStr)
if err != nil || amountKop <= 0 {
    s.render(w, r, "transfer_new.html", Page{Title: "Перевод", User: u, Flash: "Укажите положительную сумму"})
    return
}
// удалить блок с fmt.Sprintf("SELECT %s::bigint", amountStr) и s.db.Exec(q)
```

`app/internal/app/handlers_accounting.go`, `accountingReconcile`: параметризовать фильтр и
не возвращать текст ошибки/запрос:

```go
rows, err := s.db.Query(
    `SELECT id, kind, amount_kop, COALESCE(memo,''), status FROM operations
     WHERE ($1='' OR memo LIKE '%'||$1||'%')`, memoFilter)
...
if err != nil {
    log.Printf("reconcile query failed: %v", err) // в лог, не пользователю
    report = "Не удалось выполнить сверку"
}
```

То же для `from_op`-ветки (параметр `$1`). Нигде не возвращать `err.Error()` клиенту (V-24):
в `login` и прочих местах отдавать 500 без тела драйвера.

---

## V-06 — Path traversal в выписке

`app/internal/app/handlers_shop.go`, `statementExport`: имя — только базовое, путь обязан
остаться внутри каталога экспорта:

```go
name := filepath.Base(r.FormValue("filename"))
if name == "" || name == "." || name == ".." {
    name = def
}
target := filepath.Join(s.cfg.ExportsDir, name)
rel, err := filepath.Rel(s.cfg.ExportsDir, target)
if err != nil || strings.HasPrefix(rel, "..") {
    s.flash(w, "Некорректное имя файла", false)
    http.Redirect(w, r, "/statements/export", http.StatusFound)
    return
}
```

---

## V-07 / V-16 / V-17 — денежная логика

`orderReturn`: не умножать на управляемый `qty`; возврат ограничить фактически уплаченной
суммой и однократностью (статус `returned`), все расчёты — на стороне сервера:

```go
if status == "paid" || status == "delivered" || status == "received" {
    refund := total            // не total*qty
    s.db.Exec(`UPDATE orders SET status='returned' WHERE id=$1 AND status<>'returned'`, id)
    s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, refund, u.ID)
}
```

`checkoutConfirm` (V-16): пересчитывать сумму по «живой» корзине на момент оплаты, а не
доверять `total` из котировки; при расхождении отклонять. `cashierFulfill` (V-17): ветку
`received` не делать повторным возвратом — развести «выдачу» и «возврат».

---

## V-08 — сброс пароля

`app/internal/app/handlers_auth.go`: код из `crypto/rand` (>=10^8), срок жизни (напр. 15 мин),
лимит попыток и блокировка заявки после N неверных, гасить заявку после успеха, код НЕ
показывать в `/gateway/sms`. Mailpit (V-27) не публиковать наружу.

```sql
ALTER TABLE password_resets ADD COLUMN expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW()+INTERVAL '15 min';
ALTER TABLE password_resets ADD COLUMN attempts INT NOT NULL DEFAULT 0;
```
```go
err := s.db.QueryRow(`SELECT user_id FROM password_resets
    WHERE id=$1 AND sms_code=$2 AND used=FALSE AND attempts<5 AND expires_at>NOW()`, rid, code).Scan(&uid)
if err != nil {
    s.db.Exec(`UPDATE password_resets SET attempts=attempts+1 WHERE id=$1`, rid)
    ...
}
```

---

## V-10 / V-11 — IDOR

`orderView`, `orderPreview`: добавить `AND user_id=$me` (или 403 при чужом владельце, кроме
кассира/админа по бизнес-правилу). `apiOpsFeed`: отдавать только операции текущего
пользователя и не ставить grant-cookie на чужие; `signOpGrant` оставить серверным.

---

## V-13 / V-14 / V-22 — XSS и заголовки

Убрать «сырой» вывод: в `handlers_money.go` не оборачивать `q`/`memo` в `template.HTML`
(`QRaw`, `TipHTML`) — пусть `html/template` экранирует. Убрать самодельный
`sanitizeSearchDisplay`. Добавить security-заголовки в `render.go` (и на ingress):

```go
w.Header().Set("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
w.Header().Set("X-Frame-Options", "DENY")
w.Header().Set("X-Content-Type-Options", "nosniff")
w.Header().Set("Referrer-Policy", "no-referrer")
w.Header().Set("Strict-Transport-Security", "max-age=63072000")
```

---

## V-18 / V-21 — БД и устойчивость сервера

`server.go` — таймауты и лимит пула; `main.go`/DSN — TLS и пароль только из секрета:

```go
db.SetMaxOpenConns(20)
db.SetMaxIdleConns(5)
db.SetConnMaxLifetime(30 * time.Minute)

srv := &http.Server{
    Addr: s.cfg.Addr, Handler: mux,
    ReadHeaderTimeout: 5 * time.Second,
    ReadTimeout:       15 * time.Second,
    WriteTimeout:      30 * time.Second,
    IdleTimeout:       60 * time.Second,
}
return srv.ListenAndServe()
```

DSN: `postgres://wallet:${DB_PASSWORD}@db:5432/wallet?sslmode=verify-full` (пароль из секрета,
TLS включён и на стороне Postgres). См. `docker-compose.hardened.yml` и `secret.yaml`.

---

## V-19 / V-27 / V-28 — образ, K8s, зависимости

- `Dockerfile.hardened`: непривилегированный `USER`, минимальная/distroless база, обновление пакетов.
- `k8s-securitycontext.yaml`: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`,
  `seccompProfile: RuntimeDefault`, `drop: [ALL]`, лимиты ресурсов; Mailpit не публиковать Ingress'ом.
- V-28: обновить базовый образ и Go-toolchain; гейтить `trivy image`/`govulncheck` в CI.

---

## V-23 / V-26 — CSRF и секреты в CI

- CSRF: токен на все state-changing формы (double-submit cookie или `SameSite=Strict`+проверка
  Origin), убрать изменение состояния по GET (`orderReceived`).
- CI: не печатать `DB_PASSWORD`/`SESSION_KEY`/`PAYMENT_KEY` в лог job (убрать `printf` из
  `ci/app-credentials.sh`), не выводить base64 docker-auth. Хранить как masked/file CI-переменные.
