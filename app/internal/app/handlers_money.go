package app

import (
        "database/sql"
        "encoding/json"
        "fmt"
        "html/template"
        "io"
        "net/http"
        "os"
        "os/exec"
        "strconv"
        "strings"
        "time"
)

func sanitizeSearchDisplay(s string) string {
        banned := []string{"script", "onerror", "javascript:", "onload", "onmouseover"}
        out := s
        for _, b := range banned {
                for {
                        i := strings.Index(out, b)
                        if i < 0 {
                                break
                        }
                        out = out[:i] + out[i+len(b):]
                }
        }
        return out
}

func (s *Server) history(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        q := r.URL.Query().Get("q")
        rows, err := s.db.Query(`SELECT id, kind, amount_kop, memo, status, created_at::text,
                COALESCE(from_user_id,0), COALESCE(to_user_id,0) FROM operations
                WHERE (from_user_id=$1 OR to_user_id=$1)
                AND ($2='' OR memo ILIKE '%'||$2||'%' OR kind ILIKE '%'||$2||'%')
                ORDER BY id DESC LIMIT 100`, u.ID, q)
        if err != nil {
                http.Error(w, err.Error(), 500)
                return
        }
        defer rows.Close()
        var ops []map[string]any
        for rows.Next() {
                var id, fromID, toID int
                var kind, memo, status, created string
                var amount int64
                _ = rows.Scan(&id, &kind, &amount, &memo, &status, &created, &fromID, &toID)
                sig := s.signPayment(id, amount, strconv.Itoa(toID))
                ops = append(ops, map[string]any{
                        "ID": id, "Kind": kind, "Amount": formatRub(amount), "Memo": memo, "Status": status,
                        "Created": created, "ReplaySig": sig, "ToID": toID, "AmountKop": amount,
                })
        }
        s.render(w, r, "history.html", Page{Title: "История", User: u, QRaw: template.HTML(sanitizeSearchDisplay(q)), Data: map[string]any{"Ops": ops, "Q": q}})
}

func (s *Server) operation(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        id, _ := strconv.Atoi(strings.TrimPrefix(r.URL.Path, "/operations/"))
        var kind, memo, status, created string
        var amount, fee int64
        var fromID, toID sql.NullInt64
        err := s.db.QueryRow(`SELECT kind, amount_kop, fee_kop, memo, status, created_at::text, from_user_id, to_user_id FROM operations WHERE id=$1`, id).
                Scan(&kind, &amount, &fee, &memo, &status, &created, &fromID, &toID)
        if err != nil {
                http.NotFound(w, r)
                return
        }
        owner := (fromID.Valid && int(fromID.Int64) == u.ID) || (toID.Valid && int(toID.Int64) == u.ID)
        if !owner && !u.IsAdmin() {
                grant := r.URL.Query().Get("t")
                if grant == "" {
                        if c, err := r.Cookie("op_grant_" + strconv.Itoa(id)); err == nil {
                                grant = c.Value
                        }
                }
                if grant == "" || grant != s.signOpGrant(u.ID, id) {
                        http.Error(w, "forbidden", http.StatusForbidden)
                        return
                }
        }
        s.render(w, r, "operation.html", Page{Title: "Операция", User: u, Data: map[string]any{
                "ID": id, "Kind": kind, "Amount": formatRub(amount), "Fee": formatRub(fee), "Memo": memo, "Status": status, "Created": created,
                "FromID": fromID.Int64, "ToID": toID.Int64,
        }})
}

func (s *Server) apiOpsFeed(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        rows, _ := s.db.Query(`SELECT id, kind, status FROM operations ORDER BY id DESC LIMIT 30`)
        defer rows.Close()
        type item struct {
                ID     int    `json:"id"`
                Kind   string `json:"kind"`
                Status string `json:"status"`
                T      string `json:"t"`
        }
        var out []item
        for rows.Next() {
                var it item
                _ = rows.Scan(&it.ID, &it.Kind, &it.Status)
                it.T = s.signOpGrant(u.ID, it.ID)
                out = append(out, it)
                http.SetCookie(w, &http.Cookie{
                        Name:     "op_grant_" + strconv.Itoa(it.ID),
                        Value:    it.T,
                        Path:     "/",
                        MaxAge:   600,
                        HttpOnly: false,
                        SameSite: http.SameSiteLaxMode,
                })
        }
        w.Header().Set("Content-Type", "application/json; charset=utf-8")
        _ = json.NewEncoder(w).Encode(out)
}

