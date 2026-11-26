package app

import "testing"

func TestParseRubToKop(t *testing.T) {
	tests := []struct {
		input string
		want int64
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
