package app

import (
        "crypto/rand"
        "fmt"
        "math/big"
        "net/http"
        "strconv"
        "strings"
        "time"
)

func (s *Server) home(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        rows, _ := s.db.Query(`SELECT id, kind, amount_kop, memo, status, created_at::text FROM operations
                WHERE from_user_id=$1 OR to_user_id=$1 ORDER BY id DESC LIMIT 8`, u.ID)
        defer rows.Close()
        var ops []map[string]any
        for rows.Next() {
                var id int
                var kind, memo, status, created string
                var amount int64
                _ = rows.Scan(&id, &kind, &amount, &memo, &status, &created)
                ops = append(ops, map[string]any{"ID": id, "Kind": kind, "Amount": formatRub(amount), "Memo": memo, "Status": status, "Created": created})
        }
        fresh, _ := s.getUserByID(u.ID)
        s.render(w, r, "home.html", Page{Title: "Обзор", User: fresh, Data: map[string]any{"Ops": ops}})
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
        ret := r.URL.Query().Get("return")
        if ret == "" {
                ret = "/"
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "login.html", Page{Title: "Вход", Data: map[string]any{"Return": ret}})
                return
        }
        login := strings.TrimSpace(r.FormValue("login"))
        pass := r.FormValue("password")
        ret = r.FormValue("return")
        if ret == "" {
                ret = "/"
        }
        u, err := s.getUserByLogin(login)
        if err != nil {
                http.Error(w, err.Error(), 500)
                return
        }
        if u == nil || !checkPassword(u.PasswordHash, pass) {
                s.render(w, r, "login.html", Page{Title: "Вход", Flash: "Неверный логин или пароль", Data: map[string]any{"Return": ret, "Login": login}})
                return
        }
        s.setSession(w, u)
        if strings.HasPrefix(ret, "http://") || strings.HasPrefix(ret, "https://") || strings.HasPrefix(ret, "//") {
                ret = "/"
        }
        if !strings.HasPrefix(ret, "/") {
                ret = "/"
        }
        http.Redirect(w, r, ret, http.StatusFound)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
        s.clearSession(w)
        http.Redirect(w, r, "/login", http.StatusFound)
}

func (s *Server) register(w http.ResponseWriter, r *http.Request) {
        if r.Method == http.MethodGet {
                s.render(w, r, "register.html", Page{Title: "Регистрация"})
                return
        }
        login := strings.TrimSpace(r.FormValue("login"))
        name := strings.TrimSpace(r.FormValue("display_name"))
        email := strings.TrimSpace(r.FormValue("email"))
        pass := r.FormValue("password")
        hash, _ := hashPassword(pass)
        acc := fmt.Sprintf("4081781%011d", time.Now().UnixNano()%1e11)
        _, err := s.db.Exec(`INSERT INTO users (login, password_hash, display_name, email, phone, role, account_no, balance_kop) VALUES ($1,$2,$3,$4,'', 'employee',$5,0)`,
                login, hash, name, email, acc)
        if err != nil {
                s.render(w, r, "register.html", Page{Title: "Регистрация", Flash: "Не удалось создать аккаунт"})
                return
        }
        s.flash(w, "Аккаунт создан", true)
        http.Redirect(w, r, "/login", http.StatusFound)
}

func randomSMSCode() string {
        n, err := rand.Int(rand.Reader, big.NewInt(1000000))
        if err != nil {
                return fmt.Sprintf("%06d", time.Now().Unix()%1000000)
        }
        return fmt.Sprintf("%06d", n.Int64())
}

func maskPhone(phone string) string {
        p := strings.TrimSpace(phone)
        if len(p) < 4 {
                return "****"
        }
        return strings.Repeat("*", len(p)-4) + p[len(p)-4:]
}

func (s *Server) passwordForgot(w http.ResponseWriter, r *http.Request) {
        if r.Method == http.MethodGet {
                s.render(w, r, "password_forgot.html", Page{Title: "Сброс пароля"})
                return
        }
        login := strings.TrimSpace(r.FormValue("login"))
        u, _ := s.getUserByLogin(login)
        if u != nil {
                code := randomSMSCode()
                var rid int
                _ = s.db.QueryRow(`INSERT INTO password_resets (user_id, sms_code) VALUES ($1,$2) RETURNING id`, u.ID, code).Scan(&rid)
                link := s.cfg.PublicBase + "/password/reset?rid=" + strconv.Itoa(rid)
		s.mailSend(u.Email, "Сброс пароля", "Перейдите по ссылке для сброса пароля:\n"+link+"\n\nКод подтверждения отправлен SMS.")
                phone := u.Phone
                if phone == "" {
                        phone = "+79000000000"
                }
                _, _ = s.db.Exec(`INSERT INTO sms_outbox (rid, user_id, phone, body) VALUES ($1,$2,$3,$4)`,
                        rid, u.ID, phone, "Office Wallet: код подтверждения сброса "+code+" (заявка #"+strconv.Itoa(rid)+")")
        }
        s.flash(w, "Если аккаунт найден, письмо отправлено. Код подтверждения — в SMS.", true)
        http.Redirect(w, r, "/password/forgot", http.StatusFound)
}

