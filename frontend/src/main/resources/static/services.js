/*
 * Services page: whether what runs on top of a device actually serves. All numbers and cause sentences come ready-made from Python (connectors/layanan.py); JavaScript never composes them.
 * Anti-XSS: textContent and createElement only. Refresh is 15 seconds; the poller checks services every 30 seconds.
 */

var periode = (typeof PERIODE_AWAL === "string") ? PERIODE_AWAL : "24h";

/* Which histories are open, stored as a set of ids (not elements) so open panels stay open when the table is redrawn. */
var riwayatTerbuka = {};
var riwayatIsi = {};

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function kosongkan(n) { while (n.firstChild) n.removeChild(n.firstChild); }

function jam(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", {
    day: "2-digit", month: "short", hour: "2-digit",
    minute: "2-digit", second: "2-digit"
  });
}

// Same thresholds as `warnaAvail()` in report.js.
function warnaAvail(n) {
  if (n === null || n === undefined) return "abu";
  if (n >= 100) return "hijau-gelap";
  if (n >= 99) return "hijau";
  if (n >= 95) return "kuning";
  if (n >= 90) return "oranye";
  return "merah";
}

function teksAvail(n) {
  return (n === null || n === undefined) ? "-" : n.toFixed(2) + "%";
}

/* Service address as actually checked (host, port, path), on one line so it can be copied into a browser or curl. */
function alamatLayanan(s) {
  var jenis = s.jenis || "?";
  var dasar = s.ip + ":" + s.port;
  if (jenis === "http" || jenis === "https") {
    return jenis + "://" + dasar + (s.path || "");
  }
  return jenis + " " + dasar;
}

// ---------------------------------------------------------------------------
// Kartu ringkasan
// ---------------------------------------------------------------------------
function kartu(judul, angka, kelas, sub, penjelasan) {
  var c = el("div", "kartu");
  if (penjelasan) c.setAttribute("data-petunjuk", penjelasan);
  c.appendChild(el("div", "judul", judul));
  c.appendChild(el("div", "angka " + (kelas || ""), angka));
  if (sub) c.appendChild(el("div", "sub", sub));
  return c;
}

function gambarKartu(d) {
  var box = document.getElementById("kartu");
  kosongkan(box);

  var aman = d.bermasalah === 0;
  box.appendChild(kartu(
    "Layanan Sehat Sekarang",
    d.sehat + " / " + (d.total - d.dijeda),
    aman ? "hijau" : "merah",
    aman ? "Semua layanan menjawab dengan benar"
         : d.bermasalah + " layanan tidak menjawab dengan benar",
    "Keadaan pemeriksaan TERAKHIR, bukan sepanjang periode. Layanan yang "
    + "sedang dijeda tidak ikut dihitung karena memang tidak diperiksa."
  ));

  // Service availability is averaged here, the only number JavaScript computes on this page; it is a plain mean of finished numbers. Move it to Python if the formula grows.
  var punyaAngka = (d.layanan || []).filter(function (s) {
    return s.aktif && typeof s.availability === "number";
  });
  var rata = punyaAngka.length
    ? punyaAngka.reduce(function (a, s) { return a + s.availability; }, 0) / punyaAngka.length
    : null;
  var ketRata = "Rata-rata semua layanan pada periode ini";
  var jelasRata = "Persentase waktu layanan menjawab dengan benar. Berbeda dari "
    + "availability device: device bisa 100 persen hidup sementara layanannya "
    + "berkali-kali mati, dan justru selisih itulah yang perlu dilihat. Waktu "
    + "ketika NSM berhenti memantau tidak dihitung, tidak sebagai mati maupun "
    + "sebagai hidup.";
  if (d.periode_penuh === false && d.diamati_teks) {
    ketRata = "Baru dipantau " + d.diamati_teks + ", belum "
      + (d.periode_teks || "periode ini") + " penuh";
    jelasRata += " Layanan ini baru mulai diperiksa belakangan, jadi angka di "
      + "atas dihitung dari " + d.diamati_teks + " pemantauan, bukan dari "
      + (d.periode_teks || "periode yang dipilih") + " penuh.";
  }
  var kartuRata = kartu("Availability Layanan", teksAvail(rata), warnaAvail(rata),
    ketRata, jelasRata);
  kartuRata.classList.add("kartu-sorot");
  box.appendChild(kartuRata);

  var totalInsiden = (d.layanan || []).reduce(function (a, s) {
    return a + (s.insiden || 0);
  }, 0);
  box.appendChild(kartu("Gangguan Layanan", String(totalInsiden),
    totalInsiden === 0 ? "hijau" : "kuning", "Pada periode ini",
    "Satu gangguan dihitung sejak layanan berhenti menjawab dengan benar "
    + "sampai ia menjawab benar lagi. Angka ini terpisah dari gangguan device: "
    + "layanan bisa mati berkali-kali tanpa device-nya pernah ikut mati."));

  box.appendChild(kartu("Layanan Dipantau", String(d.total),
    "biru",
    d.dijeda ? d.dijeda + " di antaranya sedang dijeda" : "Semuanya aktif dipantau",
    "Layanan didaftarkan lewat `python set_layanan.py`, bukan lewat halaman "
    + "ini. Menambah layanan berarti menambah baris data, bukan mengubah kode."));
}

