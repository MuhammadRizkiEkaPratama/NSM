/*
 * NSM tooltips, replacing the browser default (about 1 s delay, differs per OS, cannot be styled). Tooltips are for additional information only; a button's main purpose must be clear without it, since touch screens never show tooltips.
 *
 * Usage: add `data-petunjuk` to any element.
 *   <button data-petunjuk="Menjeda pemantauan device ini">...</button>
 * `title` is also recognized and moved automatically so it does not show twice. Also shown on keyboard focus.
 */
(function () {
  var kotak = null;
  var sasaran = null;
  var jedaTampil = null;

  function buatKotak() {
    if (kotak) return kotak;
    kotak = document.createElement("div");
    kotak.className = "petunjuk";
    kotak.setAttribute("role", "tooltip");
    document.body.appendChild(kotak);
    return kotak;
  }

  function ambilTeks(el) {
    var t = el.getAttribute("data-petunjuk");
    if (t) return t;
    // Move title to data-petunjuk once; otherwise the native tooltip stacks on top.
    var judul = el.getAttribute("title");
    if (judul) {
      el.setAttribute("data-petunjuk", judul);
      el.removeAttribute("title");
      return judul;
    }
    return null;
  }

  function tempatkan(el) {
    var r = el.getBoundingClientRect();
    var k = kotak.getBoundingClientRect();
    var jarak = 8;

    var kiri = r.left + r.width / 2 - k.width / 2;
    var atas = r.top - k.height - jarak;
    kotak.classList.remove("bawah");

    if (atas < 6) {
      atas = r.bottom + jarak;
      kotak.classList.add("bawah");
    }

    /* A tooltip must not cover what it explains. When it would overlap the card containing its source element, it moves below the card (summary-card sub-labels sit under the big number, and a tooltip above would hide it). Applies to cards only, and to `.gerbang` cards on the Configuration home page. */
    var kartu = el.closest ? el.closest(".kartu, .kartu-mini, .gerbang") : null;
    if (kartu && !kotak.classList.contains("bawah")) {
      var rk = kartu.getBoundingClientRect();
      if (atas < rk.bottom && atas + k.height > rk.top) {
        atas = rk.bottom + jarak;
        kotak.classList.add("bawah");
      }
    }
    kiri = Math.max(8, Math.min(kiri, window.innerWidth - k.width - 8));

    kotak.style.left = Math.round(kiri) + "px";
    kotak.style.top = Math.round(atas) + "px";
  }

  function tampilkan(el) {
    var teks = ambilTeks(el);
    if (!teks) return;
    sasaran = el;
    buatKotak();
    kotak.textContent = teks;
    kotak.classList.add("siap");
    tempatkan(el);
    kotak.classList.add("terlihat");
  }

  function sembunyikan() {
    sasaran = null;
    clearTimeout(jedaTampil);
    if (kotak) kotak.classList.remove("terlihat", "siap");
  }

  function cariSasaran(e) {
    var el = e.target.closest ? e.target.closest("[data-petunjuk],[title]") : null;
    if (el && (el.getAttribute("data-petunjuk") || el.getAttribute("title"))) return el;
    return null;
  }

  document.addEventListener("pointerover", function (e) {
    var el = cariSasaran(e);

    // Pointer moved somewhere without a hint: close now, otherwise the old tooltip can hang indefinitely.
    if (!el) { sembunyikan(); return; }

    if (el === sasaran) { clearTimeout(jedaTampil); return; }

    // Moving to another target closes the old tooltip immediately instead of waiting for the show delay.
    sembunyikan();
    jedaTampil = setTimeout(function () { tampilkan(el); }, 120);
  });

  document.addEventListener("pointerout", function (e) {
    if (!sasaran) return;
    // Moving between children of the same target (e.g. button to its SVG) also fires pointerout; check the destination first to avoid flicker.
    var tujuan = e.relatedTarget;
    if (tujuan && sasaran.contains(tujuan)) return;
    sembunyikan();
  });

  /* Last guard: the hovered element can vanish. The dashboard redraws cards every 5 s and report tables every 10 s, removing the element without pointerout, and the tooltip would hang forever. */
  setInterval(function () {
    if (sasaran && !sasaran.isConnected) sembunyikan();
  }, 500);

  document.addEventListener("focusin", function (e) {
    var el = cariSasaran(e);
    if (el) tampilkan(el);
  });
  document.addEventListener("focusout", sembunyikan);

  // Scrolling or Escape closes the tooltip.
  window.addEventListener("scroll", sembunyikan, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") sembunyikan();
  });
})();
