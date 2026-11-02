/* Theme switch for the static preview pages only. They do not load `fragmen/nav`, so the real switch in the account menu is missing. Never loaded by real NSM pages. */
(function () {
  "use strict";
  var tombol = Array.prototype.slice.call(
    document.querySelectorAll("[data-p-tema]"));
  if (!tombol.length) return;

  tombol.forEach(function (b) {
    b.addEventListener("click", function () {
      var v = b.dataset.pTema;
      if (window.NSMTema) {
        window.NSMTema.pilih(v);
      } else if (v === "light") {
        document.documentElement.setAttribute("data-theme", "light");
      } else {
        document.documentElement.removeAttribute("data-theme");
      }
      tombol.forEach(function (x) {
        x.setAttribute("aria-pressed", String(x.dataset.pTema === v));
      });
    });
  });
})();