function titik(ok, dijeda) {
  var kelas = dijeda ? "titik-tanya"
            : ok === true ? "titik-up"
            : ok === false ? "titik-down" : "titik-tanya";
  return el("span", "titik " + kelas);
}

function barisLayanan(s) {
  var tr = el("tr");
  var dijeda = !s.aktif;

  // --- status ---
  var tdStatus = el("td");
  var isi = el("span", "sel-status");
  isi.appendChild(titik(s.ok, dijeda));
  isi.appendChild(el("b",
    dijeda ? "abu" : s.ok === true ? "hijau" : s.ok === false ? "merah" : "abu",
    dijeda ? "dijeda" : s.ok === true ? "OK"
           : s.ok === false ? "GAGAL" : "belum dicek"));
  if (dijeda) {
    tdStatus.setAttribute("data-petunjuk",
      "Layanan ini sedang dijeda, jadi NSM berhenti memeriksanya dan keadaannya "
      + "sekarang tidak diketahui. Angka pada baris ini berasal dari periode "
      + "sebelum dijeda dan tidak lagi bertambah.");
  }
  tdStatus.appendChild(isi);
  tr.appendChild(tdStatus);

  var tdNama = el("td");
  tdNama.appendChild(el("div", "nama-layanan", s.nama));
  tdNama.appendChild(el("div", "alamat-layanan", alamatLayanan(s)));
  tr.appendChild(tdNama);

  // Owning device, also the link to its history page.
  var tdDev = el("td");
  var keDevice = el("a", null, s.device);
  keDevice.setAttribute("href", "/report/device/" + s.device_id + "?period=" + periode);
  keDevice.setAttribute("title", "Buka riwayat device " + s.device);
  tdDev.appendChild(keDevice);
  tr.appendChild(tdDev);

  tr.appendChild(el("td", "nowrap",
                    (s.jenis || "?").toUpperCase() + " " + s.port));

  // --- availability + bilah ---
  var tdAvail = el("td");
  var bar = el("span", "bilah-nilai");
  var isiBar = el("i");
  var persen = (typeof s.availability === "number") ? s.availability : 0;
  isiBar.style.width = persen + "%";
  var gaya = getComputedStyle(document.documentElement);
  isiBar.style.background = gaya.getPropertyValue(
    persen >= 100 ? "--up-gelap" : persen >= 99 ? "--up"
    : persen >= 95 ? "--hati-hati" : persen >= 90 ? "--waspada"
    : "--down").trim();
  bar.appendChild(isiBar);
  tdAvail.appendChild(bar);
  tdAvail.appendChild(el("span", warnaAvail(s.availability), teksAvail(s.availability)));
  // As in the device table: if there was a span when NSM stopped observing, say how long, since the percentage otherwise includes unobserved hours.
  if (s.tak_terpantau_teks) {
    tdAvail.appendChild(el("div", "catatan-jeda",
      s.tak_terpantau_teks + " tak terpantau"));
    tdAvail.setAttribute("data-petunjuk",
      "NSM tidak memantau device pemilik layanan ini selama "
      + s.tak_terpantau_teks + " pada periode ini (poller mati atau device "
      + "dijeda). Selama itu layanannya juga tidak diperiksa, jadi waktu itu "
      + "dikeluarkan dari hitungan: tidak dianggap mati dan tidak dianggap hidup.");
  }
  // Raw value for sorting (see js/urut.js); the displayed text is a formatted string.
  if (typeof s.availability === "number") tdAvail.dataset.nilai = s.availability;
  tr.appendChild(tdAvail);

  var tdInsiden = el("td", "angka" + (s.insiden > 0 ? " kuning" : ""),
                     String(s.insiden || 0));
  tdInsiden.dataset.nilai = s.insiden || 0;
  tr.appendChild(tdInsiden);

  var tdDown = el("td", "nowrap", s.total_down_teks || "-");
  // Seconds, not text, so "9 menit" sorts below "1 jam 26 menit" correctly.
  tdDown.dataset.nilai = s.total_down_detik || 0;
  tr.appendChild(tdDown);

  // Response time of the last check. Not ping latency: it goes through the whole stack to the application, so it is much larger.
  var tdMs = el("td", "angka nowrap",
    (typeof s.waktu_ms === "number") ? s.waktu_ms.toFixed(2) + " ms" : "-");
  if (typeof s.waktu_ms === "number") tdMs.dataset.nilai = s.waktu_ms;
  tdMs.setAttribute("data-petunjuk",
    "Lama layanan menjawab pemeriksaan terakhir. Berbeda dari latency ping: "
    + "angka ini menempuh seluruh tumpukan sampai ke aplikasinya, jadi wajar "
    + "kalau jauh lebih besar. Yang perlu diperhatikan bukan besarnya, "
    + "melainkan kenaikannya dari hari ke hari.");
  tr.appendChild(tdMs);

  var tdCek = el("td", "nowrap redup");
  if (s.terakhir_cek) {
    tdCek.textContent = waktuRelatif(s.terakhir_cek);
    tdCek.setAttribute("data-petunjuk", waktuLengkap(s.terakhir_cek));
    var t = Date.parse(s.terakhir_cek);
    if (!isNaN(t)) tdCek.dataset.nilai = t;
  } else {
    tdCek.textContent = "-";
  }
  tr.appendChild(tdCek);

  // --- tombol riwayat ---
  var tdAksi = el("td");
  var tombol = el("button", "pil",
    riwayatTerbuka[s.id] ? "Tutup" : (s.insiden > 0 ? "Riwayat (" + s.insiden + ")" : "Riwayat"));
  tombol.addEventListener("click", function () {
    if (riwayatTerbuka[s.id]) {
      delete riwayatTerbuka[s.id];
      gambarTabel(dataTerakhir);
    } else {
      riwayatTerbuka[s.id] = true;
      gambarTabel(dataTerakhir);
      muatRiwayat(s.id);
    }
  });
  tdAksi.appendChild(tombol);
  tr.appendChild(tdAksi);

  return tr;
}

