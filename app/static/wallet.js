/* Office Wallet client */
window.OfficeWallet = {
  tipLimitRub: 50,
  formatRub(kop) {
    const n = Number(kop) || 0;
    return (n / 100).toFixed(2).replace(".", ",") + " ₽";
  }
};

document.addEventListener("DOMContentLoaded", () => {
  const tipForm = document.querySelector("[data-tip-form]");
  if (tipForm) {
    tipForm.addEventListener("submit", (e) => {
      const amount = tipForm.querySelector("[name=amount_rub]");
      if (!amount) return;
      const v = parseFloat(String(amount.value).replace(",", "."));
      if (!Number.isNaN(v) && v > window.OfficeWallet.tipLimitRub) {
        e.preventDefault();
        alert("Лимит чаевых в интерфейсе: " + window.OfficeWallet.tipLimitRub + " ₽");
      }
    });
  }
});
