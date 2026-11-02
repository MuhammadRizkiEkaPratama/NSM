/*
 * Insights / SOC agent / tenant pages in one file. The page is chosen by which elements exist in the document, not by template name (same pattern as `drift.js`, `sot.js`, `insiden.js`).
 * Entirely read-only: no POST, so no CSRF token is needed. The agent is enabled only through `.env` by someone at the machine.
 * All text goes through textContent, never innerHTML: log templates come from network devices over unauthenticated UDP syslog and are the least trusted input in the system.
 */

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function kosongkan(n) { while (n.firstChild) n.removeChild(n.firstChild); }

function pesanGalat(e) {
  if (e && e.badan && e.badan.ditolak) return e.badan.ditolak;
  return e && e.message ? e.message : String(e);
}

function tampilGalat(wadah, e) {
  if (!wadah) return;
  kosongkan(wadah);
  wadah.appendChild(el("p", "wsn-kosong", pesanGalat(e)));
}

function kosong(wadah, kalimat) {
  kosongkan(wadah);
  wadah.appendChild(el("p", "wsn-kosong", kalimat));
}

function kartuMini(judul, isi, kelas) {
  var k = el("div", "kartu-mini");
  k.appendChild(el("div", "judul", judul));
  k.appendChild(el("div", "isi angka-mini" + (kelas ? " " + kelas : ""), isi));
  return k;
}

/* Bits per second to a readable unit. Decimal (not 1024) on purpose: network speeds are decimal, so figures match what the device reports. */
function bps(v) {
  if (v === null || v === undefined) return "-";
  var a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + " Gbit/s";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + " Mbit/s";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + " kbit/s";
  return v.toFixed(0) + " bit/s";
}

/* Severity class from the deviation score. Same threshold as Python (`aneh` at 3 sigma) so the UI color and the API verdict agree. */
function kelasSigma(s) {
  if (s === null || s === undefined) return "netral";
  if (s >= 6) return "parah";
  if (s >= 3) return "waspada";
  return "aman";
}

var KELAS_VONIS = {
  cukup: "aman", stabil: "aman", menurun: "aman",
  tidak_yakin: "waspada", kapasitas_tak_diketahui: "netral",
  tidak_cukup_data: "netral", habis: "parah", menipis: "waspada"
};

function lencanaVonis(v) {
  var kelas = KELAS_VONIS[v] || "netral";
  var peta = {aman: "lencana-up", waspada: "lencana-menunggu",
              parah: "lencana-down", netral: "lencana-netral"};
  return el("span", "lencana " + peta[kelas], String(v || "-").replace(/_/g, " "));
}

function gambarTemplat(teks) {
  var d = el("div", "wsn-templat");
  var sisa = String(teks || "");
  var i;
  while ((i = sisa.indexOf("<*>")) >= 0) {
    if (i > 0) d.appendChild(document.createTextNode(sisa.slice(0, i)));
    d.appendChild(el("span", "ganti", "<*>"));
    sisa = sisa.slice(i + 3);
  }
  if (sisa) d.appendChild(document.createTextNode(sisa));
  return d;
}


/* ===========================================================================
 * C1 -- BASELINE
 * =========================================================================*/