/* Cause row, only for services currently failing. The sentence comes from Python. */
function barisSebab(s, kolom) {
  var tr = el("tr", "baris-sebab");
  var td = el("td", null, s.kategori_teks || "Sebab belum diketahui");
  td.colSpan = kolom;
  tr.appendChild(td);
  return tr;
}

var KOLOM = 10;
var dataTerakhir = null;

function gambarTabel(d) {
  var tb = document.getElementById("baris");
  kosongkan(tb);

  var semua = (d && d.layanan) || [];
  if (!semua.length) {
    var tr = el("tr");
    var td = el("td", "redup",
      "Belum ada layanan terdaftar. Layanan didaftarkan dari CMD dengan "
      + "python set_layanan.py, bukan dari halaman ini.");
    td.colSpan = KOLOM;
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }

  semua.forEach(function (s) {
    tb.appendChild(barisLayanan(s));
    if (s.ok === false && s.aktif) tb.appendChild(barisSebab(s, KOLOM));
    if (riwayatTerbuka[s.id]) tb.appendChild(barisRiwayat(s));
  });
}

function barisRiwayat(s) {
  var tr = el("tr", "baris-riwayat");
  var td = el("td");
  td.colSpan = KOLOM;
  var panel = el("div", "panel-riwayat");
  panel.id = "riwayat-" + s.id;

  var data = riwayatIsi[s.id];
  if (!data) {
    panel.appendChild(el("div", "redup", "Memuat riwayat…"));
  } else if (data.error) {
    panel.appendChild(el("div", "galat merah", data.error));
  } else if (!data.riwayat || !data.riwayat.length) {
    panel.appendChild(el("div", "kosong",
      "Tidak ada gangguan tercatat pada periode ini."));
  } else {
    panel.appendChild(el("h4", null,
      data.riwayat.length + " gangguan pada periode ini (terbaru di atas)"));
    /* Cause sentences repeated across incidents are printed once in a block above the list; sentences that appear only once stay on their card. */
    var hitungSebab = {};
    data.riwayat.forEach(function (r) {
      var t = (r.detail || r.kategori_teks || "").trim();
      if (t) hitungSebab[t] = (hitungSebab[t] || 0) + 1;
    });
    var sebabBersama = Object.keys(hitungSebab).filter(function (t) {
      return hitungSebab[t] > 1;
    });
    if (sebabBersama.length) {
      var ketBersama = el("div", "keterangan-bersama");
      ketBersama.appendChild(el("div", "judul-ket",
        "Sebab yang sama berlaku untuk beberapa gangguan"));
      sebabBersama.forEach(function (t) {
        var b = el("div", "baris-ket");
        b.appendChild(el("span", "cap-jumlah", hitungSebab[t] + "x"));
        b.appendChild(el("span", "isi-ket", t));
        ketBersama.appendChild(b);
      });
      panel.appendChild(ketBersama);
    }

    data.riwayat.forEach(function (r) {
      panel.appendChild(kartuKejadian(r, sebabBersama));
    });
  }

  td.appendChild(panel);
  tr.appendChild(td);
  return tr;
}

