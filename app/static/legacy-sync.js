/* Legacy supply sync helpers */
(function () {
  window.SupplySync = {
    pathParts: ["api", "v2", "supply", "pricing"],
    endpoint() {
      return "/" + this.pathParts.join("/");
    },
    async resolveChannel() {
      const r = await fetch("/api/catalog", { credentials: "same-origin" });
      const part = r.headers.get("X-Wallet-Sync-Part") || "";
      const body = await r.json();
      const pref = (body && body.meta && body.meta.ch_pref) || "";
      return String(pref) + String(part);
    }
  };
  window.__SK_TAIL__ = ["-", "session", "-", "key"].join("");
})();
