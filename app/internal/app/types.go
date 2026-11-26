package app

import "html/template"

type Config struct {
        Addr         string
        DatabaseURL  string
        MailHost     string
        MailPort     string
        MailUI       string
        MockHost     string
        SessionKey   string
        PaymentKey   string
        PublicBase   string
        ExportsDir   string
        TemplatesDir string
        StaticDir    string
}

type User struct {
        ID                int
        Login             string
        PasswordHash      string
        DisplayName       string
        Email             string
        Phone             string
        Role              string
        AccountNo         string
        BalanceKop        int64
        OverdraftLimitKop int64
        Blocked           bool
}

type Page struct {
        Title   string
        User    *User
        Flash   string
        FlashOK bool
        MailUI  string
        Data    map[string]any
        QRaw    template.HTML
        TipHTML template.HTML
        Preview template.HTML
}

func (u *User) IsCashier() bool    { return u != nil && (u.Role == "cashier" || u.Role == "admin") }
func (u *User) IsAccountant() bool { return u != nil && (u.Role == "accountant" || u.Role == "admin") }
func (u *User) IsAdmin() bool      { return u != nil && u.Role == "admin" }
func (u *User) RoleLabel() string {
        if u == nil {
                return ""
        }
        switch u.Role {
        case "employee":
                return "Сотрудник"
        case "cashier":
                return "Кассир"
        case "accountant":
                return "Бухгалтер"
        case "admin":
                return "Администратор"
        default:
                return u.Role
        }
}
func (u *User) BalanceRub() string { return formatRub(u.BalanceKop) }

func formatRub(kop int64) string {
        sign := ""
        if kop < 0 {
                sign = "-"
                kop = -kop
        }
        return sign + itoa(kop/100) + "," + pad2(kop%100) + " ₽"
}

func pad2(n int64) string {
        if n < 10 {
                return "0" + itoa(n)
        }
        return itoa(n)
}

func itoa(n int64) string {
        if n == 0 {
                return "0"
        }
        var b [32]byte
        i := len(b)
        neg := n < 0
        if neg {
                n = -n
        }
        for n > 0 {
                i--
                b[i] = byte('0' + n%10)
                n /= 10
        }
        if neg {
                i--
                b[i] = '-'
        }
        return string(b[i:])
}
