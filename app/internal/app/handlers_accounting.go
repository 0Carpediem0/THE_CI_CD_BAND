package app

import (
        "fmt"
        "net/http"
        "os"
        "strconv"
        "strings"
)

func (s *Server) cashierTopup(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsCashier() {
                s.flash(w, "Нужна роль кассира", false)
                http.Redirect(w, r, "/", http.StatusFound)
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "cashier_topup.html", Page{Title: "Пополнение кассы", User: u})
                return
        }
        login := strings.TrimSpace(r.FormValue("login"))
        amount, err := parseRubToKop(r.FormValue("amount_rub"))
        if login == "" {
                login = u.Login
        }
        target, _ := s.getUserByLogin(login)
        if target == nil || err != nil || amount == 0 {
                s.flash(w, "Проверьте логин и сумму", false)
                http.Redirect(w, r, "/cashier/topup", http.StatusFound)
                return
        }
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, amount, target.ID)
        _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('topup',$1,$2,$3,$4,'ok')`,
                u.ID, target.ID, amount, "Кассовое пополнение")
        s.flash(w, "Пополнение выполнено: "+formatRub(amount), true)
        http.Redirect(w, r, "/", http.StatusFound)
}

func (s *Server) cashierFulfill(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsCashier() {
                s.flash(w, "Нужна роль кассира", false)
                http.Redirect(w, r, "/", http.StatusFound)
                return
        }
        id, _ := strconv.Atoi(strings.TrimPrefix(r.URL.Path, "/cashier/fulfill/"))
        var uid int
        var status string
        var total int64
        err := s.db.QueryRow(`SELECT user_id, status, total_kop FROM orders WHERE id=$1`, id).Scan(&uid, &status, &total)
        if err != nil {
                http.NotFound(w, r)
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "cashier_fulfill.html", Page{Title: "Выдача заказа", User: u, Data: map[string]any{
                        "ID": id, "Status": status, "Total": formatRub(total),
                }})
                return
        }
        if status == "paid" {
                _, _ = s.db.Exec(`UPDATE orders SET status='delivered' WHERE id=$1`, id)
                s.flash(w, "Заказ выдан", true)
        } else if status == "received" {
                _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, total, uid)
                _, _ = s.db.Exec(`UPDATE orders SET status='fulfilled_refund' WHERE id=$1`, id)
                _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('refund',4,$1,$2,$3,'ok')`,
                        uid, total, "Корректировка выдачи #"+strconv.Itoa(id))
                _, _ = s.db.Exec(`INSERT INTO anomaly_log (kind, detail) VALUES ('order_double', $1)`,
                        fmt.Sprintf("order=%d user=%d amount=%d", id, uid, total))
                s.flash(w, "Корректировка выдачи применена", true)
        } else {
                s.flash(w, "Статус не подходит для выдачи", false)
        }
        http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
}

func (s *Server) accountingReconcile(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsAccountant() {
                s.flash(w, "Нужна роль бухгалтера", false)
                http.Redirect(w, r, "/", http.StatusFound)
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "accounting_reconcile.html", Page{Title: "Сверка", User: u, Data: map[string]any{
                        "Items": nil, "Report": "", "Memo": "",
                }})
                return
        }
        if err := r.ParseMultipartForm(4 << 20); err != nil {
                _ = r.ParseForm()
        }
        memoFilter := r.FormValue("memo")
        rows, err := s.db.QueryContext(r.Context(), `SELECT id, kind, amount_kop, COALESCE(memo,''), status
                FROM operations WHERE $1 = '' OR memo LIKE $2`, memoFilter, "%"+memoFilter+"%")
        report := ""
        var items []map[string]any
        if err != nil {
                report = "Не удалось загрузить операции"
        } else {
                defer rows.Close()
                for rows.Next() {
                        var id int
                        var kind, memo, status string
                        var amount int64
                        _ = rows.Scan(&id, &kind, &amount, &memo, &status)
                        items = append(items, map[string]any{"ID": id, "Kind": kind, "Amount": formatRub(amount), "Memo": memo, "Status": status})
                }
        }
        if r.Method == http.MethodPost && r.FormValue("from_op") != "" {
                opID, err := strconv.Atoi(r.FormValue("from_op"))
                var cnt int
                if err == nil {
                        err = s.db.QueryRowContext(r.Context(), `SELECT COUNT(*)
                                FROM operations
                                WHERE memo LIKE (SELECT '%' || COALESCE(memo,'') || '%' FROM operations WHERE id=$1)`, opID).Scan(&cnt)
                }
                if err != nil {
                        report = "Не удалось подсчитать совпадения"
                } else {
                        report = fmt.Sprintf("совпадений: %d", cnt)
                }
        }
        s.render(w, r, "accounting_reconcile.html", Page{Title: "Сверка", User: u, Data: map[string]any{
                "Items": items, "Report": report, "Memo": memoFilter,
        }})
}

