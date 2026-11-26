package app

import (
        "database/sql"
        "html/template"
        "log"
        "net/http"
        "os"
        "path/filepath"
        "strings"
        "sync"
        "time"

        _ "github.com/lib/pq"
)

type Server struct {
        cfg  Config
        db   *sql.DB
        tmpl *template.Template
        mu   sync.Mutex
}

func New(cfg Config) (*Server, error) {
        db, err := sql.Open("postgres", cfg.DatabaseURL)
        if err != nil {
                return nil, err
        }
        db.SetMaxOpenConns(20)
        db.SetMaxIdleConns(10)
        var pingErr error
        for i := 0; i < 40; i++ {
                pingErr = db.Ping()
                if pingErr == nil {
                        break
                }
                log.Println("waiting for db:", pingErr)
                time.Sleep(500 * time.Millisecond)
        }
        if pingErr != nil {
                _ = db.Close()
                return nil, pingErr
        }
        _ = os.MkdirAll(cfg.ExportsDir, 0o755)
        s := &Server{cfg: cfg, db: db}
        if err := s.loadTemplates(); err != nil {
                _ = db.Close()
                return nil, err
        }
        return s, nil
}

func (s *Server) loadTemplates() error {
        pattern := filepath.Join(s.cfg.TemplatesDir, "*.html")
        t, err := template.New("root").Funcs(template.FuncMap{
                "rub": formatRub,
        }).ParseGlob(pattern)
        if err != nil {
                return err
        }
        s.tmpl = t
        return nil
}

func (s *Server) ListenAndServe() error {
        mux := http.NewServeMux()
        mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.Dir(s.cfg.StaticDir))))
        mux.HandleFunc("/", s.route)
        server := &http.Server{
                Addr:              s.cfg.Addr,
                Handler:           mux,
                ReadHeaderTimeout: 5 * time.Second,
                ReadTimeout:       15 * time.Second,
                WriteTimeout:      30 * time.Second,
                IdleTimeout:       60 * time.Second,
        }
        return server.ListenAndServe()
}

func (s *Server) route(w http.ResponseWriter, r *http.Request) {
        path := r.URL.Path
        switch {
        case path == "/" && r.Method == http.MethodGet:
                s.home(w, r)
        case path == "/login":
                s.login(w, r)
        case path == "/logout":
                s.logout(w, r)
        case path == "/register":
                s.register(w, r)
        case path == "/password/forgot":
                s.passwordForgot(w, r)
        case path == "/password/reset":
                s.passwordReset(w, r)
        case path == "/history":
                s.history(w, r)
        case strings.HasPrefix(path, "/operations/"):
                s.operation(w, r)
        case path == "/transfer/new":
                s.transferNew(w, r)
        case path == "/transfer/confirm":
                s.transferConfirm(w, r)
        case path == "/tips/new":
                s.tipsNew(w, r)
        case path == "/tips/received":
                s.tipsReceived(w, r)
        case path == "/api/recipients":
                s.apiRecipients(w, r)
        case path == "/shop":
                s.shop(w, r)
        case path == "/api/catalog":
                s.apiCatalog(w, r)
        case path == "/api/v2/supply/pricing":
                s.apiSupplyPricing(w, r)
        case path == "/api/ops/feed":
                s.apiOpsFeed(w, r)
        case path == "/cart":
                s.cart(w, r)
        case path == "/cart/add":
                s.cartAdd(w, r)
        case path == "/checkout":
                s.checkout(w, r)
        case path == "/checkout/quote":
                s.checkoutQuote(w, r)
        case path == "/checkout/confirm":
                s.checkoutConfirm(w, r)
        case path == "/gateway/sms":
                s.smsGateway(w, r)
        case strings.HasPrefix(path, "/orders/"):
                s.ordersRouter(w, r)
        case path == "/statements/export":
                s.statementExport(w, r)
        case path == "/profile":
                s.profile(w, r)
        case path == "/settings/notify":
                s.notifySettings(w, r)
        case path == "/mail":
                s.mailBox(w, r)
        case path == "/ops/journal":
                s.opsJournal(w, r)
        case path == "/cashier/topup":
                s.cashierTopup(w, r)
        case strings.HasPrefix(path, "/cashier/fulfill/"):
                s.cashierFulfill(w, r)
        case path == "/accounting/reconcile":
                s.accountingReconcile(w, r)
        case path == "/accounting/block":
                s.accountingBlock(w, r)
        case path == "/accounting/adjust":
                s.accountingAdjust(w, r)
        case path == "/admin/secrets":
                s.adminSecrets(w, r)
        case path == "/pay/replay":
                s.payReplay(w, r)
        default:
                http.NotFound(w, r)
        }
}
