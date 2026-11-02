/*
 * Shared client-side table sorter. Only columns whose header declares `data-urut="teks"` or `data-urut="angka"` are sortable.
 * Cells hold human-formatted text ("1 jam 26 menit", "356.83 KB") that sorts wrongly as text, so numeric columns must carry the raw value in `td.dataset.nilai`; cells without it always sort last.
 * Sorting is done in the browser because these tables load all rows at once and no numbers are computed here, only rows moved.
 * Pages redraw their tbody every 5 to 30 seconds, so the tbody is observed and the chosen order is reapplied after each redraw.
 */
(function () {
  "use strict";

  var AWALAN = "nsm.urut.";

  function kunciSimpan(tabel) {
    // State is kept per page and per table, so sorting one table does not affect another. Same key pattern as lipatan.js.
    var id = tabel.id || tabel.getAttribute("data-urut-nama") || "tabel";
    return AWALAN + location.pathname.replace(/\/\d+$/, "/:id") + "." + id;
  }

  function baca(tabel) {
    try {
      var v = localStorage.getItem(kunciSimpan(tabel));
      return v ? JSON.parse(v) : null;
    } catch (e) {
      // localStorage can be denied (private mode, full quota); sorting still works, it is just not remembered.
      return null;
    }
  }

  function simpan(tabel, kolom, naik) {
    try {
      localStorage.setItem(kunciSimpan(tabel),
        JSON.stringify({ kolom: kolom, naik: naik }));
    } catch (e) { /* see the reason in baca() */ }
  }

  /* Comparable value of a cell. Returns null when the cell has no valid value; such rows always go last, in either direction. */
  function nilai(sel, jenis) {
    if (!sel) return null;
    if (jenis === "angka" || jenis === "waktu") {
      // Only `data-nilai` is trusted; the displayed text is formatted for humans.
      var mentah = sel.dataset ? sel.dataset.nilai : null;
      if (mentah === undefined || mentah === null || mentah === "") return null;
      var n = Number(mentah);
      return isNaN(n) ? null : n;
    }
    var teks = (sel.textContent || "").trim();
    return teks === "" || teks === "-" ? null : teks.toLocaleLowerCase("id-ID");
  }

  function banding(a, b) {
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b), "id-ID");
  }

  function urutkan(tabel, kolom, naik) {
    var tbody = tabel.tBodies[0];
    if (!tbody) return;
    var th = tabel.tHead ? tabel.tHead.rows[0].cells[kolom] : null;
    var jenis = th ? th.getAttribute("data-urut") : "teks";

    // A data row and its explanation row move as one unit. Explanation rows are recognized by a single spanning cell (colSpan) and follow the data row above them.
    var kelompok = [];
    Array.prototype.forEach.call(tbody.rows, function (r) {
      if (r.cells.length > 1) {
        kelompok.push({ utama: r, ikut: [] });
      } else if (kelompok.length) {
        kelompok[kelompok.length - 1].ikut.push(r);
      }
    });
    if (kelompok.length < 2) return;

    kelompok.sort(function (a, b) {
      var h = banding(nilai(a.utama.cells[kolom], jenis),
                      nilai(b.utama.cells[kolom], jenis));
      return naik ? h : -h;
    });
    kelompok.forEach(function (k) {
      tbody.appendChild(k.utama);
      k.ikut.forEach(function (r) { tbody.appendChild(r); });
    });

    Array.prototype.forEach.call(tabel.tHead.rows[0].cells, function (sel, i) {
      if (!sel.hasAttribute("data-urut")) return;
      sel.setAttribute("aria-sort",
        i === kolom ? (naik ? "ascending" : "descending") : "none");
      sel.classList.toggle("urut-naik", i === kolom && naik);
      sel.classList.toggle("urut-turun", i === kolom && !naik);
    });
  }

  function pasang(tabel) {
    if (!tabel.tHead || !tabel.tHead.rows.length) return;
    var keadaan = baca(tabel);

    Array.prototype.forEach.call(tabel.tHead.rows[0].cells, function (th, i) {
      if (!th.hasAttribute("data-urut")) return;

      th.classList.add("bisa-urut");
      th.setAttribute("role", "button");
      th.setAttribute("tabindex", "0");
      th.setAttribute("aria-sort", "none");

      function klik() {
        var sekarang = baca(tabel);
        // A second click on the same column reverses direction; a new column always starts ascending.
        var naik = (sekarang && sekarang.kolom === i) ? !sekarang.naik : true;
        simpan(tabel, i, naik);
        urutkan(tabel, i, naik);
      }

      th.addEventListener("click", klik);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); klik(); }
      });
    });

    // The observer is disconnected while `urutkan()` runs and reconnected afterwards. A synchronous flag is not enough because MutationObserver callbacks are microtasks that fire after the flag is reset, which would loop forever.
    var pengamat = null;

    function terapkanLagi() {
      var k = baca(tabel);
      if (!k) return;
      if (pengamat) pengamat.disconnect();
      urutkan(tabel, k.kolom, k.naik);
      if (pengamat) pengamat.observe(tabel.tBodies[0], { childList: true });
    }

    terapkanLagi();

    // Tables are redrawn on every refresh, so the chosen order is reapplied after each redraw.
    var tbody = tabel.tBodies[0];
    if (tbody && window.MutationObserver) {
      pengamat = new MutationObserver(terapkanLagi);
      pengamat.observe(tbody, { childList: true });
    }
  }

  function mulai() {
    var tabel = document.querySelectorAll("table");
    Array.prototype.forEach.call(tabel, function (t) {
      if (t.querySelector("thead [data-urut]")) pasang(t);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mulai);
  } else {
    mulai();
  }
})();
