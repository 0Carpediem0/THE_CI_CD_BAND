package app

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"html/template"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"
)

func (s *Server) shop(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	rows, _ := s.db.Query(`SELECT id, code, title, price_kop FROM products WHERE active=TRUE ORDER BY id`)
	defer rows.Close()
	var items []map[string]any
	for rows.Next() {
		var id int
		var code, title string
		var price int64
		_ = rows.Scan(&id, &code, &title, &price)
		items = append(items, map[string]any{"ID": id, "Code": code, "Title": title, "Price": formatRub(price), "PriceKop": price})
	}
	s.render(w, r, "shop.html", Page{Title: "Магазин", User: u, Data: map[string]any{"Items": items}})
}

func (s *Server) apiCatalog(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	rows, _ := s.db.Query(`SELECT id, code, title, price_kop FROM products WHERE active=TRUE`)
	defer rows.Close()
	type item struct {
		ID       int    `json:"id"`
		Code     string `json:"code"`
		Title    string `json:"title"`
		PriceKop int64  `json:"price_kop"`
	}
	var out []item
	for rows.Next() {
		var it item
		_ = rows.Scan(&it.ID, &it.Code, &it.Title, &it.PriceKop)
		out = append(out, it)
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(map[string]any{"items": out})
}

func (s *Server) apiSupplyPricing(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	if !u.IsAccountant() {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	if r.Header.Get("X-Wallet-Channel") != s.supplyChannel() {
		http.Error(w, `{"error":"channel required"}`, http.StatusForbidden)
		return
	}
	rows, _ := s.db.Query(`SELECT id, code, price_kop, cost_kop, COALESCE(supplier_note,'') FROM products WHERE active=TRUE`)
	defer rows.Close()
	type item struct {
		ID           int    `json:"id"`
		Code         string `json:"code"`
		PriceKop     int64  `json:"price_kop"`
		CostKop      int64  `json:"cost_kop"`
		SupplierNote string `json:"supplier_note"`
	}
	var out []item
	for rows.Next() {
		var it item
		_ = rows.Scan(&it.ID, &it.Code, &it.PriceKop, &it.CostKop, &it.SupplierNote)
		out = append(out, it)
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(out)
}

func (s *Server) cart(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	rows, _ := s.db.Query(`SELECT c.id, p.title, p.price_kop, c.qty, c.product_id FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.user_id=$1`, u.ID)
	defer rows.Close()
	var items []map[string]any
	var sum int64
	for rows.Next() {
		var id, qty, pid int
		var title string
		var price int64
		_ = rows.Scan(&id, &title, &price, &qty, &pid)
		line := price * int64(qty)
		sum += line
		items = append(items, map[string]any{"ID": id, "Title": title, "Price": formatRub(price), "Qty": qty, "Line": formatRub(line), "ProductID": pid, "PriceKop": price})
	}
	s.render(w, r, "cart.html", Page{Title: "Корзина", User: u, Data: map[string]any{"Items": items, "Sum": formatRub(sum), "SumKop": sum}})
}

func (s *Server) cartAdd(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	if r.Method != http.MethodPost {
		http.Redirect(w, r, "/shop", http.StatusFound)
		return
	}
	pid, _ := strconv.Atoi(r.FormValue("product_id"))
	res, err := s.db.Exec(`INSERT INTO cart_items (user_id, product_id, qty)
                SELECT $1, id, 1 FROM products WHERE id=$2 AND active`, u.ID, pid)
	if err != nil {
		s.flash(w, "Не удалось добавить товар", false)
		http.Redirect(w, r, "/shop", http.StatusFound)
		return
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		s.flash(w, "Товар недоступен", false)
		http.Redirect(w, r, "/shop", http.StatusFound)
		return
	}
	s.flash(w, "Добавлено в корзину", true)
	http.Redirect(w, r, "/cart", http.StatusFound)
}

type cartLine struct {
	ProductID int    `json:"product_id"`
	Title     string `json:"title"`
	PriceKop  int64  `json:"price_kop"`
	Qty       int    `json:"qty"`
}

func lineRefundKop(linesJSON string, qty int) (int64, error) {
	if qty <= 0 {
		return 0, fmt.Errorf("qty")
	}
	var lines []cartLine
	if err := json.Unmarshal([]byte(linesJSON), &lines); err != nil || len(lines) == 0 {
		return 0, fmt.Errorf("lines")
	}
	left := qty
	var sum int64
	for _, l := range lines {
		if l.Qty <= 0 || l.PriceKop < 0 {
			return 0, fmt.Errorf("line")
		}
		take := l.Qty
		if take > left {
			take = left
		}
		if take > 0 && l.PriceKop > 0 && int64(take) > math.MaxInt64/l.PriceKop {
			return 0, fmt.Errorf("overflow")
		}
		part := l.PriceKop * int64(take)
		if sum > math.MaxInt64-part {
			return 0, fmt.Errorf("overflow")
		}
		sum += part
		left -= take
		if left == 0 {
			break
		}
	}
	if left > 0 || sum <= 0 {
		return 0, fmt.Errorf("qty")
	}
	return sum, nil
}

func cartSnapshot(lines []cartLine) (string, error) {
	type row struct {
		ProductID int   `json:"product_id"`
		PriceKop  int64 `json:"price_kop"`
		Qty       int   `json:"qty"`
	}
	rows := make([]row, 0, len(lines))
	for _, l := range lines {
		rows = append(rows, row{ProductID: l.ProductID, PriceKop: l.PriceKop, Qty: l.Qty})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].ProductID == rows[j].ProductID {
			return rows[i].Qty < rows[j].Qty
		}
		return rows[i].ProductID < rows[j].ProductID
	})
	b, err := json.Marshal(rows)
	return string(b), err
}

func (s *Server) loadCart(userID int) ([]cartLine, int64) {
	rows, err := s.db.Query(`SELECT p.id, p.title, p.price_kop, c.qty FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.user_id=$1 ORDER BY p.id, c.id`, userID)
	if err != nil {
		return nil, 0
	}
	defer rows.Close()
	var lines []cartLine
	var sum int64
	for rows.Next() {
		var l cartLine
		_ = rows.Scan(&l.ProductID, &l.Title, &l.PriceKop, &l.Qty)
		lines = append(lines, l)
		sum += l.PriceKop * int64(l.Qty)
	}
	return lines, sum
}

func (s *Server) checkout(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	lines, dbSum := s.loadCart(u.ID)
	if r.Method == http.MethodGet {
		s.render(w, r, "checkout.html", Page{Title: "Оформление", User: u, Data: map[string]any{
			"Sum": formatRub(dbSum), "SumKop": dbSum, "Lines": lines,
		}})
		return
	}
	http.Redirect(w, r, "/checkout", http.StatusFound)
}

func (s *Server) checkoutQuote(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	if r.Method != http.MethodPost {
		http.Redirect(w, r, "/checkout", http.StatusFound)
		return
	}
	_, dbSum := s.loadCart(u.ID)
	if dbSum <= 0 {
		s.flash(w, "Корзина пуста", false)
		http.Redirect(w, r, "/cart", http.StatusFound)
		return
	}
	lines, _ := s.loadCart(u.ID)
	promoCode := strings.TrimSpace(r.FormValue("promo_code"))
	tipRaw := strings.TrimSpace(r.FormValue("tip_kop"))
	if tipRaw == "" {
		tipRaw = "0"
	}
	tipKop, tipErr := strconv.ParseInt(tipRaw, 10, 64)
	itemComment := r.FormValue("item_comment")
	promoPct := 0
	if promoCode != "" {
		_ = s.db.QueryRow(`SELECT percent FROM promo_codes WHERE code=$1`, promoCode).Scan(&promoPct)
	}
	badAmount := func() {
		s.flash(w, "Некорректная сумма", false)
		http.Redirect(w, r, "/checkout", http.StatusFound)
	}
	if tipErr != nil || tipKop < 0 || promoPct < 0 || promoPct > 100 {
		badAmount()
		return
	}
	discounted := dbSum - dbSum*int64(promoPct)/100
	if discounted < 0 || tipKop > math.MaxInt64-discounted {
		badAmount()
		return
	}
	chargeKop := discounted + tipKop
	if chargeKop < 0 {
		badAmount()
		return
	}
	snap, err := cartSnapshot(lines)
	if err != nil {
		badAmount()
		return
	}
	var qid int
	err = s.db.QueryRow(`INSERT INTO checkout_quotes (user_id, total_kop, promo_code, tip_kop, item_comment, lines_json) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id`,
		u.ID, chargeKop, promoCode, tipKop, itemComment, snap).Scan(&qid)
	if err != nil {
		s.internalError(w, err)
		return
	}
	s.render(w, r, "checkout_confirm.html", Page{Title: "Подтверждение оплаты", User: u, Data: map[string]any{
		"QuoteID": qid, "Sum": formatRub(chargeKop), "Promo": promoCode,
	}})
}

func (s *Server) checkoutConfirm(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	if r.Method != http.MethodPost {
		http.Redirect(w, r, "/checkout", http.StatusFound)
		return
	}
	qid, _ := strconv.Atoi(r.FormValue("quote_id"))
	ctx := r.Context()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		s.internalError(w, err)
		return
	}
	defer tx.Rollback()
	var total int64
	var comment, snap string
	var used bool
	err = tx.QueryRowContext(ctx, `SELECT total_kop, item_comment, lines_json, used FROM checkout_quotes WHERE id=$1 AND user_id=$2 FOR UPDATE`, qid, u.ID).
		Scan(&total, &comment, &snap, &used)
	if err != nil || used {
		s.flash(w, "Котировка недействительна", false)
		http.Redirect(w, r, "/checkout", http.StatusFound)
		return
	}
	rows, err := tx.QueryContext(ctx, `SELECT p.id, p.title, p.price_kop, c.qty FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.user_id=$1 ORDER BY p.id, c.id`, u.ID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	var lines []cartLine
	for rows.Next() {
		var l cartLine
		if err := rows.Scan(&l.ProductID, &l.Title, &l.PriceKop, &l.Qty); err != nil {
			rows.Close()
			s.internalError(w, err)
			return
		}
		lines = append(lines, l)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		s.internalError(w, err)
		return
	}
	rows.Close()
	if len(lines) == 0 {
		s.flash(w, "Корзина пуста", false)
		http.Redirect(w, r, "/cart", http.StatusFound)
		return
	}
	live, err := cartSnapshot(lines)
	if err != nil || live != snap {
		s.flash(w, "Корзина изменилась, получите новую котировку", false)
		http.Redirect(w, r, "/checkout", http.StatusFound)
		return
	}
	var balance, overdraft int64
	err = tx.QueryRowContext(ctx, `SELECT balance_kop, overdraft_limit_kop FROM users WHERE id=$1 FOR UPDATE`, u.ID).Scan(&balance, &overdraft)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if total < 0 || total > balance+overdraft {
		s.flash(w, "Недостаточно средств", false)
		http.Redirect(w, r, "/cart", http.StatusFound)
		return
	}
	res, err := tx.ExecContext(ctx, `UPDATE users SET balance_kop = balance_kop - $1 WHERE id=$2 AND balance_kop + overdraft_limit_kop >= $1`, total, u.ID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if n, _ := res.RowsAffected(); n != 1 {
		s.flash(w, "Недостаточно средств", false)
		http.Redirect(w, r, "/cart", http.StatusFound)
		return
	}
	res, err = tx.ExecContext(ctx, `UPDATE checkout_quotes SET used=TRUE WHERE id=$1 AND used=FALSE`, qid)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if n, _ := res.RowsAffected(); n != 1 {
		s.flash(w, "Котировка недействительна", false)
		http.Redirect(w, r, "/checkout", http.StatusFound)
		return
	}
	b, err := json.Marshal(lines)
	if err != nil {
		s.internalError(w, err)
		return
	}
	var orderID int
	err = tx.QueryRowContext(ctx, `INSERT INTO orders (user_id, status, total_kop, lines_json, item_comment) VALUES ($1,'paid',$2,$3,$4) RETURNING id`,
		u.ID, total, string(b), comment).Scan(&orderID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM cart_items WHERE user_id=$1`, u.ID); err != nil {
		s.internalError(w, err)
		return
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('purchase',$1,4,$2,$3,'ok')`,
		u.ID, total, "Заказ #"+strconv.Itoa(orderID)); err != nil {
		s.internalError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		s.internalError(w, err)
		return
	}
	s.flash(w, "Заказ оформлен", true)
	http.Redirect(w, r, "/orders/"+strconv.Itoa(orderID), http.StatusFound)
}

func (s *Server) ordersRouter(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/orders/")
	parts := strings.Split(path, "/")
	if len(parts) == 0 || parts[0] == "" {
		http.NotFound(w, r)
		return
	}
	id, _ := strconv.Atoi(parts[0])
	if len(parts) == 1 {
		s.orderView(w, r, id)
		return
	}
	switch parts[1] {
	case "cancel":
		s.orderCancel(w, r, id)
	case "return":
		s.orderReturn(w, r, id)
	case "received":
		s.orderReceived(w, r, id)
	case "preview":
		s.orderPreview(w, r, id)
	default:
		http.NotFound(w, r)
	}
}

type orderRec struct {
	UserID   int
	Status   string
	Total    int64
	Lines    string
	Comment  string
	Refunded int64
}

func (s *Server) loadOrderForUser(id int, u *User) (*orderRec, bool) {
	var o orderRec
	err := s.db.QueryRow(`SELECT user_id, status, total_kop, lines_json, COALESCE(item_comment,''), refunded_kop FROM orders WHERE id=$1`, id).
		Scan(&o.UserID, &o.Status, &o.Total, &o.Lines, &o.Comment, &o.Refunded)
	if err != nil || (o.UserID != u.ID && !u.IsCashier()) {
		return nil, false
	}
	return &o, true
}

func (s *Server) orderView(w http.ResponseWriter, r *http.Request, id int) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	o, ok := s.loadOrderForUser(id, u)
	if !ok {
		http.NotFound(w, r)
		return
	}
	s.render(w, r, "order.html", Page{Title: "Заказ", User: u, Data: map[string]any{
		"ID": id, "Status": o.Status, "Total": formatRub(o.Total), "Lines": o.Lines, "Comment": o.Comment,
		"Owner": o.UserID == u.ID, "Cashier": u.IsCashier(),
	}})
}

func (s *Server) orderCancel(w http.ResponseWriter, r *http.Request, id int) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	o, ok := s.loadOrderForUser(id, u)
	if !ok || o.UserID != u.ID {
		http.NotFound(w, r)
		return
	}
	if r.Method == http.MethodGet {
		s.render(w, r, "order_cancel.html", Page{Title: "Отмена заказа", User: u, Data: map[string]any{"ID": id, "Total": formatRub(o.Total)}})
		return
	}
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "GET, POST")
		http.Error(w, "Метод не поддерживается", http.StatusMethodNotAllowed)
		return
	}
	ctx := r.Context()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		s.internalError(w, err)
		return
	}
	defer tx.Rollback()
	var total int64
	err = tx.QueryRowContext(ctx, `UPDATE orders SET status='cancelled' WHERE id=$1 AND user_id=$2 AND status IN ('paid','delivered') RETURNING total_kop`, id, u.ID).Scan(&total)
	if err != nil {
		s.flash(w, "Заказ нельзя отменить", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
		return
	}
	if _, err := tx.ExecContext(ctx, `UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, total, u.ID); err != nil {
		s.internalError(w, err)
		return
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('refund',4,$1,$2,$3,'ok')`,
		u.ID, total, "Отмена заказа #"+strconv.Itoa(id)); err != nil {
		s.internalError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		s.internalError(w, err)
		return
	}
	s.flash(w, "Заказ отменён", true)
	http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
}

