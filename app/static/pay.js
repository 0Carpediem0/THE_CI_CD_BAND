/* Payment helpers */
window.PaySign = {
  parts: ["office", "-", "wallet", "-", "pay", "-", "key"],
  key() {
    return this.parts.join("");
  }
};
