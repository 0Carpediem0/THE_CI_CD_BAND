package app

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

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
		s.internalError(w, err)
		return
	}
	defer rows.Close()
	var ops []map[string]any
	for rows.Next() {
		var id, fromID, toID int
		var kind, memo, status, created string
		var amount int64
		_ = rows.Scan(&id, &kind, &amount, &memo, &status, &created, &fromID, &toID)
		ops = append(ops, map[string]any{
			"ID": id, "Kind": kind, "Amount": formatRub(amount), "Memo": memo, "Status": status,
			"Created": created, "ToID": toID, "AmountKop": amount,
		})
	}
	s.render(w, r, "history.html", Page{Title: "История", User: u, Data: map[string]any{"Ops": ops, "Q": q}})
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
	if !owner && !u.IsAdmin() && !u.IsAccountant() {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
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
	privileged := u.IsAdmin() || u.IsAccountant()
	rows, err := s.db.Query(`SELECT id, kind, status FROM operations
                WHERE $1 OR from_user_id=$2 OR to_user_id=$2
                ORDER BY id DESC LIMIT 30`, privileged, u.ID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	defer rows.Close()
	type item struct {
		ID     int    `json:"id"`
		Kind   string `json:"kind"`
		Status string `json:"status"`
	}
	var out []item
	for rows.Next() {
		var it item
		_ = rows.Scan(&it.ID, &it.Kind, &it.Status)
		out = append(out, it)
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(out)
}

func (s *Server) apiRecipients(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	login := strings.TrimSpace(r.URL.Query().Get("login"))
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if login == "" {
		w.Write([]byte("[]"))
		return
	}
	var found string
	err := s.db.QueryRow(`SELECT login FROM users WHERE login=$1 AND role IN ('employee','admin')`, login).Scan(&found)
	if err != nil {
		w.Write([]byte("[]"))
		return
	}
	fmt.Fprintf(w, `[{"login":%q}]`, found)
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
		s.internalError(w, err)
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
	ctx := r.Context()
	var recipientID int
	var amount, fee int64
	var memo, opType string
	if r.Method == http.MethodGet {
		err := s.db.QueryRowContext(ctx, `SELECT recipient_id, amount_kop, fee_kop, memo, op_type
                        FROM transfer_drafts WHERE id=$1 AND user_id=$2`, draftID, u.ID).
			Scan(&recipientID, &amount, &fee, &memo, &opType)
		if err != nil {
			http.Redirect(w, r, "/transfer/new", http.StatusFound)
			return
		}
		rcpt, err := s.getUserByID(recipientID)
		if err != nil || rcpt == nil {
			http.NotFound(w, r)
			return
		}
		s.render(w, r, "transfer_confirm.html", Page{Title: "Подтверждение перевода", User: u, Data: map[string]any{
			"DraftID": draftID, "Recipient": rcpt.Login, "RecipientName": rcpt.DisplayName,
			"Amount": formatRub(amount), "Fee": formatRub(fee), "Memo": memo, "OpType": opType,
			"AmountKop": amount, "RecipientID": recipientID,
		}})
		return
	}
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "GET, POST")
		http.Error(w, "Метод не поддерживается", http.StatusMethodNotAllowed)
		return
	}

	failed := func() {
		http.Error(w, "Не удалось провести перевод", http.StatusInternalServerError)
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		failed()
		return
	}
	defer tx.Rollback()

	err = tx.QueryRowContext(ctx, `DELETE FROM transfer_drafts WHERE id=$1 AND user_id=$2
                RETURNING recipient_id, amount_kop, fee_kop, memo, op_type`, draftID, u.ID).
		Scan(&recipientID, &amount, &fee, &memo, &opType)
	if err == sql.ErrNoRows {
		http.Redirect(w, r, "/transfer/new", http.StatusFound)
		return
	}
	if err != nil {
		failed()
		return
	}
	if amount <= 0 || fee < 0 || fee > math.MaxInt64-amount {
		http.Error(w, "Некорректная сумма", http.StatusBadRequest)
		return
	}
	kind := "transfer"
	if opType == "tip_boss" {
		kind = "tip_boss"
	}

	// Lock accounts in the same order for transfers in either direction.
	if _, err := tx.ExecContext(ctx, `SELECT id FROM users WHERE id IN ($1, $2) ORDER BY id FOR UPDATE`, u.ID, recipientID); err != nil {
		failed()
		return
	}

	var debitBalance int64
	err = tx.QueryRowContext(ctx, `UPDATE users SET balance_kop=balance_kop-$1
                WHERE id=$2 AND NOT blocked AND balance_kop::numeric + overdraft_limit_kop >= $1
                RETURNING balance_kop`, amount+fee, u.ID).Scan(&debitBalance)
	if err == sql.ErrNoRows {
		s.flash(w, "Недостаточно средств или счёт заблокирован", false)
		http.Redirect(w, r, "/transfer/new", http.StatusFound)
		return
	}
	if err != nil {
		failed()
		return
	}

	var recipientBalance int64
	err = tx.QueryRowContext(ctx, `UPDATE users SET balance_kop=balance_kop+$1
                WHERE id=$2 AND NOT blocked RETURNING balance_kop`, amount, recipientID).Scan(&recipientBalance)
	if err == sql.ErrNoRows {
		s.flash(w, "Получатель недоступен", false)
		http.Redirect(w, r, "/transfer/new", http.StatusFound)
		return
	}
	if err != nil {
		failed()
		return
	}

	var opID int
	err = tx.QueryRowContext(ctx, `INSERT INTO operations
                (kind, from_user_id, to_user_id, amount_kop, fee_kop, memo, status)
                VALUES ($1,$2,$3,$4,$5,$6,'ok') RETURNING id`,
		kind, u.ID, recipientID, amount, fee, memo).Scan(&opID)
	if err != nil {
		failed()
		return
	}
	if u.ID == recipientID {
		debitBalance = recipientBalance
	}
	if debitBalance < 0 {
		if _, err := tx.ExecContext(ctx, `INSERT INTO anomaly_log (kind, detail) VALUES ('negative_balance', $1)`, fmt.Sprintf("user=%d op=%d", u.ID, opID)); err != nil {
			failed()
			return
		}
	}
	if err := tx.Commit(); err != nil {
		failed()
		return
	}

	var notifyURL string
	_ = s.db.QueryRow(`SELECT notify_url FROM notify_settings WHERE user_id=$1`, u.ID).Scan(&notifyURL)
	if notifyURL != "" {
		s.doNotify(notifyURL)
	}

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
	ctx := r.Context()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		s.internalError(w, err)
		return
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `SELECT id FROM users WHERE id IN ($1, $2) ORDER BY id FOR UPDATE`, u.ID, rcpt.ID); err != nil {
		s.internalError(w, err)
		return
	}
	var balance int64
	if err := tx.QueryRowContext(ctx, `SELECT balance_kop FROM users WHERE id=$1`, u.ID).Scan(&balance); err != nil {
		s.internalError(w, err)
		return
	}
	if amountKop > balance {
		s.flash(w, "Недостаточно средств", false)
		http.Redirect(w, r, "/tips/new", http.StatusFound)
		return
	}
	res, err := tx.ExecContext(ctx, `UPDATE users SET balance_kop = balance_kop - $1 WHERE id=$2 AND balance_kop >= $1`, amountKop, u.ID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if n, _ := res.RowsAffected(); n != 1 {
		s.flash(w, "Недостаточно средств", false)
		http.Redirect(w, r, "/tips/new", http.StatusFound)
		return
	}
	if _, err := tx.ExecContext(ctx, `UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, amountKop, rcpt.ID); err != nil {
		s.internalError(w, err)
		return
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('tip',$1,$2,$3,$4,'ok')`,
		u.ID, rcpt.ID, amountKop, comment); err != nil {
		s.internalError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		s.internalError(w, err)
		return
	}
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
				"ID": id, "Amount": formatRub(amount), "Status": status, "Created": created, "FromID": fromID, "Memo": memo,
			},
		})
		return
	}
	rows, err := s.db.Query(`SELECT id, amount_kop, COALESCE(memo,''), status, created_at::text, COALESCE(from_user_id,0)
                FROM operations WHERE kind='tip' AND to_user_id=$1 ORDER BY id DESC LIMIT 50`, u.ID)
	if err != nil {
		s.internalError(w, err)
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
	if u := s.requireUser(w, r); u == nil {
		return
	}
	http.Redirect(w, r, "/transfer/new", http.StatusFound)
}

func (s *Server) doNotify(rawURL string) string {
	parsed, err := http.NewRequest(http.MethodGet, rawURL, nil)
	if err != nil {
		return "некорректный адрес"
	}
	host := parsed.URL.Hostname()
	path := parsed.URL.Path
	if parsed.URL.Scheme != "http" || host != s.cfg.MockHost {
		return "некорректный хост уведомлений"
	}
	if !strings.HasPrefix(path, "/hooks/") {
		return "некорректный путь callback"
	}
	client := &http.Client{
		Timeout: 3 * time.Second,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	resp, err := client.Do(parsed)
	if err != nil {
		return "не удалось связаться с сервисом уведомлений"
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
			if !strings.Contains(fetched, "service=ok") {
				errMsg = "Не удалось проверить уведомление"
			}
		}
		s.flash(w, "Настройки сохранены", true)
	}
	s.render(w, r, "notify.html", Page{Title: "Уведомления о платеже", User: u, Data: map[string]any{
		"NotifyURL": cur, "Error": errMsg, "Fetched": fetched,
	}})
}
