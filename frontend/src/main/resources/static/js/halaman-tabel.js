/*
 * Client-side pagination for history tables and card containers: 5 rows/cards per page. `pasang()` accepts any container: a `<table>` is read via `tBodies[0].rows`, anything else via its `children`.
 *
 * Five rather than the usual 10 because these tables sit below summaries and number cards. Data is paginated in the browser because the APIs already send it in full; a table that grows to thousands of rows should move to server pagination (see `BATAS_WAJAR`).
 *
 * Usage:
 *   halamanTabel.pasang(elemenTabel);              // 5 rows
 *   halamanTabel.pasang(elemenTabel, {perHal: 8});
 *
 * Safe to call again: an already wired table is refreshed, not given a second control.
 */
(function (global) {
  "use strict";

  var PER_HALAMAN = 5;

  // Above this size, browser pagination still ships thousands of unseen DOM rows. Logged as a console warning, since the endpoint design is what needs fixing.
  var BATAS_WAJAR = 500;

  function buatKontrol() {
    var k = document.createElement("div");
    k.className = "hal-tabel";
    k.innerHTML =
      '<span class="hal-info"></span>' +
      '<span class="hal-tombol">' +
      '<button type="button" class="hal-mundur">Sebelumnya</button>' +
      '<span class="hal-posisi"></span>' +
      '<button type="button" class="hal-maju">Berikutnya</button>' +
      '</span>';
    return k;
  }

  // Tables are read via their `<tr>` rows, other containers via direct children. `null` means "table not ready" (no `<tbody>` yet), distinct from an empty array.
  function ambilItem(wadah) {
    if (wadah.tagName === "TABLE") {
      var tbody = wadah.tBodies[0];
      return tbody ? Array.prototype.slice.call(tbody.rows) : null;
    }
    return Array.prototype.slice.call(wadah.children);
  }

  function pasang(wadah, opsi) {
    if (!wadah) return;
    opsi = opsi || {};
    var perHal = opsi.perHal || PER_HALAMAN;

    var baris = ambilItem(wadah);
    if (baris === null) return;

    // The control belongs to this table, not a neighbor: it is always inserted right after the table (or after its `div.gulir-tabel` wrapper if present, so the Next button does not scroll away with a wide table). Looking it up as the first control among the parent's children made several tables share one control.
    var jangkar = (wadah.parentNode
      && wadah.parentNode.classList.contains("gulir-tabel"))
      ? wadah.parentNode : wadah;

    var lama = jangkar.nextElementSibling;
    if (lama && !lama.classList.contains("hal-tabel")) lama = null;
    if (baris.length <= perHal) {
      if (lama) lama.remove();
      wadah.classList.remove("berpaginasi");
      baris.forEach(function (b) { b.hidden = false; });
      return;
    }

    if (baris.length > BATAS_WAJAR && global.console) {
      console.warn("halaman-tabel: " + baris.length + " baris dipaginasi di "
        + "peramban. Di atas " + BATAS_WAJAR + " baris, yang benar adalah "
        + "paginasi di sisi server.");
    }

    // Marker for print CSS (see nsm.css): otherwise printing page 1 would silently drop the remaining rows.
    wadah.classList.add("berpaginasi");

    var kontrol = lama || buatKontrol();
    if (!lama) jangkar.parentNode.insertBefore(kontrol, jangkar.nextSibling);

    var info = kontrol.querySelector(".hal-info");
    var posisi = kontrol.querySelector(".hal-posisi");
    var mundur = kontrol.querySelector(".hal-mundur");
    var maju = kontrol.querySelector(".hal-maju");

    // If the URL hash links to a row, open the page containing it; `scrollIntoView` does nothing on `hidden` elements.
    var hal = 0;
    if (location.hash.length > 1) {
      var idJangkar = location.hash.slice(1);
      for (var hi = 0; hi < baris.length; hi++) {
        if (baris[hi].id === idJangkar) { hal = Math.floor(hi / perHal); break; }
      }
    }
    var totalHal = Math.ceil(baris.length / perHal);

    function gambar() {
      var awal = hal * perHal;
      var akhir = Math.min(awal + perHal, baris.length);
      for (var i = 0; i < baris.length; i++) {
        baris[i].hidden = (i < awal || i >= akhir);
      }
      // Show the total ("6-10 of 40"), not just the page number.
      info.textContent = (awal + 1) + "–" + akhir + " dari " + baris.length;
      posisi.textContent = (hal + 1) + " / " + totalHal;
      mundur.disabled = (hal === 0);
      maju.disabled = (hal >= totalHal - 1);
    }

    mundur.onclick = function () { if (hal > 0) { hal--; gambar(); } };
    maju.onclick = function () { if (hal < totalHal - 1) { hal++; gambar(); } };
    gambar();
  }

  function terapkan(wadah) {
    wadah = wadah || document;
    var daftar = wadah.querySelectorAll("table[data-hal]");
    for (var i = 0; i < daftar.length; i++) {
      var n = parseInt(daftar[i].getAttribute("data-hal"), 10);
      pasang(daftar[i], { perHal: n > 0 ? n : PER_HALAMAN });
    }
  }

  global.halamanTabel = { pasang: pasang, terapkan: terapkan,
                          PER_HALAMAN: PER_HALAMAN };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { terapkan(); });
  } else {
    terapkan();
  }
})(window);