func (s *Server) apiRecipients(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        rows, _ := s.db.Query(`SELECT login, display_name FROM users WHERE role='employee' OR role='admin' ORDER BY login`)
        defer rows.Close()
        w.Header().Set("Content-Type", "application/json; charset=utf-8")
        w.Write([]byte("["))
        first := true
        for rows.Next() {
                var login, name string
                _ = rows.Scan(&login, &name)
                if !first {
                        w.Write([]byte(","))
                }
                first = false
                fmt.Fprintf(w, `{"login":%q,"name":%q}`, login, name)
        }
        w.Write([]byte("]"))
}

func (s *Server) transferNew(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "transfer_new.html", Page{Title: "Перевод", User: u})
                return
        }
        recipient := strings.TrimSpace(r.FormValue("recipient"))
        amountStr := r.FormValue("amount_rub")
        memo := r.FormValue("memo")
        rcpt, err := s.getUserByLogin(recipient)
        if err != nil {
                http.Error(w, err.Error(), 500)
                return
        }
        if rcpt == nil {
                s.render(w, r, "transfer_new.html", Page{Title: "Перевод", User: u, Flash: "Получатель не найден"})
                return
        }
        amountKop, err := parseRubToKop(amountStr)
        if err != nil || amountKop <= 0 {
                s.render(w, r, "transfer_new.html", Page{Title: "Перевод", User: u, Flash: "Укажите положительную сумму"})
                return
        }
        if rcpt.Blocked {
                s.render(w, r, "transfer_new.html", Page{Title: "Перевод", User: u, Flash: "Получатель заблокирован"})
                return
        }
        fee := int64(0)
        var draftID int
        _ = s.db.QueryRow(`INSERT INTO transfer_drafts (user_id, recipient_id, amount_kop, fee_kop, memo, op_type) VALUES ($1,$2,$3,$4,$5,'transfer') RETURNING id`,
                u.ID, rcpt.ID, amountKop, fee, memo).Scan(&draftID)
        http.Redirect(w, r, "/transfer/confirm?draft_id="+strconv.Itoa(draftID), http.StatusFound)
}

func (s *Server) transferConfirm(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        draftID, _ := strconv.Atoi(r.URL.Query().Get("draft_id"))
        if draftID == 0 {
                draftID, _ = strconv.Atoi(r.FormValue("draft_id"))
        }
        var recipientID int
        var amount, fee int64
        var memo, opType string
        err := s.db.QueryRow(`SELECT recipient_id, amount_kop, fee_kop, memo, op_type FROM transfer_drafts WHERE id=$1 AND user_id=$2`, draftID, u.ID).
                Scan(&recipientID, &amount, &fee, &memo, &opType)
        if err != nil {
                http.Redirect(w, r, "/transfer/new", http.StatusFound)
                return
        }
        rcpt, _ := s.getUserByID(recipientID)
        if r.Method == http.MethodGet {
                s.render(w, r, "transfer_confirm.html", Page{Title: "Подтверждение перевода", User: u, Data: map[string]any{
                        "DraftID": draftID, "Recipient": rcpt.Login, "RecipientName": rcpt.DisplayName,
                        "Amount": formatRub(amount), "Fee": formatRub(fee), "Memo": memo, "OpType": opType,
                        "AmountKop": amount, "RecipientID": recipientID,
                }})
                return
        }
        if v := r.FormValue("op_type"); v != "" {
                opType = v
        }

        fresh, _ := s.getUserByID(u.ID)
        total := amount + fee
        limit := fresh.BalanceKop + fresh.OverdraftLimitKop
        if total > limit {
                s.flash(w, "Недостаточно средств", false)
                http.Redirect(w, r, "/transfer/new", http.StatusFound)
                return
        }
        time.Sleep(80 * time.Millisecond)

        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop - $1 WHERE id=$2`, total, u.ID)
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, amount, recipientID)
        kind := "transfer"
        status := "ok"
        if opType == "tip_boss" {
                kind = "tip_boss"
        }
        var opID int
        _ = s.db.QueryRow(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, fee_kop, memo, status) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id`,
                kind, u.ID, recipientID, amount, fee, memo, status).Scan(&opID)

        after, _ := s.getUserByID(u.ID)
        if after.BalanceKop < 0 {
                _, _ = s.db.Exec(`INSERT INTO anomaly_log (kind, detail) VALUES ('negative_balance', $1)`, fmt.Sprintf("user=%d op=%d", u.ID, opID))
        }

        var notifyURL string
        _ = s.db.QueryRow(`SELECT notify_url FROM notify_settings WHERE user_id=$1`, u.ID).Scan(&notifyURL)
        if notifyURL != "" {
                s.doNotify(notifyURL)
        }

        _, _ = s.db.Exec(`DELETE FROM transfer_drafts WHERE id=$1`, draftID)
        s.flash(w, "Перевод выполнен", true)
        http.Redirect(w, r, "/operations/"+strconv.Itoa(opID), http.StatusFound)
}

