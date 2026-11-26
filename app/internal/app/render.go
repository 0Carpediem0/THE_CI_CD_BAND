package app

import (
        "net"
        "net/http"
        "net/smtp"
        "net/url"
        "strconv"
        "strings"
)

func (s *Server) render(w http.ResponseWriter, r *http.Request, name string, p Page) {
        if p.Data == nil {
                p.Data = map[string]any{}
        }
        p.MailUI = s.cfg.MailUI
        if p.User == nil {
                p.User = s.currentUser(r)
        }
        if c, err := r.Cookie("flash"); err == nil && c.Value != "" {
                if decoded, err := url.QueryUnescape(c.Value); err == nil {
                        p.Flash = decoded
                } else {
                        p.Flash = c.Value
                }
                http.SetCookie(w, &http.Cookie{Name: "flash", Value: "", Path: "/", MaxAge: -1})
        }
        if c, err := r.Cookie("flash_ok"); err == nil && c.Value == "1" {
                p.FlashOK = true
                http.SetCookie(w, &http.Cookie{Name: "flash_ok", Value: "", Path: "/", MaxAge: -1})
        }
        w.Header().Set("Content-Type", "text/html; charset=utf-8")
        if err := s.tmpl.ExecuteTemplate(w, name, p); err != nil {
                http.Error(w, err.Error(), 500)
        }
}

func (s *Server) flash(w http.ResponseWriter, msg string, ok bool) {
        http.SetCookie(w, &http.Cookie{Name: "flash", Value: url.QueryEscape(msg), Path: "/"})
        if ok {
                http.SetCookie(w, &http.Cookie{Name: "flash_ok", Value: "1", Path: "/"})
        }
}

func (s *Server) mailSend(to, subject, body string) {
        _, _ = s.db.Exec(`INSERT INTO mail_outbox (recipient, subject, body) VALUES ($1,$2,$3)`, to, subject, body)
        addr := net.JoinHostPort(s.cfg.MailHost, s.cfg.MailPort)
        msg := []byte("To: " + to + "\r\nSubject: " + subject + "\r\n\r\n" + body)
        _ = smtp.SendMail(addr, nil, "wallet@office.local", []string{to}, msg)
}

func parseRubToKop(s string) (int64, error) {
        s = strings.ReplaceAll(strings.TrimSpace(s), ",", ".")
        sign := ""
        if strings.HasPrefix(s, "-") || strings.HasPrefix(s, "+") {
                sign, s = s[:1], s[1:]
        }
        rubles, fraction, hasFraction := strings.Cut(s, ".")
        if rubles == "" || (hasFraction && (len(fraction) == 0 || len(fraction) > 2)) {
                return 0, strconv.ErrSyntax
        }
        digits := rubles + fraction
        for _, digit := range digits {
                if digit < '0' || digit > '9' {
                        return 0, strconv.ErrSyntax
                }
        }
        cents := digits + strings.Repeat("0", 2-len(fraction))
        return strconv.ParseInt(sign+cents, 10, 64)
}
