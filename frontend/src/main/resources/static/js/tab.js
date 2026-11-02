/*
 * Tabs shared by several pages. Panels stay in the DOM and are only `hidden`: pages refresh all panels periodically, so switching tabs never shows stale data and render code need not know which tab is active.
 *
 * Markup:
 *     <div class="tab-bar" role="tablist">
 *       <button class="tab" role="tab" id="tab-x" aria-controls="panel-x" data-tab="x" aria-selected="true">Name</button>
 *       <button class="tab" role="tab" id="tab-y" aria-controls="panel-y" data-tab="y" aria-selected="false">Other</button>
 *     </div>
 *     <div class="tab-panel" id="panel-x" data-tab-panel="x"></div>
 *     <div class="tab-panel" id="panel-y" data-tab-panel="y" hidden></div>
 *
 * Then call once: `NSMTab.pasang(".tab-bar")`.
 *
 * The tab marked `aria-selected="true"` opens by default, otherwise the first. The choice is remembered per page in localStorage (like `lipatan.js`).
 */
(function () {
  "use strict";

  var AWALAN = "nsm.tab.";

  function kunciSimpan(bar) {
    var nama = bar.getAttribute("aria-label") || bar.id || "utama";
    return AWALAN + location.pathname + "." + nama;
  }

  function bacaTersimpan(bar) {
    try {
      return localStorage.getItem(kunciSimpan(bar));
    } catch (e) {
      // localStorage may be refused (private mode, quota); fall back to the markup default.
      return null;
    }
  }

  function simpanTerpilih(bar, kunci) {
    try { localStorage.setItem(kunciSimpan(bar), kunci); } catch (e) {  }
  }

  function pasangSatu(bar) {
    var tombol = Array.prototype.slice.call(bar.querySelectorAll(".tab[data-tab]"));
    if (!tombol.length) return;

    function panel(kunci) {
      return document.querySelector('[data-tab-panel="' + kunci + '"]');
    }

    function pilih(kunci, simpan) {
      tombol.forEach(function (t) {
        var aktif = t.getAttribute("data-tab") === kunci;
        t.setAttribute("aria-selected", aktif ? "true" : "false");
        var p = panel(t.getAttribute("data-tab"));
        if (p) p.hidden = !aktif;
      });
      if (simpan) simpanTerpilih(bar, kunci);
    }

    tombol.forEach(function (t) {
      t.addEventListener("click", function () { pilih(t.getAttribute("data-tab"), true); });
      // Left/right arrows switch tabs (WAI-ARIA tab pattern); Tab itself moves between components.
      t.addEventListener("keydown", function (e) {
        var i = tombol.indexOf(t);
        if (e.key === "ArrowRight") {
          e.preventDefault();
          var kanan = tombol[(i + 1) % tombol.length];
          kanan.focus(); pilih(kanan.getAttribute("data-tab"), true);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          var kiri = tombol[(i - 1 + tombol.length) % tombol.length];
          kiri.focus(); pilih(kiri.getAttribute("data-tab"), true);
        }
      });
    });

    // Default order: marked in markup, then saved from a previous visit, then first. A tab the markup marks as open must not lose to an old stored choice.
    var ditandai = tombol.filter(function (t) {
      return t.getAttribute("aria-selected") === "true";
    })[0];
    var tersimpan = bacaTersimpan(bar);
    var adaTersimpan = tersimpan && tombol.some(function (t) {
      return t.getAttribute("data-tab") === tersimpan;
    });

    if (ditandai) {
      pilih(ditandai.getAttribute("data-tab"), false);
    } else if (adaTersimpan) {
      pilih(tersimpan, false);
    } else {
      pilih(tombol[0].getAttribute("data-tab"), false);
    }
  }

  /* Update the count text and tone in a tab header. `kelas` is "nol" (dimmed) or empty. Same role as `NSMLipat.ringkas()` for collapsible panels. */
  function cacah(kunciTab, teks, kelas) {
    var el = document.querySelector('.tab-cacah[data-untuk-tab="' + kunciTab + '"]');
    if (!el) return;
    el.textContent = teks == null ? "" : String(teks);
    el.className = "tab-cacah" + (kelas ? " " + kelas : "");
  }

  function pasang(selektor) {
    var daftar = document.querySelectorAll(selektor);
    Array.prototype.forEach.call(daftar, pasangSatu);
  }

  window.NSMTab = { pasang: pasang, cacah: cacah };
})();
