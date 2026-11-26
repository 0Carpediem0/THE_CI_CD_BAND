package app

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"golang.org/x/crypto/bcrypt"
)

const sessionCookie = "ow_session"

var dummyPasswordHash string

func init() {
	b, err := bcrypt.GenerateFromPassword([]byte("office-wallet-timing"), bcrypt.DefaultCost)
	if err != nil {
		panic(err)
	}
	dummyPasswordHash = string(b)
}

const sessionTTL = 12 * time.Hour

func (s *Server) currentUser(r *http.Request) *User {
	c, err := r.Cookie(sessionCookie)
	if err != nil || c.Value == "" {
		return nil
	}
	parts := strings.Split(c.Value, ".")
	if len(parts) != 5 || parts[0] != "ow" {
		return nil
	}
	uid, err := strconv.Atoi(parts[1])
	if err != nil {
		return nil
	}
	ver, err := strconv.Atoi(parts[2])
	if err != nil {
		return nil
	}
	exp, err := strconv.ParseInt(parts[3], 10, 64)
	if err != nil || time.Now().Unix() > exp {
		return nil
	}
	sig := parts[4]
	expect := s.signSession(uid, ver, exp)
	if subtle.ConstantTimeCompare([]byte(sig), []byte(expect)) != 1 {
		return nil
	}
	u, err := s.getUserByID(uid)
	if err != nil || u == nil || u.SessionVersion != ver {
		return nil
	}
	return u
}

func (s *Server) signSession(uid, ver int, exp int64) string {
	mac := hmac.New(sha256.New, []byte(s.cfg.SessionKey))
	mac.Write([]byte(strconv.Itoa(uid) + ":" + strconv.Itoa(ver) + ":" + strconv.FormatInt(exp, 10)))
	return hex.EncodeToString(mac.Sum(nil))
}

func (s *Server) cookieSecure() bool {
	return strings.HasPrefix(strings.ToLower(s.cfg.PublicBase), "https://")
}

func (s *Server) setSession(w http.ResponseWriter, u *User) {
	exp := time.Now().Add(sessionTTL).Unix()
	sig := s.signSession(u.ID, u.SessionVersion, exp)
	val := "ow." + strconv.Itoa(u.ID) + "." + strconv.Itoa(u.SessionVersion) + "." + strconv.FormatInt(exp, 10) + "." + sig
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    val,
		Path:     "/",
		HttpOnly: true,
		Secure:   s.cookieSecure(),
		SameSite: http.SameSiteStrictMode,
	})
}

func (s *Server) clearSession(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		HttpOnly: true,
		Secure:   s.cookieSecure(),
		SameSite: http.SameSiteStrictMode,
	})
}

func (s *Server) bumpSession(id int) {
	_, _ = s.db.Exec(`UPDATE users SET session_version = session_version + 1 WHERE id=$1`, id)
}

func (s *Server) requireUser(w http.ResponseWriter, r *http.Request) *User {
	u := s.currentUser(r)
	if u == nil || u.Blocked {
		if u != nil && u.Blocked {
			s.clearSession(w)
		}
		http.Redirect(w, r, "/login?return="+r.URL.RequestURI(), http.StatusFound)
		return nil
	}
	return u
}

func (s *Server) getUserByID(id int) (*User, error) {
	row := s.db.QueryRow(`SELECT id, login, password_hash, display_name, email, COALESCE(phone,''), role, account_no, balance_kop, overdraft_limit_kop, blocked, session_version FROM users WHERE id=$1`, id)
	return scanUser(row)
}

func (s *Server) getUserByLogin(login string) (*User, error) {
	row := s.db.QueryRow(`SELECT id, login, password_hash, display_name, email, COALESCE(phone,''), role, account_no, balance_kop, overdraft_limit_kop, blocked, session_version FROM users WHERE login=$1`, login)
	return scanUser(row)
}

func scanUser(row *sql.Row) (*User, error) {
	var u User
	err := row.Scan(&u.ID, &u.Login, &u.PasswordHash, &u.DisplayName, &u.Email, &u.Phone, &u.Role, &u.AccountNo, &u.BalanceKop, &u.OverdraftLimitKop, &u.Blocked, &u.SessionVersion)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &u, nil
}

func checkPassword(hash, plain string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(plain)) == nil
}

func hashPassword(plain string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(plain), bcrypt.DefaultCost)
	return string(b), err
}

func clientIP(remoteAddr string) string {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil || host == "" {
		return remoteAddr
	}
	return host
}

func (s *Server) loginKey(login, ip string) string {
	return login + "\n" + ip
}

func (s *Server) loginLocked(login, ip string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	a := s.attempts[s.loginKey(login, ip)]
	return a != nil && time.Now().Before(a.until)
}

func (s *Server) loginFail(login, ip string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := s.loginKey(login, ip)
	a := s.attempts[key]
	if a == nil {
		a = &loginAttempt{}
		s.attempts[key] = a
	}
	if time.Now().Before(a.until) {
		return
	}
	a.n++
	if a.n >= 5 {
		a.until = time.Now().Add(15 * time.Minute)
		a.n = 0
	}
}

func (s *Server) loginSuccess(login, ip string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.attempts, s.loginKey(login, ip))
}

func (s *Server) supplyChannel() string {
	mac := hmac.New(sha256.New, []byte(s.cfg.SessionKey))
	mac.Write([]byte("supply-channel-v2"))
	return hex.EncodeToString(mac.Sum(nil))[:20]
}
