package app

import (
        "encoding/json"
        "fmt"
        "html/template"
        "net/http"
        "os"
        "path/filepath"
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
        type catalogResp struct {
                Items []item         `json:"items"`
                Meta  map[string]any `json:"meta"`
        }
        ch := s.supplyChannel()
        half := len(ch) / 2
        meta := map[string]any{
                "pos":     true,
                "ch_pref": ch[:half],
        }
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("X-Wallet-Sync-Part", ch[half:])
		_ = json.NewEncoder(w).Encode(catalogResp{Items: out, Meta: meta})
}

func (s *Server) apiSupplyPricing(w http.ResponseWriter, r *http.Request) {
        u := s.requireUser(w, r)
        if u == nil {
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
        _, _ = s.db.Exec(`INSERT INTO cart_items (user_id, product_id, qty) VALUES ($1,$2,1)`, u.ID, pid)
        s.flash(w, "Добавлено в корзину", true)
        http.Redirect(w, r, "/cart", http.StatusFound)
}

type cartLine struct {
        ProductID int    `json:"product_id"`
        Title     string `json:"title"`
        PriceKop  int64  `json:"price_kop"`
        Qty       int    `json:"qty"`
}

func (s *Server) loadCart(userID int) ([]cartLine, int64) {
        rows, err := s.db.Query(`SELECT p.id, p.title, p.price_kop, c.qty FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.user_id=$1`, userID)
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
        promoCode := strings.TrimSpace(r.FormValue("promo_code"))
        tipKop, _ := strconv.ParseInt(r.FormValue("tip_kop"), 10, 64)
        if tipKop < 0 {
                tipKop = 0
        }
        itemComment := r.FormValue("item_comment")
        promoPct := 0
        if promoCode != "" {
                _ = s.db.QueryRow(`SELECT percent FROM promo_codes WHERE code=$1`, promoCode).Scan(&promoPct)
        }
        chargeKop := dbSum - dbSum*int64(promoPct)/100 + tipKop
        if chargeKop < 0 {
                chargeKop = 0
        }
        var qid int
        _ = s.db.QueryRow(`INSERT INTO checkout_quotes (user_id, total_kop, promo_code, tip_kop, item_comment) VALUES ($1,$2,$3,$4,$5) RETURNING id`,
                u.ID, chargeKop, promoCode, tipKop, itemComment).Scan(&qid)
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
        var total, tip int64
        var promo, comment string
        var used bool
        err := s.db.QueryRow(`SELECT total_kop, promo_code, tip_kop, item_comment, used FROM checkout_quotes WHERE id=$1 AND user_id=$2`, qid, u.ID).
                Scan(&total, &promo, &tip, &comment, &used)
        if err != nil || used {
                s.flash(w, "Котировка недействительна", false)
                http.Redirect(w, r, "/checkout", http.StatusFound)
                return
        }
        lines, liveSum := s.loadCart(u.ID)
        if len(lines) == 0 {
                s.flash(w, "Корзина пуста", false)
                http.Redirect(w, r, "/cart", http.StatusFound)
                return
        }
        fresh, _ := s.getUserByID(u.ID)
        if total > fresh.BalanceKop+fresh.OverdraftLimitKop {
                s.flash(w, "Недостаточно средств", false)
                http.Redirect(w, r, "/cart", http.StatusFound)
                return
        }
        _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop - $1 WHERE id=$2`, total, u.ID)
        _, _ = s.db.Exec(`UPDATE checkout_quotes SET used=TRUE WHERE id=$1`, qid)
        if liveSum > total {
                _, _ = s.db.Exec(`INSERT INTO anomaly_log (kind, detail) VALUES ('quote_drift', $1)`,
                        fmt.Sprintf("user=%d quote=%d charged=%d cart=%d", u.ID, qid, total, liveSum))
        }
        b, _ := json.Marshal(lines)
        var orderID int
        _ = s.db.QueryRow(`INSERT INTO orders (user_id, status, total_kop, lines_json, item_comment) VALUES ($1,'paid',$2,$3,$4) RETURNING id`,
                u.ID, total, string(b), comment).Scan(&orderID)
        _, _ = s.db.Exec(`DELETE FROM cart_items WHERE user_id=$1`, u.ID)
        _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('purchase',$1,4,$2,$3,'ok')`,
                u.ID, total, "Заказ #"+strconv.Itoa(orderID))
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

func (s *Server) orderView(w http.ResponseWriter, r *http.Request, id int) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        var uid int
        var status, lines, comment string
        var total int64
        err := s.db.QueryRow(`SELECT user_id, status, total_kop, lines_json, COALESCE(item_comment,'') FROM orders WHERE id=$1`, id).
                Scan(&uid, &status, &total, &lines, &comment)
        if err != nil {
                http.NotFound(w, r)
                return
        }
        s.render(w, r, "order.html", Page{Title: "Заказ", User: u, Data: map[string]any{
                "ID": id, "Status": status, "Total": formatRub(total), "Lines": lines, "Comment": comment,
                "Owner": uid == u.ID, "Cashier": u.IsCashier(),
        }})
}