func (s *Server) passwordReset(w http.ResponseWriter, r *http.Request) {
        ridStr := r.URL.Query().Get("rid")
        if ridStr == "" {
                ridStr = r.FormValue("rid")
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "password_reset.html", Page{Title: "Новый пароль", Data: map[string]any{"RID": ridStr}})
                return
        }
        if r.Method != http.MethodPost {
                w.Header().Set("Allow", "GET, POST")
                http.Error(w, "Метод не поддерживается", http.StatusMethodNotAllowed)
                return
        }
        rid, err := strconv.Atoi(ridStr)
        code := strings.TrimSpace(r.FormValue("sms_code"))
        invalid := func() {
                s.render(w, r, "password_reset.html", Page{Title: "Новый пароль", Flash: "Неверный код или заявка", Data: map[string]any{"RID": ridStr}})
        }
        if err != nil || rid <= 0 || len(code) != 6 {
                invalid()
                return
        }
        pass := r.FormValue("password")
        if pass == "" {
                http.Error(w, "Введите пароль", http.StatusBadRequest)
                return
        }
        hash, err := hashPassword(pass)
        if err != nil {
                http.Error(w, "Некорректный пароль", http.StatusBadRequest)
                return
        }
        ctx := r.Context()
        tx, err := s.db.BeginTx(ctx, nil)
        if err != nil {
                http.Error(w, "Не удалось обновить пароль", http.StatusInternalServerError)
                return
        }
        defer tx.Rollback()
        var uid int
        err = tx.QueryRowContext(ctx, `UPDATE password_resets SET used=TRUE
                WHERE id=$1 AND sms_code=$2 AND NOT used AND created_at >= now() - interval '15 minutes'
                RETURNING user_id`, rid, code).Scan(&uid)
        if err != nil {
                invalid()
                return
        }
        if _, err := tx.ExecContext(ctx, `UPDATE users SET password_hash=$1 WHERE id=$2`, hash, uid); err != nil {
                http.Error(w, "Не удалось обновить пароль", http.StatusInternalServerError)
                return
        }
        if err := tx.Commit(); err != nil {
                http.Error(w, "Не удалось обновить пароль", http.StatusInternalServerError)
                return
        }
        s.flash(w, "Пароль обновлён", true)
        http.Redirect(w, r, "/login", http.StatusFound)
}

func (s *Server) smsGateway(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsAdmin() {
                http.Error(w, "forbidden", http.StatusForbidden)
                return
        }
        rows, _ := s.db.Query(`SELECT id, rid, phone, body, created_at::text FROM sms_outbox ORDER BY id DESC LIMIT 50`)
        defer rows.Close()
        var msgs []map[string]any
        for rows.Next() {
                var id, rid int
                var phone, body, created string
                _ = rows.Scan(&id, &rid, &phone, &body, &created)
                msgs = append(msgs, map[string]any{
                        "ID": id, "RID": rid, "Phone": maskPhone(phone), "Body": body, "Created": created,
                })
        }
        s.render(w, r, "sms_gateway.html", Page{Title: "SMS-шлюз", User: u, Data: map[string]any{"Messages": msgs}})
}

func (s *Server) mailBox(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if r.Method == http.MethodPost {
                s.mailSend(u.Email, "Проверка уведомлений", "Проверка доставки Office Wallet")
                s.flash(w, "Письмо отправлено", true)
                http.Redirect(w, r, "/mail", http.StatusFound)
                return
        }
        rows, err := s.db.QueryContext(r.Context(), `SELECT recipient, subject, body, created_at::text FROM mail_outbox WHERE recipient=$1 ORDER BY id DESC LIMIT 50`, u.Email)
        if err != nil {
                http.Error(w, "Не удалось загрузить письма", http.StatusInternalServerError)
                return
        }
        defer rows.Close()
        var msgs []map[string]any
        for rows.Next() {
                var to, sub, body, created string
                _ = rows.Scan(&to, &sub, &body, &created)
                msgs = append(msgs, map[string]any{"To": to, "Subject": sub, "Body": body, "Created": created})
        }
        s.render(w, r, "mail.html", Page{Title: "Уведомления", User: u, Data: map[string]any{"Messages": msgs}})
}

func (s *Server) profile(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if r.Method == http.MethodPost {
                name := strings.TrimSpace(r.FormValue("display_name"))
                email := strings.TrimSpace(r.FormValue("email"))
                _, _ = s.db.Exec(`UPDATE users SET display_name=$1, email=$2 WHERE id=$3`, name, email, u.ID)
                s.flash(w, "Профиль сохранён", true)
                http.Redirect(w, r, "/profile", http.StatusFound)
                return
        }
        fresh, _ := s.getUserByID(u.ID)
        s.render(w, r, "profile.html", Page{Title: "Профиль", User: fresh})
}