function gambarBaseline(d) {
  var wCatatan = document.getElementById("baseline-catatan");
  var wRingkas = document.getElementById("baseline-ringkas");
  var wadah = document.getElementById("baseline");

  // The "still catching up" warning is drawn above the number: while the baseline is incomplete, deviation figures are misleading and would read as a real alarm.
  kosongkan(wCatatan);
  if (d.mengejar && d.catatan) {
    wCatatan.appendChild(el("div", "wsn-peringatan", d.catatan));
  }

  var semua = d.semua || [];
  var aneh = d.aneh || [];
  kosongkan(wRingkas);
  wRingkas.appendChild(kartuMini("Menyimpang (>= " + d.ambang + " sigma)",
    String(aneh.length), aneh.length ? "buruk" : "aman"));
  wRingkas.appendChild(kartuMini("Bisa dinilai", String(semua.length)));
  wRingkas.appendChild(kartuMini("Belum cukup sampel",
    String(d.belum_cukup === undefined ? "-" : d.belum_cukup)));
  wRingkas.appendChild(kartuMini("Baseline",
    d.mengejar ? "sedang mengejar" : "sudah lengkap",
    d.mengejar ? null : "aman"));

  kosongkan(wadah);
  if (!semua.length) {
    kosong(wadah, "Belum ada perangkat yang kebiasaannya cukup terkumpul "
                + "untuk dinilai. Baseline butuh minimal 20 sampel per "
                + "jam-dalam-minggu sebelum ia berani menyebut angka.");
    return;
  }
  semua.forEach(function (h) {
    var kelas = kelasSigma(h.sigma);
    var b = el("div", "wsn-baris " + kelas);

    var atas = el("div", "atas");
    atas.appendChild(el("span", "wsn-sigma " + kelas,
      (h.sigma === null || h.sigma === undefined ? "-" : h.sigma.toFixed(2))));
    atas.appendChild(el("span", "nama", h.device || "?"));
    atas.appendChild(el("span", "kapan", h.slot_teks || ""));
    b.appendChild(atas);

    b.appendChild(el("div", "ket", h.kalimat || ""));

    var a = el("div", "angka-baris");
    var x1 = el("span");
    x1.appendChild(document.createTextNode("biasanya "));
    x1.appendChild(el("b", null, (h.biasanya || 0).toFixed(1) + " ms"));
    a.appendChild(x1);
    var x2 = el("span");
    x2.appendChild(document.createTextNode("sekarang "));
    x2.appendChild(el("b", null, (h.nilai || 0).toFixed(1) + " ms"));
    a.appendChild(x2);
    var x3 = el("span");
    x3.appendChild(el("b", null, String(h.n || 0)));
    x3.appendChild(document.createTextNode(" sampel di slot ini"));
    a.appendChild(x3);
    b.appendChild(a);

    wadah.appendChild(b);
  });
}


/* ===========================================================================
 * C2 -- POLA LOG
 * =========================================================================*/

function barisPola(t, sorotBaru) {
  var b = el("div", "wsn-baris " + (sorotBaru ? "waspada" : "netral"));
  var atas = el("div", "atas");
  atas.appendChild(el("span", "nama", "x" + (t.jumlah || 0)));
  if (t.severity_min !== null && t.severity_min !== undefined) {
    // Syslog severity: lower is more severe (0 = emergency, 7 = debug).
    var parah = t.severity_min <= 3;
    atas.appendChild(el("span",
      "lencana " + (parah ? "lencana-down" : "lencana-netral"),
      "sev " + t.severity_min));
  }
  if (t.jumlah_device > 1) {
    atas.appendChild(el("span", "lencana lencana-menunggu",
      t.jumlah_device + " device"));
  }
  b.appendChild(atas);
  b.appendChild(gambarTemplat(t.templat));

  var a = el("div", "angka-baris");
  if (t.pertama) {
    var p = el("span");
    p.appendChild(document.createTextNode("pertama "));
    p.appendChild(el("b", null, waktuRelatif(t.pertama)));
    a.appendChild(p);
  }
  if (t.terakhir) {
    var q = el("span");
    q.appendChild(document.createTextNode("terakhir "));
    q.appendChild(el("b", null, waktuRelatif(t.terakhir)));
    a.appendChild(q);
  }
  b.appendChild(a);
  return b;
}