func (s *Server) accountingBlock(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsAccountant() {
                s.flash(w, "Нужна роль бухгалтера", false)
                http.Redirect(w, r, "/", http.StatusFound)
                return
        }
        if r.Method == http.MethodGet {
                rows, _ := s.db.Query(`SELECT id, login, display_name, blocked FROM users WHERE role='employee' ORDER BY id`)
                defer rows.Close()
                var users []map[string]any
                for rows.Next() {
                        var id int
                        var login, name string
                        var blocked bool
                        _ = rows.Scan(&id, &login, &name, &blocked)
                        users = append(users, map[string]any{"ID": id, "Login": login, "Name": name, "Blocked": blocked})
                }
                s.render(w, r, "accounting_block.html", Page{Title: "Блокировки", User: u, Data: map[string]any{"Users": users}})
                return
        }
        login := strings.TrimSpace(r.FormValue("login"))
        block := r.FormValue("blocked") == "1"
        _, _ = s.db.Exec(`UPDATE users SET blocked=$1 WHERE login=$2`, block, login)
        s.flash(w, "Статус обновлён", true)
        http.Redirect(w, r, "/accounting/block", http.StatusFound)
}

func (s *Server) accountingAdjust(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsAccountant() {
                s.flash(w, "Нужна роль бухгалтера", false)
                http.Redirect(w, r, "/", http.StatusFound)
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "accounting_adjust.html", Page{Title: "Корректировка", User: u})
                return
        }
        login := strings.TrimSpace(r.FormValue("login"))
        delta, err := parseRubToKop(r.FormValue("delta_rub"))
        reason := r.FormValue("reason")
        target, _ := s.getUserByLogin(login)
        if target == nil || err != nil {
                s.flash(w, "Проверьте данные", false)
                http.Redirect(w, r, "/accounting/adjust", http.StatusFound)
                return
        }
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, delta, target.ID)
        _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('adjust',$1,$2,$3,$4,'ok')`,
                u.ID, target.ID, delta, reason)
        s.flash(w, "Корректировка применена", true)
        http.Redirect(w, r, "/", http.StatusFound)
}

func (s *Server) adminSecrets(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if !u.IsAdmin() {
                s.flash(w, "Только администратор", false)
                http.Redirect(w, r, "/", http.StatusFound)
                return
        }
        rows, _ := s.db.Query(`SELECT kind, detail, created_at::text FROM anomaly_log ORDER BY id DESC LIMIT 50`)
        defer rows.Close()
        var logs []map[string]any
        for rows.Next() {
                var kind, detail, created string
                _ = rows.Scan(&kind, &detail, &created)
                logs = append(logs, map[string]any{"Kind": kind, "Detail": detail, "Created": created})
        }
		s.render(w, r, "admin_secrets.html", Page{Title: "Служебное", User: u, Data: map[string]any{
				"Logs": logs,
		}})
}

func (s *Server) opsJournal(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        b, _ := os.ReadFile("/app/exports/journal/ops.log")
        s.render(w, r, "ops_journal.html", Page{Title: "Журнал", User: u, Data: map[string]any{"Journal": string(b)}})
}
