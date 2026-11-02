/* Behavior for grouped menus in the navigation bar. Built on <details>/<summary>, so opening, keyboard support, and `aria-expanded` come from the browser and work even if this file fails to load. This file adds only what the browser lacks: closing on outside click and on Escape. Loaded from the navigation fragment, so no inline script is needed (`script-src 'self'`). */
(function () {
  "use strict";

  function semuaMenu() {
    return document.querySelectorAll(".nav details.menu-nav");
  }

  function tutupSemua(kecuali) {
    Array.prototype.forEach.call(semuaMenu(), function (m) {
      if (m !== kecuali) m.open = false;
    });
  }

  /* Opening one menu closes the others. */
  Array.prototype.forEach.call(semuaMenu(), function (m) {
    m.addEventListener("toggle", function () {
      if (m.open) tutupSemua(m);
    });
  });

  document.addEventListener("click", function (e) {
    // Clicks inside a menu do not close it, so links inside can work.
    if (e.target.closest && e.target.closest(".nav details.menu-nav")) return;
    tutupSemua(null);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var adaYangTerbuka = false;
    Array.prototype.forEach.call(semuaMenu(), function (m) {
      if (m.open) adaYangTerbuka = true;
    });
    if (!adaYangTerbuka) return;
    tutupSemua(null);
    // Focus returns to the menu title so keyboard users do not lose their position after Escape.
    var judul = document.querySelector(".nav details.menu-nav > summary");
    if (judul) judul.focus();
  });
})();
