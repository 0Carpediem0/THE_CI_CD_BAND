FROM golang:1.24-bookworm AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download 2>/dev/null || true
COPY . .
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /out/wallet ./cmd/wallet

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=build /out/wallet /app/wallet
COPY templates /app/templates
COPY static /app/static
USER nonroot
ENV ADDR=:8080
EXPOSE 8080
CMD ["/app/wallet"]