func (s *Server) orderCancel(w http.ResponseWriter, r *http.Request, id int) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        var uid int
        var status string
        var total int64
        _ = s.db.QueryRow(`SELECT user_id, status, total_kop FROM orders WHERE id=$1`, id).Scan(&uid, &status, &total)
        if r.Method == http.MethodGet {
                if uid != u.ID {
                        s.flash(w, "Чужой заказ", false)
                        http.Redirect(w, r, "/shop", http.StatusFound)
                        return
                }
                s.render(w, r, "order_cancel.html", Page{Title: "Отмена заказа", User: u, Data: map[string]any{"ID": id, "Total": formatRub(total)}})
                return
        }
        if status == "paid" || status == "delivered" {
                _, _ = s.db.Exec(`UPDATE orders SET status='cancelled' WHERE id=$1`, id)
                _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, total, uid)
                _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('refund',4,$1,$2,$3,'ok')`,
                        uid, total, "Отмена заказа #"+strconv.Itoa(id))
        }
        s.flash(w, "Заказ отменён", true)
        http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
}

func (s *Server) orderReturn(w http.ResponseWriter, r *http.Request, id int) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        var uid int
        var status string
        var total int64
        _ = s.db.QueryRow(`SELECT user_id, status, total_kop FROM orders WHERE id=$1`, id).Scan(&uid, &status, &total)
        if uid != u.ID {
                s.flash(w, "Чужой заказ", false)
                http.Redirect(w, r, "/shop", http.StatusFound)
                return
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "order_return.html", Page{Title: "Возврат", User: u, Data: map[string]any{"ID": id, "Status": status}})
                return
        }
        qty, _ := strconv.Atoi(r.FormValue("qty"))
        refund := total
        if qty != 0 {
                refund = total * int64(qty)
        }
        if status == "delivered" || status == "paid" || status == "received" {
                _, _ = s.db.Exec(`UPDATE users SET balance_kop = balance_kop + $1 WHERE id=$2`, refund, u.ID)
                _, _ = s.db.Exec(`UPDATE orders SET status='returned' WHERE id=$1`, id)
                _, _ = s.db.Exec(`INSERT INTO operations (kind, from_user_id, to_user_id, amount_kop, memo, status) VALUES ('refund',4,$1,$2,$3,'ok')`,
                        u.ID, refund, "Возврат заказа #"+strconv.Itoa(id))
                if qty < 0 {
                        _, _ = s.db.Exec(`INSERT INTO anomaly_log (kind, detail) VALUES ('return_neg', $1)`,
                                fmt.Sprintf("order=%d qty=%d credit=%d", id, qty, refund))
                }
        }
        s.flash(w, "Возврат проведён", true)
        http.Redirect(w, r, "/orders/"+strconv.Itoa(id), http.StatusFound)
}

func (s *Server) orderReceived(w http.ResponseWriter, r *http.Request, id int) {
        u := s.requireUser(w, r)
        if u == nil {
                return
        }
        var uid int
        var status string
        _ = s.db.QueryRow(`SELECT user_id, status FROM orders WHERE id=$1`, id).Scan(&uid, &status)
        if uid != u.ID {
                http.Redirect(w, r, "/shop", http.StatusFound)
                return
        }
        if status == "paid" || status == "delivered" {
                _, _ = s.db.Exec(`UPDATE orders SET status='received' WHERE id=$1`, id)
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
        def := fmt.Sprintf("statement_u%d.csv", u.ID)
        path := filepath.Join(s.cfg.ExportsDir, def)
        if _, err := os.Stat(path); err != nil {
                _ = os.WriteFile(path, []byte("id,kind,amount\n1,topup,15000\n"), 0o644)
        }
        if r.Method == http.MethodGet {
                s.render(w, r, "statement.html", Page{Title: "Выписка", User: u, Data: map[string]any{"Filename": def}})
                return
        }
        name := r.FormValue("filename")
        if name == "" {
                name = def
        }
        if strings.HasPrefix(name, "/") || strings.Contains(name, "\\") {
                s.flash(w, "Некорректное имя файла", false)
                http.Redirect(w, r, "/statements/export", http.StatusFound)
                return
        }
        if strings.Contains(name, "..") {
                name = strings.Replace(name, "../", "", 1)
        }
        target := filepath.Join(s.cfg.ExportsDir, name)
        f, err := os.Open(target)
        if err != nil {
                s.flash(w, "Файл не найден", false)
                http.Redirect(w, r, "/statements/export", http.StatusFound)
                return
        }
        defer f.Close()
        w.Header().Set("Content-Type", "text/plain; charset=utf-8")
        w.Header().Set("Content-Disposition", "attachment; filename=statement.txt")
        buf := make([]byte, 8192)
        for {
                n, rerr := f.Read(buf)
                if n > 0 {
                        _, _ = w.Write(buf[:n])
                }
                if rerr != nil {
                        break
                }
        }
}
