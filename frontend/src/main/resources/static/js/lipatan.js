/*
 * Collapsible panels shared by several pages. Layer 1 (the answer) is always visible, even when the panel is closed; layer 2 (evidence) is inside the panel; layer 3 is raw data. The panel header has a slot for a summary (e.g. "1 of 3 problem") so closing a panel never hides its answer.
 *
 * Usage: add an attribute to the heading in HTML:
 *     <h2 data-lipat="grafik">Grafik Langsung</h2>
 *     <h2 data-lipat="riwayat" data-lipat-buka>Riwayat Gangguan</h2>
 *
 * All elements after the heading, up to the next `data-lipat` heading, go into its panel. `data-lipat-buka` means open by default.
 *
 * Panel state is remembered in localStorage per page; the pages refresh every 10 seconds and a freshly opened panel would otherwise close before it could be read.
 */
(function () {
  "use strict";

  var AWALAN = "nsm.lipat.";

  function kunciSimpan(kunci) {
    // Keyed per page: "grafik" on the device page and elsewhere are different panels.
    return AWALAN + location.pathname.replace(/\/\d+$/, "/:id") + "." + kunci;
  }

  function bacaKeadaan(kunci, bawaanTerbuka) {
    try {
      var v = localStorage.getItem(kunciSimpan(kunci));
      if (v === "1") return true;
      if (v === "0") return false;
    } catch (e) {
      // localStorage may be refused (private mode, quota, site policy); fall back to defaults instead of disabling the panels.
    }
    return !!bawaanTerbuka;
  }

  function simpanKeadaan(kunci, terbuka) {
    try {
      localStorage.setItem(kunciSimpan(kunci), terbuka ? "1" : "0");
    } catch (e) { /* ignored, see the reason in `bacaKeadaan` */ }
  }

  function isiMilik(judul) {
    var isi = [];
    var n = judul.nextElementSibling;
    while (n && !n.hasAttribute("data-lipat")) {
      isi.push(n);
      n = n.nextElementSibling;
    }
    return isi;
  }

  function pasang(judul) {
    var kunci = judul.getAttribute("data-lipat");
    if (!kunci) return;

    var isi = isiMilik(judul);
    if (!isi.length) return;

    var terbuka = bacaKeadaan(kunci, judul.hasAttribute("data-lipat-buka"));

    // --- bungkus isinya ---
    var kotak = document.createElement("div");
    kotak.className = "isi-panel";
    kotak.id = "panel-isi-" + kunci;
    judul.parentNode.insertBefore(kotak, judul.nextSibling);
    isi.forEach(function (el) { kotak.appendChild(el); });

    // --- ubah judulnya jadi tombol ---
    judul.classList.add("kepala-panel");
    judul.setAttribute("role", "button");
    judul.setAttribute("tabindex", "0");
    judul.setAttribute("aria-controls", kotak.id);

    var tanda = document.createElement("span");
    tanda.className = "tanda-lipat";
    tanda.setAttribute("aria-hidden", "true");
    judul.insertBefore(tanda, judul.firstChild);

    var ringkas = document.createElement("span");
    ringkas.className = "ringkas-panel";
    ringkas.dataset.untuk = kunci;
    judul.appendChild(ringkas);

    function terapkan(bukaSekarang, simpan) {
      kotak.hidden = !bukaSekarang;
      judul.setAttribute("aria-expanded", bukaSekarang ? "true" : "false");
      judul.classList.toggle("tertutup", !bukaSekarang);
      if (simpan) simpanKeadaan(kunci, bukaSekarang);
      if (bukaSekarang) {
        // A canvas drawn while hidden uses a 600px fallback width and stretches when opened. grafik.js already listens for resize, so it is triggered here.
        window.dispatchEvent(new Event("resize"));
      }
    }

    terapkan(terbuka, false);

    function alih() { terapkan(kotak.hidden, true); }

    judul.addEventListener("click", alih);
    judul.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); alih(); }
    });

    judul._bukaPanel = function () { if (kotak.hidden) terapkan(true, true); };
  }

  /* Open all panels wrapping an element. Used when the page is reached by an anchor (e.g. #insiden-{id} from the Report page); a link landing inside a closed panel looks broken. */
  function bukaUntuk(el) {
    var n = el;
    while (n && n !== document.body) {
      if (n.classList && n.classList.contains("isi-panel")) {
        var judul = n.previousElementSibling;
        if (judul && judul._bukaPanel) judul._bukaPanel();
      }
      n = n.parentNode;
    }
  }

  function isiRingkas(kunci, teks, kelas) {
    var el = document.querySelector('.ringkas-panel[data-untuk="' + kunci + '"]');
    if (!el) return;
    el.textContent = teks || "";
    el.className = "ringkas-panel" + (kelas ? " " + kelas : "");
    el.dataset.untuk = kunci;
  }

  /* Footer help paragraphs are hidden behind one button; short ones are left as they are. */
  var BATAS_PANJANG = 220;

  function pasangCatatan(catatan) {
    var teks = (catatan.textContent || "").trim();
    if (teks.length < BATAS_PANJANG) return;

    var kunci = "catatan";
    var terbuka = bacaKeadaan(kunci, false);

    var tombol = document.createElement("button");
    tombol.type = "button";
    tombol.className = "tombol-catatan";
    tombol.setAttribute("aria-controls", "catatan-halaman");
    catatan.id = "catatan-halaman";
    catatan.parentNode.insertBefore(tombol, catatan);

    function terapkan(buka, simpan) {
      catatan.hidden = !buka;
      tombol.setAttribute("aria-expanded", buka ? "true" : "false");
      tombol.textContent = buka
        ? "Sembunyikan penjelasan halaman ini"
        : "Apa arti yang ada di halaman ini?";
      if (simpan) simpanKeadaan(kunci, buka);
    }

    terapkan(terbuka, false);
    tombol.addEventListener("click", function () { terapkan(catatan.hidden, true); });
  }

  function mulai() {
    var catatan = document.querySelector(".catatan");
    if (catatan) pasangCatatan(catatan);

    var judul = document.querySelectorAll("[data-lipat]");
    // Processed from the end: `isiMilik()` reads the siblings after a heading and wrapping moves them, so processing from the front would wrap the next heading before it is checked.
    for (var i = judul.length - 1; i >= 0; i--) pasang(judul[i]);

    if (location.hash) {
      var sasaran = document.querySelector(location.hash);
      if (sasaran) { bukaUntuk(sasaran); sasaran.scrollIntoView({ block: "center" }); }
    }
  }

  window.NSMLipat = { bukaUntuk: bukaUntuk, ringkas: isiRingkas };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mulai);
  } else {
    mulai();
  }
})();
