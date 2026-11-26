#!/bin/sh
set -eu

# This file is sourced by deploy job AFTER kubeconfig and optional RECREATE cleanup.
# Existing chart-owned Secret is the source of truth on regular upgrades.
# On fresh install / RECREATE, generate independent app credentials.
# WARNING: credentials are printed in GitLab job logs as requested for the dev contest.
SECRET_NAME=office-wallet-db

# Check existence once: a Forbidden error must NOT silently rotate database credentials.
secret_error=$(mktemp)
if kubectl -n "$K8S_NAMESPACE" get secret "$SECRET_NAME" -o name > /dev/null 2> "$secret_error"; then
  SECRET_EXISTS=true
elif grep -Eiq 'notfound|not found' "$secret_error"; then
  SECRET_EXISTS=false
else
  cat "$secret_error" >&2
  rm -f "$secret_error"
  echo "Cannot inspect application Secret; refusing to rotate credentials" >&2
  exit 1
fi
rm -f "$secret_error"

get_existing() {
  key="$1"
  if [ "$SECRET_EXISTS" = false ]; then
    return 0
  fi
  # Go template returns <no value> when a key is missing.
  encoded=$(kubectl -n "$K8S_NAMESPACE" get secret "$SECRET_NAME" -o "go-template={{index .data \"$key\"}}")
  if [ -n "$encoded" ] && [ "$encoded" != "<no value>" ]; then
    printf '%s' "$encoded" | base64 -d
  fi
}

new_password() {
  # Base64-derived alphabet avoids Helm --set escaping and URL-encoding problems.
  openssl rand -hex 24
}

echo "=== Application credentials (development only; GitLab job log is visible to authorized users) ==="
if [ -z "${DB_PASSWORD:-}" ]; then
  DB_PASSWORD=$(get_existing 'POSTGRES_PASSWORD')
fi
if [ -z "${DB_PASSWORD:-}" ]; then
  DB_PASSWORD=$(new_password)
fi
export DB_PASSWORD
printf "%s=%s\n" "DB_PASSWORD" "$DB_PASSWORD"

if [ -z "${APP_SESSION_KEY:-}" ]; then
  APP_SESSION_KEY=$(get_existing 'SESSION_KEY')
fi
if [ -z "${APP_SESSION_KEY:-}" ]; then
  APP_SESSION_KEY=$(new_password)
fi
export APP_SESSION_KEY
printf "%s=%s\n" "APP_SESSION_KEY" "$APP_SESSION_KEY"

if [ -z "${APP_PAYMENT_KEY:-}" ]; then
  APP_PAYMENT_KEY=$(get_existing 'PAYMENT_KEY')
fi
if [ -z "${APP_PAYMENT_KEY:-}" ]; then
  APP_PAYMENT_KEY=$(new_password)
fi
export APP_PAYMENT_KEY
printf "%s=%s\n" "APP_PAYMENT_KEY" "$APP_PAYMENT_KEY"

echo "=== End of application credentials ==="
