package main

import (
        "log"
        "os"

        "officewallet/internal/app"
)

func main() {
        addr := env("ADDR", ":8080")
	dsn := env("DATABASE_URL", "postgres://wallet:wallet@db:5432/wallet?sslmode=disable")
	s, err := app.New(app.Config{
		Addr:         addr,
		DatabaseURL:  dsn,
		MailHost:     env("MAIL_HOST", "mail"),
		MailPort:     env("MAIL_PORT", "1025"),
		MailUI:       env("MAIL_UI", "http://localhost:18025"),
		MockHost:     env("INTERNAL_NOTIFY_HOST", "notify-mock"),

                SessionKey:   os.Getenv("SESSION_KEY"),
                PaymentKey:   os.Getenv("PAYMENT_KEY"),
                PublicBase:   env("PUBLIC_BASE", "http://localhost:18081"),
                ExportsDir:   env("EXPORTS_DIR", "/app/exports"),
                TemplatesDir: env("TEMPLATES_DIR", "templates"),
                StaticDir:    env("STATIC_DIR", "static"),
        })
        if err != nil {
                log.Fatal(err)
        }
        log.Println("Office Wallet listening on", addr)
        log.Fatal(s.ListenAndServe())
}

func env(k, def string) string {
        if v := os.Getenv(k); v != "" {
                return v
        }
        return def
}
