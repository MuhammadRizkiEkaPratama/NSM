/* Light/dark theme switch. Loaded in <head> and kept very small so it may block rendering: loading it later would flash dark before a light theme applies. Dark is the default rather than following the system setting, so only a consciously chosen theme can be affected if a color was missed in the token mapping. */
(function () {
  "use strict";

  var KUNCI = "nsm-tema";

  function pasang(nilai) {
    if (nilai === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  var tersimpan;
  try {
    tersimpan = localStorage.getItem(KUNCI);
  } catch (e) {
    /* Private mode or full storage: keep the default theme; the switch still works for this page. */
    tersimpan = null;
  }
  pasang(tersimpan);

  window.NSMTema = {
    baca: function () { return tersimpan === "light" ? "light" : "dark"; },

    /* Saves the choice and reloads instead of swapping variables live: the browser updates variable values but does not recompute colors that use them (measured: `.nav a` kept its old color), producing a half-switched page. `tema.js` sets the theme in <head> before first paint, which is known to be correct. */
    pilih: function (nilai) {
      tersimpan = nilai;
      try {
        localStorage.setItem(KUNCI, nilai);
      } catch (e) {
        /* Storage unavailable: the theme cannot be remembered, so reloading would restore the old one. Swap in place instead, even if imperfect. */
        pasang(nilai);
        document.dispatchEvent(new CustomEvent("nsm:tema", { detail: { tema: nilai } }));
        return;
      }
      location.reload();
    }
  };

  /* Wired after the DOM is ready; this file loads in <head>, so the element does not exist yet. */
  function pasangSaklar() {
    var wadah = document.querySelectorAll("[data-saklar-tema]");
    if (!wadah.length) return;
    Array.prototype.forEach.call(wadah, function (w) {
      w.innerHTML =
        '<button type="button" class="tema-tbl" data-tema="dark">Gelap</button>' +
        '<button type="button" class="tema-tbl" data-tema="light">Terang</button>';
      Array.prototype.forEach.call(w.querySelectorAll("[data-tema]"), function (b) {
        b.addEventListener("click", function () {
          window.NSMTema.pilih(b.dataset.tema);
          tandai();
        });
      });
    });
    tandai();
  }

  function tandai() {
    var kini = window.NSMTema.baca();
    Array.prototype.forEach.call(document.querySelectorAll(".tema-tbl"), function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.tema === kini));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pasangSaklar);
  } else {
    pasangSaklar();
  }
})();