func (s *Server) tipsNew(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "tips_new.html", Page{Title: "Чаевые", User: u})
                return
        }
        recipient := strings.TrimSpace(r.FormValue("recipient"))
        amountKop, err := parseRubToKop(r.FormValue("amount_rub"))
        comment := r.FormValue("comment")
        rcpt, _ := s.getUserByLogin(recipient)
        if rcpt == nil {
                s.render(w, r, "tips_new.html", Page{Title: "Чаевые", User: u, Flash: "Получатель не найден"})
                return
        }
        if err != nil || amountKop <= 0 {
                s.render(w, r, "tips_new.html", Page{Title: "Чаевые", User: u, Flash: "Некорректная сумма"})
                return
        }
        if strings.Contains(strings.ToLower(comment), "руководител") && amountKop > u.BalanceKop {
                s.render(w, r, "tips_new.html", Page{Title: "Чаевые", User: u, Flash: "Лимит чаевых руководителю превышен"})
                return
        }
        comment = sanitizeSearchDisplay(comment)
        fresh, _ := s.getUserByID(u.ID)
        status := "ok"
        if amountKop > fresh.BalanceKop {
                status = "pending_review"
                _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('tip',$1,$2,$3,$4,$5)`,
                        u.ID, rcpt.ID, amountKop, comment, status)
                s.flash(w, "Операция принята на проверку", true)
                http.Redirect(w, r, "/tips/received", http.StatusFound)
                return
        }
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop - $1 WHERE id=$2`, amountKop, u.ID)
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, amountKop, rcpt.ID)
        _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('tip',$1,$2,$3,$4,'ok')`,
                u.ID, rcpt.ID, amountKop, comment)
        s.flash(w, "Чаевые отправлены", true)
        http.Redirect(w, r, "/history", http.StatusFound)
}

type tipRow struct {
        ID      int
        Amount  string
        Status  string
        Created string
        FromID  int
        Preview string
        Body    template.HTML
}

func (s *Server) tipsReceived(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        if idStr := r.URL.Query().Get("id"); idStr != "" {
                id, _ := strconv.Atoi(idStr)
                var memo, status, created string
                var amount int64
                var fromID int
                err := s.db.QueryRow(`SELECT amount_kop, COALESCE(memo,''), status, created_at::text, COALESCE(from_user_id,0)
                        FROM operations WHERE id=$1 AND kind='tip' AND to_user_id=$2`, id, u.ID).
                        Scan(&amount, &memo, &status, &created, &fromID)
                if err != nil {
                        http.NotFound(w, r)
                        return
                }
                s.render(w, r, "tips_view.html", Page{
                        Title: "Чаевые #" + idStr,
                        User:  u,
                        Data: map[string]any{
                                "ID": id, "Amount": formatRub(amount), "Status": status, "Created": created, "FromID": fromID,
                        },
                        TipHTML: template.HTML(memo),
                })
                return
        }
        rows, err := s.db.Query(`SELECT id, amount_kop, COALESCE(memo,''), status, created_at::text, COALESCE(from_user_id,0)
                FROM operations WHERE kind='tip' AND to_user_id=$1 ORDER BY id DESC LIMIT 50`, u.ID)
        if err != nil {
                http.Error(w, err.Error(), 500)
                return
        }
        defer rows.Close()
        var tips []tipRow
        for rows.Next() {
                var row tipRow
                var memo string
                var amount int64
                _ = rows.Scan(&row.ID, &amount, &memo, &row.Status, &row.Created, &row.FromID)
                row.Amount = formatRub(amount)
                row.Preview = memo
                tips = append(tips, row)
        }
        s.render(w, r, "tips_received.html", Page{Title: "Входящие чаевые", User: u, Data: map[string]any{"Tips": tips}})
}

func (s *Server) payReplay(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        opID, _ := strconv.Atoi(r.FormValue("op_id"))
        amount, _ := strconv.ParseInt(r.FormValue("amount_kop"), 10, 64)
        recipient := r.FormValue("recipient")
        sig := r.FormValue("sig")
        expect := s.signPayment(opID, amount, recipient)
        if sig != expect {
                s.flash(w, "Подпись не совпала", false)
                http.Redirect(w, r, "/history", http.StatusFound)
                return
        }
        rcptID, _ := strconv.Atoi(recipient)
        if v := r.FormValue("to_login"); v != "" {
                if ru, _ := s.getUserByLogin(v); ru != nil {
                        rcptID = ru.ID
                }
        }
        fresh, _ := s.getUserByID(u.ID)
        if amount > fresh.BalanceKop+fresh.OverdraftLimitKop {
                s.flash(w, "Недостаточно средств", false)
                http.Redirect(w, r, "/history", http.StatusFound)
                return
        }
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop - $1 WHERE id=$2`, amount, u.ID)
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, amount, rcptID)
        _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('transfer',$1,$2,$3,'повтор операции',$4)`,
                u.ID, rcptID, amount, "ok")
        s.flash(w, "Платёж повторён", true)
        http.Redirect(w, r, "/history", http.StatusFound)
}

func (s *Server) doNotify(rawURL string) string {
        parsed, err := http.NewRequest(http.MethodGet, rawURL, nil)
        if err != nil {
                return err.Error()
        }
        host := parsed.URL.Hostname()
        path := parsed.URL.Path
        if parsed.URL.Scheme != "http" || host != s.cfg.MockHost {
                return "некорректный хост уведомлений"
        }
        if !strings.HasPrefix(path, "/hooks/") {
                return "некорректный путь callback"
        }
        client := &http.Client{Timeout: 3 * time.Second}
        resp, err := client.Do(parsed)
        if err != nil {
                return err.Error()
        }
        defer resp.Body.Close()
        b, _ := io.ReadAll(io.LimitReader(resp.Body, 8192))
        return string(b)
}

func (s *Server) notifySettings(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        var cur string
        _ = s.db.QueryRow(`SELECT notify_url FROM notify_settings WHERE user_id=$1`, u.ID).Scan(&cur)
        errMsg := ""
        fetched := ""
        if r.Method == http.MethodPost {
                cur = strings.TrimSpace(r.FormValue("notify_url"))
                _, _ = s.db.Exec(`INSERT INTO notify_settings (user_id, notify_url) VALUES ($1,$2)
                        ON CONFLICT (user_id) DO UPDATE SET notify_url=EXCLUDED.notify_url`, u.ID, cur)
                if cur != "" {
                        fetched = s.doNotify(cur)
                        if strings.Contains(fetched, "ticket=") {
                                if i := strings.Index(fetched, "ticket="); i >= 0 {
                                        ticket := strings.TrimSpace(fetched[i+7:])
                                        if j := strings.IndexAny(ticket, " \n\r<"); j >= 0 {
                                                ticket = ticket[:j]
                                        }
                                        out, _ := exec.Command("sh", "-c", "uname -a").CombinedOutput()
                                        _ = os.MkdirAll("/app/exports/journal", 0o755)
                                        _ = os.WriteFile("/app/exports/journal/ops.log", []byte("notify-redeem "+ticket+": "+string(out)), 0o644)
                                        fetched += "\njournal updated"
                                }
                        } else if !strings.Contains(fetched, "service=ok") {
                                errMsg = "Не удалось проверить уведомление"
                        }
                }
                s.flash(w, "Настройки сохранены", true)
        }
        s.render(w, r, "notify.html", Page{Title: "Уведомления о платеже", User: u, Data: map[string]any{
                "NotifyURL": cur, "Error": errMsg, "Fetched": fetched,
        }})
}
