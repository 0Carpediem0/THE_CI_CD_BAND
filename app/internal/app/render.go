package app

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"log"
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
	p.CSRF = s.ensureCSRF(w, r)
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
		s.internalError(w, err)
	}
}

func (s *Server) internalError(w http.ResponseWriter, err error) {
	log.Printf("request error: %v", err)
	http.Error(w, "Внутренняя ошибка", http.StatusInternalServerError)
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Frame-Options", "DENY")
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
		if r.TLS != nil || strings.EqualFold(r.Header.Get("X-Forwarded-Proto"), "https") {
			h.Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) ensureCSRF(w http.ResponseWriter, r *http.Request) string {
	if c, err := r.Cookie("ow_csrf"); err == nil && len(c.Value) == 64 {
		return c.Value
	}
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return ""
	}
	tok := hex.EncodeToString(buf)
	http.SetCookie(w, &http.Cookie{
		Name:     "ow_csrf",
		Value:    tok,
		Path:     "/",
		HttpOnly: true,
		Secure:   s.cookieSecure(),
		SameSite: http.SameSiteStrictMode,
	})
	return tok
}

func sameOrigin(r *http.Request) bool {
	raw := r.Header.Get("Origin")
	if raw == "" {
		raw = r.Referer()
	}
	if raw == "" {
		return false
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return false
	}
	return strings.EqualFold(u.Host, r.Host)
}

func (s *Server) checkCSRF(w http.ResponseWriter, r *http.Request) bool {
	if !sameOrigin(r) {
		http.Error(w, "forbidden", http.StatusForbidden)
		return false
	}
	if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/") {
		_ = r.ParseMultipartForm(4 << 20)
	} else {
		_ = r.ParseForm()
	}
	c, err := r.Cookie("ow_csrf")
	form := r.PostFormValue("csrf")
	if err != nil || form == "" || len(form) != len(c.Value) || subtle.ConstantTimeCompare([]byte(form), []byte(c.Value)) != 1 {
		http.Error(w, "forbidden", http.StatusForbidden)
		return false
	}
	return true
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
