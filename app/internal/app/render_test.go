package app

import "testing"

func TestParseRubToKop(t *testing.T) {
	tests := []struct {
		input   string
		want    int64
		invalid bool
	}{
		{"125", 12500, false},
		{" 12,5 ", 1250, false},
		{"-0.01", -1, false},
		{"+0.01", 1, false},
		{"92233720368547758.07", 9223372036854775807, false},
		{"-92233720368547758.08", -9223372036854775808, false},
		{"92233720368547758.08", 0, true},
		{"-92233720368547758.09", 0, true},
		{"92233720368547759", 0, true},
		{"1.234", 0, true},
		{"1.", 0, true},
		{"1.-2", 0, true},
		{"", 0, true},
	}
	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got, err := parseRubToKop(tt.input)
			if (err != nil) != tt.invalid || got != tt.want && !tt.invalid {
				t.Fatalf("parseRubToKop(%q) = %d, %v; want %d, invalid=%t", tt.input, got, err, tt.want, tt.invalid)
			}
		})
	}
}

func TestLineRefundKop(t *testing.T) {
	lines := `[{"product_id":1,"title":"Кофе","qty":1,"price_kop":45000}]`
	got, err := lineRefundKop(lines, 1)
	if err != nil || got != 45000 {
		t.Fatalf("lineRefundKop qty 1 = %d, %v", got, err)
	}
	if _, err := lineRefundKop(lines, 100); err == nil {
		t.Fatal("qty above purchased units")
	}
	if _, err := lineRefundKop(lines, 0); err == nil {
		t.Fatal("qty 0")
	}
	two := `[{"product_id":1,"qty":2,"price_kop":1000},{"product_id":2,"qty":1,"price_kop":500}]`
	got, err = lineRefundKop(two, 3)
	if err != nil || got != 2500 {
		t.Fatalf("lineRefundKop qty 3 = %d, %v", got, err)
	}
}

func TestClientIP(t *testing.T) {
	if got := clientIP("203.0.113.8:51514"); got != "203.0.113.8" {
		t.Fatalf("clientIP = %q", got)
	}
	if got := clientIP("[2001:db8::1]:443"); got != "2001:db8::1" {
		t.Fatalf("clientIP = %q", got)
	}
}