function gambarPolaLog(d) {
  var wRingkas = document.getElementById("pola-ringkas");
  var wBaru = document.getElementById("pola-baru");
  var wSering = document.getElementById("pola-sering");

  kosongkan(wRingkas);
  if (!d.tersedia) {
    // A missing library means the feature is off; say so explicitly, since an empty page would read as "no log messages".
    kosong(wBaru, "Penambangan pola tidak berjalan: pustaka drain3 belum "
                + "terpasang di lingkungan ini.");
    kosongkan(wSering);
    return;
  }

  var hemat = (d.total_pesan || 0) - (d.total_templat || 0);
  wRingkas.appendChild(kartuMini("Pesan log", String(d.total_pesan || 0)));
  wRingkas.appendChild(kartuMini("Pola berbeda", String(d.total_templat || 0)));
  wRingkas.appendChild(kartuMini("Pola BARU (" + d.jam + " jam)",
    String((d.baru || []).length), (d.baru || []).length ? "buruk" : "aman"));
  wRingkas.appendChild(kartuMini("Dilipat",
    (d.total_pesan || 0) + " pesan → " + (d.total_templat || 0) + " pola",
    hemat > 0 ? "aman" : null));
  wRingkas.querySelectorAll(".angka-mini").forEach(function (n, i) {
    if (i === 3) n.classList.add("kecil-teks");
  });

  kosongkan(wBaru);

  // Warning goes above the list: if NSM's own syslog history is shorter than this window, every pattern counts as new, which trains readers to ignore the list.
  if (d.riwayat_muda && d.catatan) {
    wBaru.appendChild(el("div", "wsn-peringatan", d.catatan));
  }

  if (!(d.baru || []).length) {
    kosong(wBaru, "Tidak ada pola baru dalam " + d.jam + " jam terakhir. "
                + "Itu kabar baik: perangkat tidak mengatakan sesuatu yang "
                + "belum pernah ia katakan.");
  } else {
    d.baru.forEach(function (t) { wBaru.appendChild(barisPola(t, true)); });
  }

  kosongkan(wSering);
  if (!(d.tersering || []).length) {
    kosong(wSering, "Belum ada pesan log yang tertambang.");
  } else {
    d.tersering.slice(0, 12).forEach(function (t) {
      wSering.appendChild(barisPola(t, false));
    });
  }
}


/* ===========================================================================
 * C3 -- PRAKIRAAN
 * =========================================================================*/

function barisPrakiraan(h, angka) {
  var kelas = KELAS_VONIS[h.vonis] || "netral";
  var b = el("div", "wsn-baris " + kelas);
  var atas = el("div", "atas");
  atas.appendChild(el("span", "nama", h.nama || "?"));
  atas.appendChild(lencanaVonis(h.vonis));
  b.appendChild(atas);
  b.appendChild(el("div", "ket", h.alasan || ""));
  if (angka && angka.length) {
    var a = el("div", "angka-baris");
    angka.forEach(function (pasangan) {
      if (pasangan[1] === null || pasangan[1] === undefined) return;
      var x = el("span");
      x.appendChild(document.createTextNode(pasangan[0] + " "));
      x.appendChild(el("b", null, pasangan[1]));
      a.appendChild(x);
    });
    if (a.childNodes.length) b.appendChild(a);
  }
  return b;
}

function gambarPrakiraan(d) {
  var wLat = document.getElementById("prakiraan-latency");
  var wBw = document.getElementById("prakiraan-bandwidth");

  kosongkan(wLat);
  if (!(d.latency || []).length) {
    kosong(wLat, "Belum ada device dengan riwayat rollup jam yang cukup.");
  } else {
    d.latency.forEach(function (h) {
      wLat.appendChild(barisPrakiraan(h, [
        ["sekarang", h.latency_kini_ms === null || h.latency_kini_ms === undefined
          ? null : h.latency_kini_ms.toFixed(1) + " ms"],
        ["laju", h.laju_persen_per_minggu === null
          || h.laju_persen_per_minggu === undefined
          ? null : h.laju_persen_per_minggu.toFixed(1) + "% per minggu"]
      ]));
    });
  }

  kosongkan(wBw);
  if (!(d.bandwidth || []).length) {
    kosong(wBw, "Belum ada sampel bandwidth yang cukup.");
  } else {
    d.bandwidth.forEach(function (h) {
      wBw.appendChild(barisPrakiraan(h, [
        ["puncak", bps(h.puncak_bps)],
        ["laju", h.laju_bps_per_hari === null || h.laju_bps_per_hari === undefined
          ? null : bps(h.laju_bps_per_hari) + " per hari"],
        ["penuh dalam", h.horizon_teks || null]
      ]));
    });
  }
}

