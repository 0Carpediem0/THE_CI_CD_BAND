#!/bin/sh
set -eu

# RECREATE=true is explicitly destructive: database state and application files
# stored in these PVCs are permanently lost when local-path PVs are deleted.
if [ "${RECREATE:-false}" != "true" ]; then
  echo "RECREATE is not true; preserving Helm release and PVCs."
  exit 0
fi

: "${K8S_NAMESPACE:?K8S_NAMESPACE is required}"
# A namespace-scoped credential is still authoritative; never create/delete ns.
case "$K8S_NAMESPACE" in
  team-[0-9]*-app) ;;
  *) echo "Invalid K8S_NAMESPACE: $K8S_NAMESPACE" >&2; exit 1 ;;
esac

RELEASE=office-wallet
echo "RECREATE=true: removing Helm release $RELEASE in $K8S_NAMESPACE"
helm uninstall "$RELEASE" --namespace "$K8S_NAMESPACE" --ignore-not-found --wait --timeout 10m

# Helm removes chart-owned PVCs but does NOT remove PVCs made by
# StatefulSet volumeClaimTemplates, hence the explicit, per-chart allowlist.
# Do not remove registry-creds, contest-tls, or any foreign PVCs.
for pvc in office-wallet-office-wallet-postgres office-wallet-office-wallet-exports; do
  echo "Deleting known PVC: $pvc"
  kubectl -n "$K8S_NAMESPACE" delete pvc "$pvc" --ignore-not-found=true --wait=true --timeout=5m
done

echo "Old release and application PVCs removed; fresh installation follows."