func (s *Server) orderReturn(w http.ResponseWriter, r *http.Request, id int) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	o, ok := s.loadOrderForUser(id, u)
	if !ok || o.UserID != u.ID {
		s.flash(w, "Чужой заказ", false)
		http.Redirect(w, r, "/shop", http.StatusFound)
		return
	}
	if r.Method == http.MethodGet {
		s.render(w, r, "order_return.html", Page{Title: "Возврат", User: u, Data: map[string]any{"ID": id, "Status": o.Status, "Total": formatRub(o.Total - o.Refunded)}})
		return
	}
	qty, _ := strconv.Atoi(r.FormValue("qty"))
	if qty <= 0 {
		s.flash(w, "Некорректное количество", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id)+"/return", http.StatusFound)
		return
	}
	ctx := r.Context()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		s.internalError(w, err)
		return
	}
	defer tx.Rollback()
	var total, refunded int64
	var linesJSON string
	err = tx.QueryRowContext(ctx, `SELECT total_kop, refunded_kop, lines_json FROM orders WHERE id=$1 AND user_id=$2 AND status IN ('paid','delivered','received') FOR UPDATE`, id, u.ID).Scan(&total, &refunded, &linesJSON)
	if err != nil || refunded >= total {
		s.flash(w, "Возврат недоступен", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
		return
	}
	remaining := total - refunded
	requested, reqErr := lineRefundKop(linesJSON, qty)
	if reqErr != nil || remaining <= 0 || requested <= 0 {
		s.flash(w, "Сумма возврата превышает оплаченное", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id)+"/return", http.StatusFound)
		return
	}
	refund := requested
	if refund > remaining {
		refund = remaining
	}
	if refund <= 0 || refund > total || refund > remaining {
		s.flash(w, "Сумма возврата превышает оплаченное", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id)+"/return", http.StatusFound)
		return
	}
	if _, err := tx.ExecContext(ctx, `UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, refund, u.ID); err != nil {
		s.internalError(w, err)
		return
	}
	res, err := tx.ExecContext(ctx, `UPDATE orders SET refunded_kop = refunded_kop + $1,
                status = CASE WHEN refunded_kop + $1 >= total_kop THEN 'returned' ELSE status END
                WHERE id=$2 AND user_id=$3 AND status IN ('paid','delivered','received') AND refunded_kop + $1 <= total_kop`, refund, id, u.ID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if n, _ := res.RowsAffected(); n != 1 {
		s.flash(w, "Возврат недоступен", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
		return
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('refund',4,$1,$2,$3,'ok')`,
		u.ID, refund, "Возврат заказа #"+strconv.Itoa(id)); err != nil {
		s.internalError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		s.internalError(w, err)
		return
	}
	s.flash(w, "Возврат проведён", true)
	http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
}