function gambarAnggaran(d) {
  var w = document.getElementById("prakiraan-anggaran");
  kosongkan(w);
  var baris = (d && d.anggaran) || [];
  if (!baris.length) {
    kosong(w, "Belum ada device yang pengamatannya cukup panjang untuk "
            + "menerbitkan angka anggaran galat.");
    return;
  }
  baris.forEach(function (h) {
    w.appendChild(barisPrakiraan(h, [
      ["sisa", h.sisa_persen === null || h.sisa_persen === undefined
        ? null : h.sisa_persen.toFixed(0) + "%"],
      ["target", h.target_persen === null || h.target_persen === undefined
        ? null : h.target_persen + "%"],
      ["habis dalam", h.horizon_teks || null]
    ]));
  });
}


/* ===========================================================================
 * C4 -- AGEN SOC
 * =========================================================================*/

function gambarSaklarAgen(d) {
  var w = document.getElementById("agen-saklar");
  kosongkan(w);
  var kisi = el("div", "wsn-saklar");

  function item(kunci, nyala, teksNilai, arti, kelasKhusus) {
    var i = el("div", "item");
    i.appendChild(el("div", "kunci", kunci));
    i.appendChild(el("div", "nilai " + (kelasKhusus || (nyala ? "nyala" : "mati")),
                     teksNilai));
    i.appendChild(el("div", "arti", arti));
    kisi.appendChild(i);
  }

  item("AGEN_SOC_AKTIF", d.aktif, d.aktif ? "NYALA" : "MATI",
       d.aktif ? "Agen menangani insiden baru dan mencatat usulannya."
               : "Agen tidak bekerja sama sekali. Ini bawaannya.");

  item("AGEN_SOC_MODE", d.mode === "jalan", d.mode.toUpperCase(),
       d.mode === "jalan"
         ? "Usulannya DITERUSKAN ke pagar, dan pagar yang memutuskan."
         : "Agen mencatat apa yang AKAN dilakukannya, tanpa melakukannya.",
       d.mode === "jalan" ? "awas" : "mati");

  item("AGEN_SOC_NARASI", d.narasi_ai, d.narasi_ai ? "NYALA" : "MATI",
       d.narasi_ai
         ? "Narasi insiden ditulis ulang lewat LLM API."
         : "Tidak ada data yang dikirim ke luar jaringan lab. Narasi tetap "
           + "ada, disusun dari templat.");

  w.appendChild(kisi);

  if (!d.aktif) {
    w.appendChild(el("div", "wsn-peringatan",
      "Agen SOC MATI. Halaman ini akan tetap kosong sampai "
      + "AGEN_SOC_AKTIF=1 disetel di .env dan poller dimulai ulang. Itu "
      + "disengaja: komponen yang mengusulkan tindakan pada perangkat "
      + "jaringan pantas dinyalakan oleh keputusan sadar seseorang, bukan "
      + "oleh sebuah deploy."));
  }
}

var LABEL_JENIS = {
  triase: "Triase", bukti: "Pengayaan bukti",
  narasi: "Narasi", tindakan: "Usulan tindakan"
};

function barisUsulan(u) {
  var kelas = u.vonis_pagar === "tolak" ? "waspada"
            : u.vonis_pagar === "izin" ? "aman" : "netral";

  // A row of kind "tindakan" with an empty `tindakan` proposes nothing; it records why nothing was proposed. It must not be titled "Usulan tindakan", or it contradicts the counter, which only counts rows that have an action.
  if (u.jenis === "tindakan" && !u.tindakan) {
    return barisUsulanJudul(u, kelas, "Tidak ada tindakan diusulkan");
  }
  return barisUsulanJudul(u, kelas, LABEL_JENIS[u.jenis] || u.jenis);
}

