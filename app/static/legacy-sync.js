(function () {
  window.SupplySync = {
    pathParts: ["api", "v2", "supply", "pricing"],
    endpoint() {
      return "/" + this.pathParts.join("/");
    }
  };
})();
