FROM golang:1.22-bookworm AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download 2>/dev/null || true
COPY . .
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /out/wallet ./cmd/wallet

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /out/wallet /app/wallet
COPY templates /app/templates
COPY static /app/static
COPY labdata /var/www/labdata
RUN mkdir -p /app/exports && chmod 755 /app /app/exports
ENV ADDR=:8080
EXPOSE 8080
CMD ["/app/wallet"]