function kartuKejadian(r, sebabBersama) {
  var k = el("div", "kejadian");
  k.id = "insiden-svc-" + r.id;

  var waktu = r.berlangsung
    ? jam(r.mulai) + " — belum pulih (" + r.durasi_teks + " berjalan)"
    : jam(r.mulai) + " — " + jam(r.selesai) + "  •  " + r.durasi_teks;
  k.appendChild(el("div", "waktu-kejadian", waktu));

  var lencana = el("span", "lencana " + (r.berlangsung ? "lencana-menunggu" : "lencana-down"),
                   r.berlangsung ? "masih berlangsung" : (r.kategori || "gangguan"));
  k.appendChild(lencana);

  // Cause sentences may contain blank lines between paragraphs; split so they render as paragraphs.
  var sebab = (r.detail || r.kategori_teks || "").trim();
  if (sebabBersama && sebabBersama.indexOf(sebab) >= 0) {
    // Already printed once above the list; marked here so the reader knows the card does have a cause (full text on hover).
    var acuan = el("div", "sebab-kejadian redup", "Sebab: sesuai keterangan di atas");
    acuan.setAttribute("data-petunjuk", sebab);
    k.appendChild(acuan);
  } else {
    sebab.split("\n\n").forEach(function (paragraf) {
      if (paragraf.trim()) k.appendChild(el("div", "sebab-kejadian", paragraf.trim()));
    });
  }

  if (r.bukti && r.bukti.length) {
    var ul = el("ul", "bukti");
    r.bukti.forEach(function (b) {
      ul.appendChild(el("li", b.ok === true ? "ok" : b.ok === false ? "gagal" : "netral",
                        b.teks));
    });
    k.appendChild(ul);
  }

  if (r.saran) {
    var s = el("div", "saran");
    s.appendChild(el("b", null, "Saran: "));
    s.appendChild(document.createTextNode(r.saran));
    k.appendChild(s);
  }

  // Two diagnostic snapshots taken over SSH at the moment of failure and recovery. Collapsed because they can be hundreds of lines, but kept since some figures (service uptime, request counts) are lost once the service restarts.
  if (r.diagnosa_mulai) k.appendChild(lipatan("Diagnosa saat gangguan mulai", r.diagnosa_mulai));
  if (r.diagnosa_pulih) k.appendChild(lipatan("Diagnosa saat pulih", r.diagnosa_pulih));

  return k;
}

function lipatan(judul, isi) {
  var d = el("details", "diagnosa");
  d.appendChild(el("summary", null, judul));
  d.appendChild(el("pre", null, isi));
  return d;
}

function muatRiwayat(id) {
  ambilJson("/api/services/" + id + "/history?period=" + encodeURIComponent(periode))
    .then(function (d) {
      riwayatIsi[id] = d;
      gambarTabel(dataTerakhir);
    })
    .catch(function (e) {
      riwayatIsi[id] = { error: (e && e.sesiHabis) ? e.message
                                                   : "Gagal memuat riwayat layanan" };
      gambarTabel(dataTerakhir);
    });
}

// ---------------------------------------------------------------------------
// Muat data
// ---------------------------------------------------------------------------
function muat() {
  var meta = document.getElementById("meta");
  ambilJson("/api/services?period=" + encodeURIComponent(periode))
    .then(function (d) {
      dataTerakhir = d;
      gambarKartu(d);
      gambarTabel(d);
      meta.textContent = "Diperbarui " + new Date().toLocaleTimeString("id-ID");
    })
    .catch(function (e) {
      meta.textContent = (e && e.sesiHabis) ? e.message : "Gagal memuat layanan";
      if (window.console) console.error("[NSM] gagal memuat layanan:", e);
    });
}

function pasangPeriode() {
  var pil = document.querySelectorAll("#alat .pil[data-p]");
  Array.prototype.forEach.call(pil, function (p) {
    if (p.getAttribute("data-p") === periode) p.classList.add("aktif");
    function pilih() {
      periode = p.getAttribute("data-p");
      Array.prototype.forEach.call(pil, function (q) { q.classList.remove("aktif"); });
      p.classList.add("aktif");
      history.replaceState(null, "", "/services?period=" + periode);
      // Fetched histories belong to the old period and are discarded; open panels stay open and are refilled.
      riwayatIsi = {};
      muat();
      Object.keys(riwayatTerbuka).forEach(function (id) { muatRiwayat(id); });
    }
    p.addEventListener("click", pilih);
    p.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pilih(); }
    });
  });
}

pasangPeriode();
muat();

// Stop refreshing while the tab is hidden and fetch once when it becomes visible again.
setInterval(function () { if (!document.hidden) muat(); }, 15000);
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) muat();
});