function barisUsulanJudul(u, kelas, judul) {
  var b = el("div", "wsn-baris " + kelas);

  var atas = el("div", "atas");
  atas.appendChild(el("span", "nama", judul));
  if (u.tindakan) {
    atas.appendChild(el("span", "lencana lencana-netral", u.tindakan));
  }
  if (u.vonis_pagar && u.vonis_pagar !== "tidak_diminta") {
    atas.appendChild(el("span",
      "lencana " + (u.vonis_pagar === "izin" ? "lencana-up" : "lencana-down"),
      u.vonis_pagar === "izin" ? "pagar mengizinkan" : "pagar MENOLAK"));
  }
  if (u.mode) atas.appendChild(el("span", "lencana lencana-netral",
                                  "mode " + u.mode));
  var kapan = el("span", "kapan");
  kapan.title = waktuLengkap(u.waktu);
  pasangWaktuRelatif(kapan, u.waktu);
  atas.appendChild(kapan);
  b.appendChild(atas);

  var isi = u.isi || {};
  if (u.jenis === "narasi" && isi.teks) {
    b.appendChild(el("div", "ket", isi.teks));
    b.appendChild(el("div", "angka-baris", "sumber: " + (isi.sumber || "-")));
  } else if (u.jenis === "triase") {
    b.appendChild(el("div", "ket", isi.riwayat || ""));
    var a = el("div", "angka-baris");
    if (isi.akar) {
      var x = el("span");
      x.appendChild(document.createTextNode("akar "));
      x.appendChild(el("b", null, isi.akar));
      a.appendChild(x);
    }
    if (isi.device_terdampak) {
      var y = el("span");
      y.appendChild(el("b", null, String(isi.device_terdampak.length)));
      y.appendChild(document.createTextNode(" perangkat terdampak"));
      a.appendChild(y);
    }
    b.appendChild(a);
  } else if (u.jenis === "tindakan") {
    // Show the full refusal reason: hiding it means nobody learns that something could be done but is not allowed.
    if (u.alasan_pagar) b.appendChild(el("div", "ket", u.alasan_pagar));
    if (isi.alasan_pilih) {
      b.appendChild(el("div", "angka-baris",
                       "alasan memilih: " + isi.alasan_pilih));
    }
  } else if (u.jenis === "bukti") {
    var r = isi.ringkas || {};
    var g = el("div", "angka-baris");
    [["syslog", isi.syslog_jumlah],
     ["pola baru", (r.pola_baru || []).length],
     ["device", (r.device_ids || []).length]].forEach(function (p) {
      var z = el("span");
      z.appendChild(el("b", null, String(p[1] === undefined ? 0 : p[1])));
      z.appendChild(document.createTextNode(" " + p[0]));
      g.appendChild(z);
    });
    b.appendChild(g);
    if ((r.gagal_dikumpulkan || []).length) {
      // Evidence that failed to be collected is named, not omitted; a silently shortened chain looks complete.
      b.appendChild(el("div", "ket",
        "Tidak bisa dikumpulkan: " + r.gagal_dikumpulkan.join("; ")));
    }
  }

  if (u.insiden_id) {
    var t = el("div", "angka-baris");
    var tautan = el("a", null, "buka insiden #" + u.insiden_id);
    tautan.href = "/insiden/" + u.insiden_id;
    t.appendChild(tautan);
    b.appendChild(t);
  }
  return b;
}

function gambarAgen(d) {
  gambarSaklarAgen(d);

  var wRingkas = document.getElementById("agen-ringkas");
  kosongkan(wRingkas);
  var setuju = d.diusulkan
    ? Math.round(100 * d.diizinkan_pagar / d.diusulkan) + "%"
    : "belum ada";
  wRingkas.appendChild(kartuMini("Tindakan diusulkan", String(d.diusulkan)));
  wRingkas.appendChild(kartuMini("Diizinkan pagar", String(d.diizinkan_pagar),
                                 d.diizinkan_pagar ? "aman" : null));
  wRingkas.appendChild(kartuMini("Ditolak pagar", String(d.ditolak_pagar),
                                 d.ditolak_pagar ? "buruk" : null));
  wRingkas.appendChild(kartuMini("Pagar setuju", setuju));

  var w = document.getElementById("agen-usulan");
  kosongkan(w);
  var us = d.usulan || [];
  if (!us.length) {
    kosong(w, d.aktif
      ? "Belum ada usulan dalam jendela ini. Agen hanya menangani insiden "
        + "yang TERBUKA, dan ia melewati insiden yang sudah pernah ditangani."
      : "Agen mati, jadi belum ada satu pun usulan yang tercatat.");
  } else {
    us.forEach(function (u) { w.appendChild(barisUsulan(u)); });
  }

  var meta = document.getElementById("meta");
  if (meta) meta.textContent = "diperbarui " + jamSaja(new Date());
}


/* ===========================================================================
 * D -- TENANT
 * =========================================================================*/