func (s *Server) orderReceived(w http.ResponseWriter, r *http.Request, id int) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		http.Error(w, "Метод не поддерживается", http.StatusMethodNotAllowed)
		return
	}
	o, ok := s.loadOrderForUser(id, u)
	if !ok || o.UserID != u.ID {
		http.Redirect(w, r, "/shop", http.StatusFound)
		return
	}
	res, err := s.db.Exec(`UPDATE orders SET status='received' WHERE id=$1 AND user_id=$2 AND status IN ('paid','delivered')`, id, u.ID)
	if err != nil {
		s.internalError(w, err)
		return
	}
	if n, _ := res.RowsAffected(); n != 1 {
		s.flash(w, "Статус не подходит", false)
		http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
		return
	}
	s.flash(w, "Отмечено получение", true)
	http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
}

func (s *Server) orderPreview(w http.ResponseWriter, r *http.Request, id int) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	var comment string
	var total int64
	err := s.db.QueryRowContext(r.Context(), `SELECT total_kop, COALESCE(item_comment,'')
                FROM orders WHERE id=$1 AND user_id=$2`, id, u.ID).Scan(&total, &comment)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	label := "Комментарий"
	if r.URL.Query().Get("renderer") == "classic" {
		label = "Позиция"
	}
	receipt := fmt.Sprintf("Чек заказа #%d\nСумма: %s\n%s: %s\n", id, formatRub(total), label, comment)
	s.render(w, r, "order_preview.html", Page{
		Title:   "Превью чека",
		User:    u,
		Preview: template.HTML("<pre class=\"receipt-preview\">" + template.HTMLEscapeString(receipt) + "</pre>"),
		Data:    map[string]any{"ID": id},
	})
}

