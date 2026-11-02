/* Dashboard summary strip plus network rate chart. Six boxes only: a dashboard that shows everything stops being used. Each box that can mean a problem links to the relevant page. One request (`/api/dashboard/ringkas`) feeds the whole strip, since the page refreshes every 5 s and six requests per beat would load Java, Python, and the poller's database. */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var JEDA_MS = 5000;
  var sidikTerakhir = null;
  var kotakEl, grafikEl, kakiEl, jamEl;

  function elSvg(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function el(tag, kelas, teks) {
    var e = document.createElement(tag);
    if (kelas) e.className = kelas;
    if (teks !== undefined && teks !== null) e.textContent = teks;
    return e;
  }

  /* bps to short text. Has its own copy, like other pages in NSM that do not share files. */
  function fmtBps(bps) {
    if (bps === null || bps === undefined) return "-";
    if (bps >= 1e9) return (bps / 1e9).toFixed(2) + " Gbps";
    if (bps >= 1e6) return (bps / 1e6).toFixed(2) + " Mbps";
    if (bps >= 1e3) return (bps / 1e3).toFixed(1) + " kbps";
    return Math.round(bps) + " bps";
  }

  // =======================================================================
  // KOTAK RINGKAS
  // =======================================================================

  /* One box. `nada` (the tone) is computed from the number, not fixed: a "down devices" box that stays red at zero would make red meaningless. */
  function kotak(o) {
    var a = el(o.tautan ? "a" : "div", "ringkas-kotak nada-" + (o.nada || "diam"));
    if (o.tautan) { a.href = o.tautan; }
    if (o.petunjuk) a.setAttribute("data-petunjuk", o.petunjuk);

    a.appendChild(el("div", "ringkas-label", o.label));

    var baris = el("div", "ringkas-baris-angka");
    baris.appendChild(el("span", "ringkas-angka", o.angka));
    if (o.satuan) baris.appendChild(el("span", "ringkas-satuan", o.satuan));
    a.appendChild(baris);

    a.appendChild(el("div", "ringkas-ket", o.ket || ""));
    return a;
  }

  function gambarKotak(d) {
    var dev = d.device || {}, lay = d.layanan || {}, lat = d.latency || {};
    var laju = d.laju || {};
    var f = document.createDocumentFragment();

    // 1. Devices up, with the denominator ("of 10").
    f.appendChild(kotak({
      label: "Perangkat menjawab",
      angka: dev.hidup === undefined ? "-" : dev.hidup,
      satuan: "/ " + (dev.total || 0),
      nada: dev.mati ? "buruk" : "baik",
      ket: dev.dijeda ? (dev.dijeda + " dijeda, tidak dihitung") : "semuanya dipantau",
      petunjuk: "Berapa perangkat yang membalas pemeriksaan terakhir. " +
                "Perangkat yang sedang DIJEDA tidak dihitung sebagai mati — " +
                "ia sengaja tidak dipantau, dan mencampur keduanya membuat " +
                "angka merah menakut-nakuti tentang hal yang sudah diketahui."
    }));

    // 2. Devices down, as its own box rather than a subtraction the reader must do.
    var namaMati = (dev.daftar_mati || []).map(function (x) { return x.nama; });
    f.appendChild(kotak({
      label: "Perangkat mati",
      angka: dev.mati === undefined ? "-" : dev.mati,
      nada: dev.mati ? "buruk" : "baik",
      ket: namaMati.length ? namaMati.slice(0, 2).join(", ") : "tidak ada",
      petunjuk: namaMati.length
        ? ("Tidak menjawab: " + namaMati.join(", ") +
           ". Satu perangkat mati bisa membuat perangkat di belakangnya ikut " +
           "merah tanpa dirinya bermasalah — lihat peta topologi untuk urutan jalurnya.")
        : "Semua perangkat yang dipantau membalas pemeriksaan terakhir."
    }));

    // 3. Services down, kept separate from devices on purpose: ping only proves the machine is on.
    var namaLayanan = (lay.daftar_mati || []).map(function (x) {
      return x.nama + " (" + x.device + ")";
    });
    f.appendChild(kotak({
      label: "Layanan mati",
      angka: lay.mati === undefined ? "-" : lay.mati,
      satuan: "/ " + (lay.total || 0),
      nada: lay.mati ? "buruk" : "baik",
      tautan: "/services",
      ket: namaLayanan.length ? namaLayanan[0] : "semua melayani",
      petunjuk: (namaLayanan.length ? ("Sedang mati: " + namaLayanan.join(", ") + ". ") : "") +
                "Kartu perangkat hijau dengan layanan merah adalah keadaan " +
                "yang wajar: mesinnya menyala, yang berhenti layanan di atasnya."
    }));

    // 4. Incidents today: the only historical number in the strip, limited to today.
    f.appendChild(kotak({
      label: "Insiden hari ini",
      angka: d.insiden_hari_ini === undefined ? "-" : d.insiden_hari_ini,
      nada: d.insiden_hari_ini ? "hati" : "baik",
      tautan: "/report",
      ket: "sejak tengah malam",
      petunjuk: "Berapa kali perangkat BERUBAH menjadi tidak menjawab sejak " +
                "pukul 00.00. Perangkat yang mati sejak kemarin dan belum " +
                "pulih dihitung pada hari ia mulai mati, bukan hari ini."
    }));

    // 5. Average latency plus the worst device by name; an average alone hides one slow device.
    var rata = lat.rata_ms;
    var terlambat = lat.terlambat;
    f.appendChild(kotak({
      label: "Latency rata-rata",
      angka: rata === null || rata === undefined ? "-" : rata.toFixed(0),
      satuan: "ms",
      nada: rata > 150 ? "hati" : "baik",
      ket: terlambat ? ("terlambat: " + terlambat.nama + " " + terlambat.ms.toFixed(0) + " ms")
                     : "belum ada sampel",
      petunjuk: "Rata-rata waktu balasan dari " + (lat.sampel || 0) + " perangkat " +
                "yang menjawab pemeriksaan terakhir. Yang paling lambat disebut " +
                "namanya karena rata-rata sendirian menyembunyikan satu " +
                "perangkat lambat di antara sembilan yang cepat."
    }));

    // 6. Current rate, the same value as the last chart point (one source).
    f.appendChild(kotak({
      label: "Laju jaringan kini",
      angka: fmtBps(laju.masuk_bps === null ? null : (laju.masuk_bps + laju.keluar_bps)),
      nada: "info",
      tautan: "/traffic",
      ket: "masuk " + (laju.masuk_teks || "-") + " · keluar " + (laju.keluar_teks || "-"),
      petunjuk: "Penjumlahan interface TERSIBUK dari " + (laju.perangkat || 0) +
                " perangkat. Ini bukan total lalu lintas jaringan tanpa " +
                "hitungan ganda: paket yang menyeberang antar-lokasi dilihat " +
                "oleh beberapa perangkat sekaligus."
    }));

    kotakEl.replaceChildren(f);
  }

  // =======================================================================
  // GRAFIK LAJU
  // =======================================================================

  /* Chart is hand-drawn SVG like the other NSM charts (CSP `script-src 'self'`). Two mirrored bands: inbound up, outbound down from the same zero line, so the dominant direction is readable from the shape. */
  function gambarGrafik(deret) {
    if (!grafikEl) return;
    grafikEl.replaceChildren();

    if (!deret || deret.length < 2) {
      var p = el("div", "grafik-kosong",
        "Belum cukup sampel lalu lintas untuk digambar. Grafik muncul sesudah " +
        "poller mengumpulkan beberapa pembacaan bandwidth.");
      grafikEl.appendChild(p);
      return;
    }

    var W = 620, H = 150, PAD_KIRI = 6, PAD_KANAN = 6, TENGAH = H / 2;
    var svg = elSvg("svg", {
      viewBox: "0 0 " + W + " " + H, class: "grafik-laju",
      preserveAspectRatio: "none", role: "img",
      "aria-label": "Grafik laju jaringan: masuk ke atas, keluar ke bawah"
    });

    var maks = 0;
    deret.forEach(function (d) {
      maks = Math.max(maks, d.masuk_bps || 0, d.keluar_bps || 0);
    });
    // Floor so a nearly idle network does not make a few bits look like a spike.
    maks = Math.max(maks, 200000);

    var lebarPakai = W - PAD_KIRI - PAD_KANAN;
    function x(i) { return PAD_KIRI + (i / (deret.length - 1)) * lebarPakai; }
    function yAtas(v) { return TENGAH - (Math.min(v, maks) / maks) * (TENGAH - 8); }
    function yBawah(v) { return TENGAH + (Math.min(v, maks) / maks) * (TENGAH - 8); }

    [0.5].forEach(function (f) {
      [yAtas(maks * f), yBawah(maks * f)].forEach(function (yy) {
        svg.appendChild(elSvg("line", { x1: PAD_KIRI, y1: yy, x2: W - PAD_KANAN, y2: yy,
                                        class: "grafik-bantu" }));
      });
    });

    function pita(ambil, ke, kelas) {
      var d = "M" + x(0) + "," + TENGAH;
      deret.forEach(function (t, i) { d += " L" + x(i) + "," + ke(ambil(t) || 0); });
      d += " L" + x(deret.length - 1) + "," + TENGAH + " Z";
      svg.appendChild(elSvg("path", { d: d, class: kelas }));

      var garis = "M" + x(0) + "," + ke(ambil(deret[0]) || 0);
      deret.forEach(function (t, i) { if (i) garis += " L" + x(i) + "," + ke(ambil(t) || 0); });
      svg.appendChild(elSvg("path", { d: garis, class: kelas + "-garis" }));
    }

    pita(function (t) { return t.masuk_bps; }, yAtas, "grafik-masuk");
    pita(function (t) { return t.keluar_bps; }, yBawah, "grafik-keluar");

    // Zero line drawn last so the bands do not cover it.
    svg.appendChild(elSvg("line", { x1: PAD_KIRI, y1: TENGAH, x2: W - PAD_KANAN, y2: TENGAH,
                                    class: "grafik-nol" }));
    grafikEl.appendChild(svg);

    // The peak is given as a number so the shape can be compared with things outside this chart.
    if (kakiEl) {
      var menit = deret.length;
      kakiEl.replaceChildren();
      kakiEl.appendChild(el("span", "grafik-kaki-kiri",
        menit + " menit terakhir · satu titik = 1 menit"));
      kakiEl.appendChild(el("span", "grafik-kaki-kanan",
        "puncak skala " + fmtBps(maks)));
    }
  }

  // =======================================================================
  // DENYUT
  // =======================================================================

  function gambar(d) {
    if (!d) return;
    // Like the topology map: if the content fingerprint is unchanged, nothing is redrawn (avoids flicker and losing text selection).
    if (d.sidik && d.sidik === sidikTerakhir) return;
    sidikTerakhir = d.sidik || null;

    gambarKotak(d);
    gambarGrafik(d.deret_laju);
    if (jamEl && d.waktu) {
      var t = new Date(d.waktu);
      jamEl.textContent = "diperbarui " +
        String(t.getHours()).padStart(2, "0") + "." +
        String(t.getMinutes()).padStart(2, "0") + "." +
        String(t.getSeconds()).padStart(2, "0");
    }
  }

  function tarik() {
    ambilJson("/api/dashboard/ringkas").then(gambar).catch(function () {
      // Stay silent on a single failure: the next beat is 5 s away. Never stop retrying, so there is no failure counter that cancels the timer.
    });
  }

  function pasang() {
    kotakEl = document.getElementById("ringkas-kotak");
    grafikEl = document.getElementById("ringkas-grafik");
    kakiEl = document.getElementById("ringkas-grafik-kaki");
    jamEl = document.getElementById("ringkas-jam");
    if (!kotakEl) return;
    tarik();
    setInterval(tarik, JEDA_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pasang);
  } else {
    pasang();
  }
})();
