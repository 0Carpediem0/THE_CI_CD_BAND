#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${TAG:-1.0.0}"
REGISTRY="${REGISTRY:-}"

APP_IMAGE="${REGISTRY:+$REGISTRY/}office-wallet-app:${TAG}"
MOCK_IMAGE="${REGISTRY:+$REGISTRY/}office-wallet-mock:${TAG}"

docker build -t "$APP_IMAGE" "$ROOT/app"
docker build -t "$MOCK_IMAGE" "$ROOT/mock"

echo "Built:"
echo "  $APP_IMAGE"
echo "  $MOCK_IMAGE"

if [[ "${LOAD_KIND:-0}" == "1" ]]; then
  kind load docker-image "$APP_IMAGE" ${KIND_CLUSTER:+--name "$KIND_CLUSTER"}
  kind load docker-image "$MOCK_IMAGE" ${KIND_CLUSTER:+--name "$KIND_CLUSTER"}
  echo "Loaded into kind"
fi