function gambarTenant(d) {
  var w = document.getElementById("tenant-daftar");
  kosongkan(w);
  var ts = d.tenant || [];
  if (!ts.length) {
    kosong(w, "Belum ada tenant. NSM berjalan tanpa pemisahan penyewa, "
            + "persis seperti sebelum Paket D.");
  } else {
    ts.forEach(function (t) {
      var b = el("div", "wsn-baris " + (t.penuh ? "parah"
                                       : t.aktif ? "aman" : "netral"));
      var atas = el("div", "atas");
      atas.appendChild(el("span", "nama", t.nama));
      atas.appendChild(el("span",
        "lencana " + (t.aktif ? "lencana-up" : "lencana-netral"),
        t.aktif ? "aktif" : "nonaktif"));
      if (t.penuh) {
        atas.appendChild(el("span", "lencana lencana-down", "kuota penuh"));
      }
      if (t.kontak) atas.appendChild(el("span", "kapan", t.kontak));
      b.appendChild(atas);

      var a = el("div", "angka-baris");
      var x = el("span");
      x.appendChild(el("b", null, String(t.device)));
      x.appendChild(document.createTextNode(
        t.kuota_device ? " dari " + t.kuota_device + " device"
                       : " device (tanpa kuota)"));
      a.appendChild(x);
      b.appendChild(a);

      if (t.kuota_device) {
        var bar = el("div", "wsn-bar");
        var isi = el("span");
        var persen = Math.min(100, 100 * t.device / t.kuota_device);
        isi.style.width = persen + "%";
        if (t.penuh) isi.className = "penuh";
        bar.appendChild(isi);
        b.appendChild(bar);
      }
      if (t.catatan) b.appendChild(el("div", "ket", t.catatan));
      w.appendChild(b);
    });
  }

  var wy = document.getElementById("tenant-yatim");
  kosongkan(wy);
  var yatim = d.tanpa_tenant || [];
  if (!yatim.length) {
    kosong(wy, "Tidak ada. Setiap perangkat sudah punya pemilik.");
  } else {
    var b = el("div", "wsn-baris netral");
    b.appendChild(el("div", "nama", yatim.length + " perangkat"));
    b.appendChild(el("div", "ket",
      yatim.map(function (x) { return x.nama; }).join(", ")));
    b.appendChild(el("div", "angka-baris",
      "Mereka terlihat oleh poller, CLI, dan admin platform — tetapi "
      + "tidak oleh tenant mana pun."));
    wy.appendChild(b);
  }
}


/* ===========================================================================
 * Pemilihan halaman
 * =========================================================================*/
(function () {
  var adaBaseline = document.getElementById("baseline");
  var adaAgen = document.getElementById("agen-usulan");
  var adaTenant = document.getElementById("tenant-daftar");

  if (adaBaseline) {
    // Four separate requests, not one: the error budget is much slower (8.5 s for 11 devices), and merging would block everything else on it.
    ambilJson("/api/baseline").then(gambarBaseline)
      .catch(function (e) { tampilGalat(document.getElementById("baseline"), e); });
    ambilJson("/api/pola-log?jam=24").then(gambarPolaLog)
      .catch(function (e) { tampilGalat(document.getElementById("pola-baru"), e); });
    ambilJson("/api/prakiraan").then(gambarPrakiraan)
      .catch(function (e) { tampilGalat(document.getElementById("prakiraan-latency"), e); });
    ambilJson("/api/prakiraan/anggaran").then(gambarAnggaran)
      .catch(function (e) { tampilGalat(document.getElementById("prakiraan-anggaran"), e); });
  } else if (adaAgen) {
    var muat = function () {
      var pilih = document.getElementById("jendela");
      ambilJson("/api/agen-soc?jam=" + (pilih ? pilih.value : "24"))
        .then(gambarAgen)
        .catch(function (e) { tampilGalat(adaAgen, e); });
    };
    var pilih = document.getElementById("jendela");
    if (pilih) pilih.addEventListener("change", muat);
    muat();
    setInterval(muat, 30000);
  } else if (adaTenant) {
    ambilJson("/api/tenant").then(gambarTenant)
      .catch(function (e) { tampilGalat(adaTenant, e); });
  }
})();