func (s *Server) statementExport(w http.ResponseWriter, r *http.Request) {
	u := s.requireUser(w, r)
	if u == nil {
		return
	}
	if r.Method == http.MethodGet {
		s.render(w, r, "statement.html", Page{Title: "Выписка", User: u})
		return
	}
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "GET, POST")
		http.Error(w, "Метод не поддерживается", http.StatusMethodNotAllowed)
		return
	}
	rows, err := s.db.QueryContext(r.Context(), `SELECT id, kind, amount_kop FROM operations
                WHERE from_user_id=$1 OR to_user_id=$1 ORDER BY id DESC`, u.ID)
	if err != nil {
		http.Error(w, "Не удалось сформировать выписку", http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	var out bytes.Buffer
	csvWriter := csv.NewWriter(&out)
	_ = csvWriter.Write([]string{"id", "kind", "amount"})
	for rows.Next() {
		var id int
		var kind string
		var amount int64
		if err := rows.Scan(&id, &kind, &amount); err != nil {
			http.Error(w, "Не удалось сформировать выписку", http.StatusInternalServerError)
			return
		}
		_ = csvWriter.Write([]string{strconv.Itoa(id), kind, strconv.FormatInt(amount, 10)})
	}
	csvWriter.Flush()
	if rows.Err() != nil || csvWriter.Error() != nil {
		http.Error(w, "Не удалось сформировать выписку", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", `attachment; filename="statement.csv"`)
	_, _ = w.Write(out.Bytes())
}
