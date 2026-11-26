package app

import (
        "crypto/hmac"
        "crypto/sha256"
        "database/sql"
        "encoding/hex"
        "net/http"
        "strconv"
        "strings"

        "golang.org/x/crypto/bcrypt"
)

const sessionCookie = "ow_session"

func (s *Server) currentUser(r *http.Request) *User {
        c, err := r.Cookie(sessionCookie)
        if err != nil || c.Value == "" {
                return nil
        }
        parts := strings.Split(c.Value, ".")
        if len(parts) != 4 || parts[0] != "ow" {
                return nil
        }
        uid, err := strconv.Atoi(parts[1])
        if err != nil {
                return nil
        }
        role := parts[2]
        sig := parts[3]
        expect := s.signSession(uid, role)
        if !hmac.Equal([]byte(sig), []byte(expect)) {
                return nil
        }
        u, err := s.getUserByID(uid)
        if err != nil || u == nil {
                return nil
        }
        if role != "" {
                u.Role = role
        }
        return u
}

func (s *Server) signSession(uid int, role string) string {
        mac := hmac.New(sha256.New, []byte(s.cfg.SessionKey))
        mac.Write([]byte(strconv.Itoa(uid) + ":" + role))
        return hex.EncodeToString(mac.Sum(nil))
}

func (s *Server) setSession(w http.ResponseWriter, u *User) {
        sig := s.signSession(u.ID, u.Role)
        val := "ow." + strconv.Itoa(u.ID) + "." + u.Role + "." + sig
        http.SetCookie(w, &http.Cookie{
                Name:     sessionCookie,
                Value:    val,
                Path:     "/",
                HttpOnly: false,
                SameSite: http.SameSiteLaxMode,
        })
}

func (s *Server) clearSession(w http.ResponseWriter) {
        http.SetCookie(w, &http.Cookie{Name: sessionCookie, Value: "", Path: "/", MaxAge: -1})
}

func (s *Server) requireUser(w http.ResponseWriter, r *http.Request) *User {
        u := s.currentUser(r)
        if u == nil {
                http.Redirect(w, r, "/login?return="+r.URL.RequestURI(), http.StatusFound)
                return nil
        }
        return u
}

func (s *Server) getUserByID(id int) (*User, error) {
        row := s.db.QueryRow(`SELECT id, login, password_hash, display_name, email, COALESCE(phone,''), role, account_no, balance_kop, overdraft_limit_kop, blocked FROM users WHERE id=$1`, id)
        return scanUser(row)
}

func (s *Server) getUserByLogin(login string) (*User, error) {
        row := s.db.QueryRow(`SELECT id, login, password_hash, display_name, email, COALESCE(phone,''), role, account_no, balance_kop, overdraft_limit_kop, blocked FROM users WHERE login=$1`, login)
        return scanUser(row)
}

func scanUser(row *sql.Row) (*User, error) {
        var u User
        err := row.Scan(&u.ID, &u.Login, &u.PasswordHash, &u.DisplayName, &u.Email, &u.Phone, &u.Role, &u.AccountNo, &u.BalanceKop, &u.OverdraftLimitKop, &u.Blocked)
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

func (s *Server) signPayment(opID int, amount int64, recipient string) string {
        mac := hmac.New(sha256.New, []byte(s.cfg.PaymentKey))
        mac.Write([]byte(strconv.Itoa(opID) + ":" + strconv.FormatInt(amount, 10) + ":" + recipient))
        return hex.EncodeToString(mac.Sum(nil))
}

func (s *Server) signOpGrant(viewerID, opID int) string {
        mac := hmac.New(sha256.New, []byte(s.cfg.SessionKey))
        mac.Write([]byte("opgrant:" + strconv.Itoa(viewerID) + ":" + strconv.Itoa(opID)))
        return hex.EncodeToString(mac.Sum(nil))[:32]
}

func (s *Server) supplyChannel() string {
        mac := hmac.New(sha256.New, []byte(s.cfg.SessionKey))
        mac.Write([]byte("supply-channel-v2"))
        return hex.EncodeToString(mac.Sum(nil))[:20]
}
