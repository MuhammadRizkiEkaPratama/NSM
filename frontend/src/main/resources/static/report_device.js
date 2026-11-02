/*
 * Per-device history page, split from the report page so many devices do not pile up. Incident history is paginated 5 rows per page via `halaman-tabel.js`.
 * Anti-XSS: all text goes through textContent / createElement.
 */

var periode = (typeof PERIODE_AWAL === "string") ? PERIODE_AWAL : "24h";
var dataTerakhir = null;

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}
/* Scroll wrapper for tables built from JS; without it a wide table pushes the whole page sideways instead of scrolling itself. */
function bungkusTabel(t) {
  var w = el("div", "gulir-tabel");
  w.appendChild(t);
  return w;
}


function jam(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", { day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

/* Section explanations live behind a "?" icon: what a section means is constant, while status messages (for example "no services registered") are the page's answer and stay visible. */
var PENJELASAN_BAGIAN = {
  grafik:
    "Keadaan terkini yang digambar ulang terus-menerus, bukan riwayat. Ping "
    + "dicatat tiap beberapa detik mengikuti irama poller, sedangkan lalu "
    + "lintas jaringan jauh lebih jarang karena harus menanyai perangkat lewat "
    + "SSH atau SNMP. Karena itu kedua grafik mencakup rentang waktu yang "
    + "BERBEDA, dan rentang masing-masing tertulis di sudut kanan bawahnya "
    + "sendiri. Setelah sejumlah titik, grafik dikosongkan dan mulai lagi "
    + "supaya halaman tetap ringan walau dibiarkan terbuka berjam-jam.",
  lalulintas:
    "Masuk = data yang DITERIMA perangkat, Keluar = yang dikirimnya. Angkanya "
    + "bukan dibaca langsung sebagai kecepatan: perangkat hanya menyimpan "
    + "penghitung jumlah byte sejak ia menyala, dan lajunya dihitung dari "
    + "selisih dua pembacaan dibagi selisih waktunya. Sumbernya bisa SNMP atau "
    + "SSH, dan yang dipakai disebutkan di tabelnya — SSH adalah cadangan saat "
    + "SNMP tidak tersedia.",
  layanan:
    "Ping hanya membuktikan MESINNYA menyala. Layanan di atasnya bisa berhenti "
    + "tanpa mengubah hasil ping sama sekali, jadi perangkat hijau dengan "
    + "layanan merah adalah keadaan yang wajar dan bukan salah baca. Tiap "
    + "layanan diperiksa dengan caranya sendiri (TCP, HTTP, atau MySQL), dan "
    + "sebab kegagalannya dikelompokkan supaya bisa dibedakan mana yang "
    + "berarti 'tidak ada yang mendengarkan' dan mana 'dijawab tetapi salah'.",
  traffic:
    "Dua sumber yang menjawab pertanyaan berbeda. Access log web tahu SIAPA "
    + "meminta APA, tetapi hanya untuk HTTP. Flow koneksi TCP tahu semua "
    + "protokol, tetapi tidak tahu berkas apa yang diambil. Keduanya "
    + "ditampilkan berdampingan, bukan digabung jadi satu angka — "
    + "menggabungkannya akan menghasilkan bilangan yang tidak bisa dijelaskan "
    + "artinya oleh siapa pun.",
  riwayat:
    "Hanya PERUBAHAN status yang dicatat di sini, bukan tiap hasil ping. Satu "
    + "baris berarti perangkat berpindah keadaan, dan lamanya gangguan diukur "
    + "sampai ia kembali menjawab. Waktu ketika NSM sendiri berhenti memantau "
    + "(poller dimatikan, atau perangkat sengaja dijeda) TIDAK dihitung "
    + "sebagai waktu mati — kalau dihitung, mematikan alat pemantaunya akan "
    + "terlihat seperti jaringan yang rusak."
};

/* Attach the "?" icon to each section title once. The title has `data-lipat` (click to collapse), so the icon stops its own click (handled in `jelas.js`). */
function pasangPenjelasanBagian() {
  if (!window.jelas || !window.jelas.pasang) return;
  Object.keys(PENJELASAN_BAGIAN).forEach(function (kunci) {
    var judul = document.querySelector('h2[data-lipat="' + kunci + '"]');
    if (!judul || judul.dataset.adaJelas) return;
    judul.dataset.adaJelas = "1";
    judul.classList.add("kepala");
    // The panel goes after the title, not inside it, so opening it does not change the title height.
    var panel = window.jelas.pasang(judul, PENJELASAN_BAGIAN[kunci],
                                    judul.parentNode);
    if (panel && judul.nextSibling) {
      judul.parentNode.insertBefore(panel, judul.nextSibling);
    }
  });
}

// ---------------------------------------------------------------------------
// Identitas device
// ---------------------------------------------------------------------------
function gambarKepala(d, dipantauSejak) {
  var judul = document.getElementById("nama");
  judul.innerHTML = "";
  var kotak = el("span", "bungkus-ikon");
  kotak.style.display = "inline-block";
  kotak.style.verticalAlign = "middle";
  kotak.style.marginRight = "12px";
  kotak.appendChild(ikonDevice(jenisIkon(d), d.is_reachable, 42));
  judul.appendChild(kotak);
  judul.appendChild(el("span", null, d.name));

  var rinci = document.getElementById("rinci");
  rinci.innerHTML = "";

  var status = el("div");
  var kelasTitik = d.is_reachable === true ? "titik-up"
                 : d.is_reachable === false ? "titik-down" : "titik-tanya";
  status.appendChild(el("span", "titik " + kelasTitik));
  status.appendChild(el("b", d.is_reachable === true ? "hijau"
                          : d.is_reachable === false ? "merah" : "abu",
                        d.is_reachable === true ? "UP"
                        : d.is_reachable === false ? "DOWN" : "Belum ada data"));
  if (d.is_reachable && d.response_time_ms !== null) {
    status.appendChild(el("span", null, "  •  " + d.response_time_ms + " ms"));
  }
  if (d.last_checked) {
    status.appendChild(el("span", null, "  •  cek terakhir " + d.last_checked.substring(11, 19)));
  }
  rinci.appendChild(status);

  /* Identity as a single row of chips, each with a small label above its value; long explanations move to hover (`data-petunjuk`). */
  var keping = el("div", "keping-identitas");

  function kep(label, nilai, petunjuk) {
    var k = el("div", "keping");
    k.appendChild(el("span", "keping-label", label));
    k.appendChild(el("span", "keping-nilai", nilai));
    if (petunjuk) k.setAttribute("data-petunjuk", petunjuk);
    keping.appendChild(k);
  }

  kep("Alamat", d.ip_address || "-",
      "Alamat IP yang dipakai NSM untuk memeriksa perangkat ini. Semua ping, "
      + "SSH, dan pemeriksaan layanan ditujukan ke sini.");
  kep("Jenis", d.device_type || "-",
      "Menentukan bentuk ikonnya dan cara NSM memperlakukannya, bukan sekadar "
      + "label.");
  kep("Lokasi", d.location || "-",
      "Dipakai mengelompokkan perangkat di peta topologi Dashboard. Perangkat "
      + "satu lokasi digambar pada lajur yang sama.");
  kep("Platform", d.platform || "belum diisi",
      d.platform
        ? "Menentukan perintah apa yang dipakai saat mengambil data lewat SSH "
          + "— Linux dan Cisco IOS menjawab pertanyaan yang sama dengan "
          + "perintah yang sama sekali berbeda."
        : "Belum diisi, jadi tombol pengambilan detail tidak tersedia: NSM "
          + "tidak tahu perintah mana yang akan dimengerti perangkat ini.");
  if (dipantauSejak) {
    kep("Dipantau sejak", jam(dipantauSejak),
        "Sampel pertama yang tercatat untuk perangkat ini. Availability yang "
        + "dihitung untuk periode yang lebih panjang daripada ini tidak akan "
        + "pernah penuh, dan kartunya menyebutkan itu sendiri.");
  }
  rinci.appendChild(keping);

  var aksi = document.getElementById("aksi");
  aksi.innerHTML = "";
  if (d.platform && d.is_reachable) {
    // Name the path actually used. "Local" devices are read directly from this machine, without SSH.
    var b = el("button", "utama", d.platform === "lokal"
      ? "Ambil Detail Langsung" : "Ambil Detail via SSH");
    b.addEventListener("click", function () { lihatDetail(d.id); });
    aksi.appendChild(b);
  }
}

// ---------------------------------------------------------------------------
// Kartu ringkasan device
// ---------------------------------------------------------------------------
function kartu(judul, angka, kelas, sub, istilah) {
  var c = el("div", "kartu");
  if (istilah) jelaskan(c, istilah);
  c.appendChild(el("div", "judul", judul));
  c.appendChild(el("div", "angka " + (kelas || ""), angka));
  if (sub && sub.ringkas) c.appendChild(subKartu(sub.ringkas, sub.penuh));
  else if (sub) c.appendChild(el("div", "sub", sub));
  return c;
}

/* One icon from the `/ikon-tabler.svg` sprite. Built with createElementNS: elements made with createElement would be in the HTML namespace and never render. */
var SVG_NS = "http://www.w3.org/2000/svg";
var XLINK = "http://www.w3.org/1999/xlink";

function ikonUI(nama, kelas) {
  var svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "ikon" + (kelas ? " " + kelas : ""));
  svg.setAttribute("aria-hidden", "true");
  var use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", "/ikon-tabler.svg#i-" + nama);
  // `xlink:href` for old browsers; harmless in new ones.
  use.setAttributeNS(XLINK, "xlink:href", "/ikon-tabler.svg#i-" + nama);
  svg.appendChild(use);
  return svg;
}

/* Availability ring. A ring instead of a bar because the value is nearly always close to 100, where bars of 99.4% and 100% look identical but a ring with a small gap does not. */
function cincinAvail(nilai, kelas) {
  var KELILING = 251.3;               // 2 * pi * 40
  var bungkus = el("div", "cincin");
  var svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", "96");
  svg.setAttribute("height", "96");
  svg.setAttribute("viewBox", "0 0 96 96");

  function lingkaran(warna, offset) {
    var c = document.createElementNS(SVG_NS, "circle");
    c.setAttribute("cx", "48"); c.setAttribute("cy", "48"); c.setAttribute("r", "40");
    c.setAttribute("fill", "none"); c.setAttribute("stroke", warna);
    c.setAttribute("stroke-width", "9");
    if (offset !== undefined) {
      c.setAttribute("stroke-linecap", "round");
      c.setAttribute("stroke-dasharray", String(KELILING));
      c.setAttribute("stroke-dashoffset", String(offset));
    }
    return c;
  }

  var WARNA = { "hijau-gelap": "var(--up-gelap)", hijau: "var(--up)",
                kuning: "var(--hati-hati)", oranye: "var(--waspada)",
                merah: "var(--down)", abu: "var(--tak-diketahui)" };
  svg.appendChild(lingkaran("var(--permukaan-3)"));
  if (nilai !== null && nilai !== undefined) {
    svg.appendChild(lingkaran(WARNA[kelas] || WARNA.abu,
                              KELILING * (1 - Math.max(0, Math.min(100, nilai)) / 100)));
  }
  bungkus.appendChild(svg);

  var tengah = el("div", "tengah");
  var nilaiEl = el("span", "nilai");
  if (nilai === null || nilai === undefined) {
    nilaiEl.textContent = "-";
  } else {
    nilaiEl.appendChild(document.createTextNode(nilai.toFixed(2)));
    var persen = el("span", null, "%");
    persen.style.fontSize = "13px";
    nilaiEl.appendChild(persen);
  }
  tengah.appendChild(nilaiEl);
  tengah.appendChild(el("span", "kata", "tersedia"));
  bungkus.appendChild(tengah);
  return bungkus;
}

/* Summary as a single tile rather than five cards, since availability, incidents, total down time, and recovery time all answer one question. Latency is included too. The coverage notes ("not a full period", "unobserved") stay visible because they decide whether the numbers can be trusted. */
/* Blast radius: "if this device goes down, who else goes dark", computed by `ketergantungan.hilir()`. `pasti` is distinguished from the count: radius 0 on an incomplete graph means NSM does not know, not that it is safe. */
function gambarDampakHilir(dh) {
  var rinci = document.getElementById("rinci");
  if (!rinci || !dh) return;

  var baris = el("div", "dampak-hilir");
  baris.style.marginTop = "6px";

  if (dh.jumlah === null || dh.jumlah === undefined) {
    baris.appendChild(el("span", "redup",
      "Radius dampak tidak bisa dihitung."));
    rinci.appendChild(baris);
    return;
  }

  if (!dh.pasti) {
    baris.appendChild(el("span", "redup",
      "Radius dampak TIDAK BISA DIPASTIKAN — "
      + (dh.tak_terjangkau && dh.tak_terjangkau.length
         ? dh.tak_terjangkau.length + " perangkat belum punya jalur tercatat"
         : "graf jalur belum lengkap")
      + ". Ini bukan berarti aman; berarti NSM belum tahu."));
    rinci.appendChild(baris);
    return;
  }

  if (dh.jumlah === 0) {
    baris.appendChild(el("span", "redup",
      "Tidak ada perangkat lain yang jalurnya melewati perangkat ini."));
    rinci.appendChild(baris);
    return;
  }

  var kuat = el("b", null, dh.jumlah + " perangkat lain");
  baris.appendChild(document.createTextNode("Kalau perangkat ini jatuh, "));
  baris.appendChild(kuat);
  baris.appendChild(document.createTextNode(
    " ikut kehilangan jalur dari NSM: "
    + (dh.daftar || []).map(function (x) { return x.nama; }).join(", ") + "."));
  rinci.appendChild(baris);
}

function gambarRingkas(data) {
  var r = data.ringkasan;
  var box = document.getElementById("ringkas");
  box.innerHTML = "";

  // Say so plainly when the period is not fully covered: 85% of 40 minutes differs from 85% of 24 hours.
  var ketAvail = data.periode_penuh
    ? null
    : "Baru dipantau " + (r.durasi_diamati_teks || "-")
      + ", belum " + data.periode_teks + " penuh";

  // Time when NSM stopped observing this device (poller off or device paused) is excluded from the calculation, and this is stated.
  if (r.tak_terpantau_teks) {
    ketAvail = (ketAvail ? ketAvail + ". " : "")
      + r.tak_terpantau_teks + " tidak terpantau, tidak ikut dihitung";
  }

  box.appendChild(cincinAvail(r.availability, warnaAvail(r.availability)));

  /* Four companion numbers. Abbreviations are replaced by sentences for non-network readers; the old glossary keys stay attached. */
  var daftar = el("div", "mini-daftar");

  function mini(ikon, label, nilai, kelas, istilah) {
    var baris = el("div", "mini");
    var lab = el("span", "lab");
    lab.appendChild(ikonUI(ikon));
    lab.appendChild(document.createTextNode(label));
    if (istilah) jelaskan(lab, istilah);
    baris.appendChild(lab);
    baris.appendChild(el("span", "val " + (kelas || ""), nilai));
    daftar.appendChild(baris);
  }

  mini("alert-triangle", "Insiden", String(r.insiden),
       r.insiden > 0 ? "kuning" : "", "insiden");
  mini("wifi-off", "Total mati", r.total_down_teks || "-", null, "total-down");
  // The MTTR text comes ready-made from Python so wording matches the Report page.
  mini("history", "Rata-rata pulih", r.mttr_teks || "-", null, "mttr");
  mini("zap", "Balasan ping",
       data.avg_latency_ms === null || data.avg_latency_ms === undefined
         ? "-" : data.avg_latency_ms + " ms", "biru", "latency");

  box.appendChild(daftar);

  /* Coverage note, outside the number box and always visible: 100% from three hours differs in strength from 100% over 24 hours. */
  var kabar = document.getElementById("kesehatan-periode");
  if (kabar) kabar.textContent = data.periode_teks || "";

  /* Remove the old note first. The page redraws every 10 seconds and `box.innerHTML = ""` clears only #ringkas, not this sibling, so copies would pile up. */
  var lama = box.parentNode.querySelector(".catatan-ubin");
  if (lama) lama.parentNode.removeChild(lama);

  if (ketAvail) {
    var ket = el("div", "catatan-ubin");
    ket.appendChild(ikonUI("clock"));
    ket.appendChild(document.createTextNode(" " + ketAvail + "."));
    box.parentNode.insertBefore(ket, box.nextSibling);
  }
}

// ---------------------------------------------------------------------------
// Ringkasan kepala panel
// ---------------------------------------------------------------------------
/* Summary written into a collapsible panel header, so a closed panel still gives its answer. */
function ringkasPanel(kunci, teks, kelas) {
  if (window.NSMLipat) window.NSMLipat.ringkas(kunci, teks, kelas);
}

// ---------------------------------------------------------------------------
// Daftar riwayat (bertahap)
// ---------------------------------------------------------------------------
function gambarRiwayat(data) {
  var daftar = document.getElementById("daftar");
  var lagi = document.getElementById("lagi");
  var hitungan = document.getElementById("hitungan");
  daftar.innerHTML = "";
  lagi.innerHTML = "";

  var semua = data.riwayat || [];
  if (semua.length === 0) {
    hitungan.textContent = "";
    var pesan = "Tidak ada gangguan tercatat pada periode ini.";
    if (data.dipantau_sejak) pesan += " Device dipantau sejak " + jam(data.dipantau_sejak) + ".";
    daftar.appendChild(el("div", "kosong", pesan));
    ringkasPanel("riwayat", "tidak ada gangguan", "baik");
    return;
  }

  hitungan.textContent = semua.length + " gangguan pada periode ini (terbaru di atas).";
  ringkasPanel("riwayat", semua.length + " gangguan",
               semua.length > 0 ? "hati" : "baik");

  var tabel = el("table");
  var thead = el("thead");
  var trh = el("tr");
  [["#", null], ["Mulai Down", null], ["Pulih", null],
   ["Lama Gangguan", "insiden"], ["Kategori", "tidak-ada-respons"],
   ["Keterangan", null]]
    .forEach(function (j) {
      var th = el("th", null, j[0]);
      if (j[1]) jelaskan(th, j[1]);
      trh.appendChild(th);
    });
  thead.appendChild(trh);
  tabel.appendChild(thead);

  /* Identical explanation sentences are not repeated: those appearing more than once go into one note below the table and cells just refer to it; sentences that appear once stay in their cell. */
  var hitungDetail = {};
  semua.forEach(function (r) {
    var t = (r.detail || "").trim();
    if (t) hitungDetail[t] = (hitungDetail[t] || 0) + 1;
  });

  var tbody = el("tbody");
  semua.forEach(function (r, i) {
    var kelas = r.berlangsung ? "berlangsung" : (r.kategori || "");
    var tr = el("tr", kelas);
    // Row address, so incident cards on the Report page can link to the exact incident.
    if (r.event_id) tr.id = "insiden-" + r.event_id;

    tr.appendChild(el("td", "no", String(i + 1)));
    tr.appendChild(el("td", "waktu", jam(r.mulai)));
    tr.appendChild(el("td", "waktu", r.berlangsung ? "belum pulih" : jam(r.selesai)));

    // The Duration column counts only observed time, so the Start-to-Recovery span can exceed it when NSM was not monitoring.
    var tdLama = el("td", "lama",
      r.berlangsung ? r.durasi_teks + " (berjalan)" : r.durasi_teks);
    if (r.jeda_teks) {
      tdLama.appendChild(el("div", "catatan-jeda",
        "+ " + r.jeda_teks + " tidak terpantau"));
      tdLama.title = "NSM tidak memantau device ini selama " + r.jeda_teks
        + " di tengah gangguan (poller mati atau device dijeda). "
        + "Waktu itu tidak dihitung sebagai waktu mati.";
    }
    tr.appendChild(tdLama);

    var tdKat = el("td");
    tdKat.appendChild(el("span", "lencana " + kelas,
      r.berlangsung ? "masih berlangsung"
      : r.kategori === "dead" ? "tidak ada respons"
      : r.kategori === "ping_blocked" ? "ping diblokir" : (r.kategori || "-")));
    tr.appendChild(tdKat);

    var teksDetail = (r.detail || "").trim();
    if (teksDetail && hitungDetail[teksDetail] > 1) {
      var tdSama = el("td", "sebab redup", "sesuai keterangan di bawah");
      tdSama.setAttribute("data-petunjuk", teksDetail);
      tr.appendChild(tdSama);
    } else {
      tr.appendChild(el("td", "sebab", teksDetail || "-"));
    }
    tbody.appendChild(tr);
  });
  tabel.appendChild(tbody);
  daftar.appendChild(bungkusTabel(tabel));
  // 5 rows per page, newest first (sorted above). `lagi` is unused but left empty in the HTML.
  if (window.halamanTabel) halamanTabel.pasang(tabel, { perHal: 5 });

  var berulang = Object.keys(hitungDetail).filter(function (t) {
    return hitungDetail[t] > 1;
  });
  if (berulang.length) {
    var ket = el("div", "keterangan-bersama");
    ket.appendChild(el("div", "judul-ket",
      "Keterangan yang berlaku untuk beberapa baris sekaligus"));
    berulang.forEach(function (t) {
      var b = el("div", "baris-ket");
      b.appendChild(el("span", "cap-jumlah", hitungDetail[t] + "x"));
      b.appendChild(el("span", "isi-ket", t));
      ket.appendChild(b);
    });
    daftar.appendChild(ket);
  }
}

// Live chart. Old data is fetched once on page open; after that each refresh only appends a point from data the page already fetched, with no extra requests. When the point limit is reached the chart resets from the left.
// The chart refreshes every 5 seconds, matching the poller's ping write interval; a point is added only when the data timestamp changes.
var JEDA_GRAFIK = 5000;
var MAKS_TITIK = 60;               // 60 titik x 5 detik = 5 menit per putaran
var grafikPing = null;
var grafikBw = null;
var ifaceGrafik = [];
var waktuPingTerakhir = null;
var waktuBwTerakhir = null;
var sudahIsiAwal = false;

var WARNA = ["#4ade80", "#60a5fa", "#facc15", "#f472b6", "#fb923c", "#a78bfa"];

function formatMs(v) {
  if (v >= 100) return v.toFixed(0) + " ms";
  if (v >= 10) return v.toFixed(1) + " ms";
  return v.toFixed(2) + " ms";
}

/* One unit across the app: Mbps, three decimals, so columns compare by eye. Small traffic reads 0.000, so the raw value is always sent from Python and shown on hover. The Python counterpart is `report_service.format_bps` and the two must match. */
function formatBps(v) {
  if (v === null || v === undefined) return "-";
  return (v / 1000000).toFixed(3) + " Mbps";
}

function siapkanGrafik(namaIface) {
  grafikPing = new Grafik(document.getElementById("grafik-ping"), {
    seri: [{ nama: "Ping", warna: "#60a5fa" }],
    maksTitik: MAKS_TITIK,
    format: formatMs,
    kosongPesan: "Menunggu hasil ping…",
  });

  var seri = [];
  ifaceGrafik = namaIface.slice(0, 3);
  ifaceGrafik.forEach(function (nm, i) {
    seri.push({ nama: nm + " masuk", warna: WARNA[(i * 2) % WARNA.length] });
    seri.push({ nama: nm + " keluar", warna: WARNA[(i * 2 + 1) % WARNA.length] });
  });
  if (seri.length === 0) seri.push({ nama: "Lalu lintas", warna: "#4ade80" });

  grafikBw = new Grafik(document.getElementById("grafik-bw"), {
    seri: seri,
    maksTitik: MAKS_TITIK,
    format: formatBps,
    kosongPesan: "Belum ada data lalu lintas",
  });
}

async function isiGrafikAwal() {
  try {
    var r = await fetch("/api/devices/" + DEVICE_ID + "/chart?points=" + MAKS_TITIK);
    var d = await r.json();
    if (d.error) return;

    var namaIface = Object.keys(d.bandwidth || {}).sort();
    siapkanGrafik(namaIface);

    // ping
    if (d.ping && d.ping.length) {
      grafikPing.isiAwal([d.ping.map(function (p) { return p.ms; })],
                         d.ping.map(function (p) { return p.t; }));
      waktuPingTerakhir = d.ping[d.ping.length - 1].t;
    }

    // bandwidth: all interfaces use the time series of the first interface
    if (ifaceGrafik.length) {
      var acuan = d.bandwidth[ifaceGrafik[0]] || [];
      var nilai = [];
      ifaceGrafik.forEach(function (nm) {
        var baris = d.bandwidth[nm] || [];
        nilai.push(baris.map(function (b) { return b["in"]; }));
        nilai.push(baris.map(function (b) { return b["out"]; }));
      });
      if (acuan.length) {
        grafikBw.isiAwal(nilai, acuan.map(function (b) { return b.t; }));
        waktuBwTerakhir = acuan[acuan.length - 1].t;
      }
    }
    sudahIsiAwal = true;
    tulisKeteranganGrafik();
  } catch (e) {
    // A chart that fails to load must not take down the rest of the page
    if (!grafikPing) siapkanGrafik([]);
  }
}

function tulisKeteranganGrafik() {
  var panel = document.querySelector(".grafik-a .judul-grafik + .jelas-isi");
  if (panel && !panel.dataset.berangka) {
    panel.dataset.berangka = "1";
    panel.textContent = panel.textContent.replace(
      "tiap beberapa detik", "tiap " + (JEDA_GRAFIK / 1000) + " detik")
      .replace("sejumlah titik", MAKS_TITIK + " titik");
  }

  /* Two charts side by side with different time axes (ping spans minutes, traffic up to half an hour). The span is therefore put in each chart's title, and each chart has a different border color so they are not read as comparable. */
  perbaruiJudulGrafik();
}

/* Chart titles with their own time span, refreshed on every tick as the span grows. */
function perbaruiJudulGrafik() {
  [["grafik-ping", "Ping", "grafik-a", "activity"],
   ["grafik-bw", "Lalu lintas", "grafik-b", "network"]].forEach(function (g) {
    var kanvas = document.getElementById(g[0]);
    if (!kanvas || !kanvas.parentNode) return;
    var kotak = kanvas.parentNode;
    var judul = kotak.querySelector(".judul-grafik");
    if (!judul) {
      judul = document.createElement("div");
      judul.className = "judul-grafik";
      // Icon and text are separate children, because the tick rewrites the title and `textContent` on the parent would erase the icon.
      judul.appendChild(ikonUI(g[3]));
      judul.appendChild(el("span", "teks-judul-grafik"));
      kotak.insertBefore(judul, kanvas);
      kotak.classList.add(g[2]);
    }
    // The span is computed and attached by grafik.js; read from there instead of recomputing.
    var rentang = kanvas.dataset.rentang || "";
    var teks = judul.querySelector(".teks-judul-grafik");
    if (teks) teks.textContent = g[1] + (rentang ? "  ·  " + rentang : "");
  });

  /* The chart's "?" explanation attaches to the ping chart title, because that element only exists after the first chart tick. */
  var judulPing = document.querySelector(".grafik-a .judul-grafik");
  if (judulPing && !judulPing.dataset.adaJelas
      && window.jelas && window.jelas.pasang) {
    judulPing.dataset.adaJelas = "1";
    judulPing.classList.add("kepala");
    var panel = window.jelas.pasang(judulPing, PENJELASAN_BAGIAN.grafik,
                                    judulPing.parentNode);
    if (panel) judulPing.parentNode.insertBefore(panel, judulPing.nextSibling);
  }

}

/* Chart tick: fetch the latest point and append it only if the data is new. */
async function denyutGrafik() {
  if (!grafikPing || !grafikBw) return;
  try {
    var r = await fetch("/api/devices/" + DEVICE_ID + "/latest");
    var d = await r.json();

    // --- ping ---
    if (d.ping && d.ping.t && d.ping.t !== waktuPingTerakhir) {
      waktuPingTerakhir = d.ping.t;
      // null when the device does not answer: the line is deliberately broken, not dropped to 0
      var ms = (typeof d.ping.ms === "number") ? d.ping.ms : null;
      grafikPing.tambah([ms], d.ping.t);
    }

    // --- bandwidth ---
    if (ifaceGrafik.length && d.bandwidth) {
      // Reference time is the newest across all interfaces, so the chart does not freeze if one interface stops reporting (for example partial SNMP replies).
      var waktuBaru = null;
      ifaceGrafik.forEach(function (nm) {
        var b = d.bandwidth[nm];
        if (b && b.t && (waktuBaru === null || b.t > waktuBaru)) waktuBaru = b.t;
      });
      if (waktuBaru && waktuBaru !== waktuBwTerakhir) {
        waktuBwTerakhir = waktuBaru;
        var acuan = { t: waktuBaru };
        var nilai = [];
        ifaceGrafik.forEach(function (nm) {
          var b = d.bandwidth[nm];
          nilai.push(b ? b["in"] : null);
          nilai.push(b ? b["out"] : null);
        });
        grafikBw.tambah(nilai, acuan.t);
      }
    }
    // The chart titles are updated here because each span grows with new points.
    perbaruiJudulGrafik();
  } catch (e) {
    // A failed tick is skipped; the next attempt is 5 seconds later.
  }
}

function gambarBandwidth(b) {
  var box = document.getElementById("bw");
  var ket = document.getElementById("bw-ket");
  box.innerHTML = "";
  ket.textContent = "";

  if (!b.didukung) {
    ket.textContent = b.alasan || "";
    // Also hide the chart canvas, not just the table, so an empty chart does not contradict the note that the data will never exist.
    var kanvas = document.getElementById("grafik-bw");
    if (kanvas && kanvas.parentNode) kanvas.parentNode.style.display = "none";
    ringkasPanel("lalulintas", "tidak ada jalur baca");
    return;
  }
  if (!b.interfaces || b.interfaces.length === 0) {
    ket.textContent = "Belum ada data. Poller membaca lalu lintas tiap 30 detik, "
                    + "dan pembacaan PERTAMA hanya jadi titik acuan, sehingga angka "
                    + "muncul pada pembacaan kedua.";
    ringkasPanel("lalulintas", "belum ada sampel");
    return;
  }

  ket.textContent = b.total_sampel + " sampel pada periode ini.";
  ket.className = "kabar-data";
  ringkasPanel("lalulintas", b.interfaces.length + " interface terbaca");

  var tabel = el("table");
  var thead = el("thead");
  var trh = el("tr");
  [["Interface", "interface"], ["Masuk (kini)", "bps"], ["Keluar (kini)", "bps"],
   ["Masuk rata-rata", null], ["Keluar rata-rata", null],
   ["Masuk puncak", null], ["Keluar puncak", null],
   ["Sumber", "sumber-bacaan"], ["Terakhir", null]]
    .forEach(function (j) {
      var th = el("th", null, j[0]);
      if (j[1]) jelaskan(th, j[1]);
      trh.appendChild(th);
    });
  thead.appendChild(trh);
  tabel.appendChild(thead);

  var tbody = el("tbody");
  b.interfaces.forEach(function (i) {
    var tr = el("tr");
    // Interface names are the most-asked term, so the explanation is attached to each cell.
    var tdIface = el("td", "iface", i.iface);
    jelaskan(tdIface, "interface");
    tr.appendChild(tdIface);
    // Mbps in the cell, raw value as hover title, so the single unit does not lose information.
    function sel(teks, asli) {
      var td = el("td", "laju", teks);
      if (asli) td.setAttribute("data-petunjuk", "Nilai asli: " + asli);
      return td;
    }
    tr.appendChild(sel(i.in_teks, i.in_asli));
    tr.appendChild(sel(i.out_teks, i.out_asli));
    tr.appendChild(sel(i.in_rata_teks, i.in_rata_asli));
    tr.appendChild(sel(i.out_rata_teks, i.out_rata_asli));
    tr.appendChild(sel(i.in_puncak_teks, i.in_puncak_asli));
    tr.appendChild(sel(i.out_puncak_teks, i.out_puncak_asli));

    /* Which path the number was read from (SNMP or SSH). Without this column a dead snmpd silently falls back to SSH with correct numbers and nothing visible on screen. */
    var tdSumber = el("td");
    if (i.source) {
      // SSH is marked as the fallback since SNMP is the primary path; SSH on a device with SNMP credentials means SNMP is silent.
      var cadangan = i.source === "ssh";
      var pil = el("span", "sumber" + (cadangan ? " cadangan" : ""), i.source);
      pil.setAttribute("data-petunjuk", cadangan
        ? "Dibaca lewat SSH, yaitu jalur CADANGAN. NSM memakainya otomatis "
          + "saat SNMP tidak menjawab, jadi angkanya tetap benar, tetapi snmpd "
          + "di device ini kemungkinan mati dan perlu diperiksa."
        : i.source === "lokal"
          ? "Dibaca langsung dari mesin yang menjalankan NSM sendiri, tanpa "
            + "membuka koneksi jaringan apa pun ke mana pun."
          : "Dibaca lewat SNMP, jalur utama dan paling murah bagi device.");
      tdSumber.appendChild(pil);
    } else {
      tdSumber.className = "redup";
      tdSumber.textContent = "-";
    }
    tr.appendChild(tdSumber);

    tr.appendChild(el("td", "waktu",
      i.terakhir ? i.terakhir.substring(11, 19) : "-"));
    tbody.appendChild(tr);
  });
  tabel.appendChild(tbody);
  box.appendChild(bungkusTabel(tabel));
}

// Services of this device. A device can be 100% up while the services on it fail repeatedly. Cause sentences come ready-made from Python.
var svcTerbuka = {};        // id layanan -> sedang dibuka riwayatnya
var svcRiwayat = {};
var dataLayanan = null;
var KOLOM_SVC = 7;

function alamatLayanan(s) {
  var jenis = s.jenis || "?";
  var dasar = s.ip + ":" + s.port;
  if (jenis === "http" || jenis === "https") {
    return jenis + "://" + dasar + (s.path || "");
  }
  return jenis + " " + dasar;
}

function gambarLayanan(d) {
  dataLayanan = d;
  var box = document.getElementById("layanan");
  var ket = document.getElementById("layanan-ket");
  box.innerHTML = "";
  ket.textContent = "";

  var semua = (d && d.layanan) || [];
  if (!semua.length) {
    ket.textContent = "Device ini belum punya layanan terdaftar, jadi NSM hanya "
      + "tahu mesinnya hidup atau tidak, bukan apakah yang berjalan di atasnya "
      + "melayani. Layanan didaftarkan dari CMD dengan python set_layanan.py.";
    ringkasPanel("layanan", "belum ada layanan terdaftar");
    return;
  }

  var bermasalah = semua.filter(function (s) { return s.aktif && s.ok === false; });
  ket.textContent = bermasalah.length
    ? bermasalah.length + " dari " + semua.length + " layanan sedang tidak "
      + "menjawab dengan benar. Perhatikan: kartu device bisa tetap hijau dan "
      + "itu tidak keliru, ping memang berhasil."
    : semua.length + " layanan dipantau, semuanya menjawab dengan benar pada "
      + "pemeriksaan terakhir.";
  ringkasPanel("layanan",
    bermasalah.length
      ? bermasalah.length + " dari " + semua.length + " bermasalah"
      : semua.length + " dari " + semua.length + " sehat",
    bermasalah.length ? "buruk" : "baik");

  var tabel = el("table");
  var thead = el("thead");
  var trh = el("tr");
  [["Status", null], ["Layanan", null], ["Jenis", "lapis-layanan"],
   ["Availability", "availability"], ["Insiden", "insiden"],
   ["Total Down", "total-down"], ["", null]].forEach(function (j) {
    var th = el("th", null, j[0]);
    if (j[1]) jelaskan(th, j[1]);
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  tabel.appendChild(thead);

  var tbody = el("tbody");
  semua.forEach(function (s) {
    var tr = el("tr");
    var dijeda = !s.aktif;

    var tdStatus = el("td");
    var isi = el("span", "sel-status");
    isi.appendChild(el("span", "titik " + (dijeda ? "titik-tanya"
      : s.ok === true ? "titik-up" : s.ok === false ? "titik-down" : "titik-tanya")));
    isi.appendChild(el("b",
      dijeda ? "abu" : s.ok === true ? "hijau" : s.ok === false ? "merah" : "abu",
      dijeda ? "dijeda" : s.ok === true ? "OK"
             : s.ok === false ? "GAGAL" : "belum dicek"));
    tdStatus.appendChild(isi);
    tr.appendChild(tdStatus);

    var tdNama = el("td");
    tdNama.appendChild(el("div", "nama-layanan", s.nama));
    tdNama.appendChild(el("div", "alamat-layanan", alamatLayanan(s)));
    tr.appendChild(tdNama);

    tr.appendChild(el("td", "nowrap", (s.jenis || "?").toUpperCase() + " " + s.port));
    tr.appendChild(el("td", warnaAvail(s.availability),
      (typeof s.availability === "number") ? s.availability.toFixed(2) + "%" : "-"));
    tr.appendChild(el("td", s.insiden > 0 ? "kuning" : "", String(s.insiden || 0)));
    tr.appendChild(el("td", "nowrap", s.total_down_teks || "-"));

    var tdAksi = el("td");
    var tombol = el("button", "pil", svcTerbuka[s.id] ? "Tutup" : "Riwayat");
    tombol.addEventListener("click", function () {
      if (svcTerbuka[s.id]) delete svcTerbuka[s.id];
      else { svcTerbuka[s.id] = true; muatRiwayatLayanan(s.id); }
      gambarLayanan(dataLayanan);
    });
    tdAksi.appendChild(tombol);
    tr.appendChild(tdAksi);
    tbody.appendChild(tr);

    if (s.ok === false && s.aktif && s.kategori_teks) {
      var trSebab = el("tr", "baris-sebab");
      var tdSebab = el("td", null, s.kategori_teks);
      tdSebab.colSpan = KOLOM_SVC;
      trSebab.appendChild(tdSebab);
      tbody.appendChild(trSebab);
    }

    if (svcTerbuka[s.id]) tbody.appendChild(barisRiwayatLayanan(s));
  });
  tabel.appendChild(tbody);
  box.appendChild(bungkusTabel(tabel));
}

function barisRiwayatLayanan(s) {
  var tr = el("tr", "baris-riwayat");
  var td = el("td");
  td.colSpan = KOLOM_SVC;
  var panel = el("div", "panel-riwayat");

  var data = svcRiwayat[s.id];
  if (!data) {
    panel.appendChild(el("div", "redup", "Memuat riwayat layanan…"));
  } else if (data.error) {
    panel.appendChild(el("div", "merah", data.error));
  } else if (!data.riwayat || !data.riwayat.length) {
    panel.appendChild(el("div", "kosong",
      "Tidak ada gangguan layanan tercatat pada periode ini."));
  } else {
    /* Repeated cause sentences are printed once above the list (same as `services.js`; service incidents are drawn in both places). */
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
      panel.appendChild(kejadianLayanan(r, sebabBersama));
    });
  }

  td.appendChild(panel);
  tr.appendChild(td);
  return tr;
}

function kejadianLayanan(r, sebabBersama) {
  var k = el("div", "kejadian");
  // Target of the link from the incident card on the Report page.
  k.id = "insiden-svc-" + r.id;

  k.appendChild(el("div", "waktu-kejadian", r.berlangsung
    ? jam(r.mulai) + " — belum pulih (" + r.durasi_teks + " berjalan)"
    : jam(r.mulai) + " — " + jam(r.selesai) + "  •  " + r.durasi_teks));

  k.appendChild(el("span",
    "lencana " + (r.berlangsung ? "lencana-down" : "lencana-menunggu"),
    r.berlangsung ? "masih berlangsung" : (r.kategori || "gangguan")));

  var sebab = (r.detail || r.kategori_teks || "").trim();
  if (sebabBersama && sebabBersama.indexOf(sebab) >= 0) {
    // Already printed once above the list; marked so the reader knows the card has a cause (full text on hover).
    var acuan = el("div", "sebab-kejadian redup", "Sebab: sesuai keterangan di atas");
    acuan.setAttribute("data-petunjuk", sebab);
    k.appendChild(acuan);
  } else {
    sebab.split("\n\n").forEach(function (p) {
      if (p.trim()) k.appendChild(el("div", "sebab-kejadian", p.trim()));
    });
  }

  if (r.bukti && r.bukti.length) {
    var ul = el("ul", "bukti");
    r.bukti.forEach(function (b) {
      ul.appendChild(el("li",
        b.ok === true ? "ok" : b.ok === false ? "gagal" : "netral", b.teks));
    });
    k.appendChild(ul);
  }

  if (r.saran) k.appendChild(el("div", "saran", "Saran: " + r.saran));

  // Two snapshots taken over SSH at the moment of failure and recovery; some figures (service uptime, requests served) are lost once the service restarts.
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

function muatRiwayatLayanan(id) {
  return ambilJson("/api/services/" + id + "/history?period=" + encodeURIComponent(periode))
    .then(function (d) {
      svcRiwayat[id] = d;
      gambarLayanan(dataLayanan);
    })
    .catch(function (e) {
      svcRiwayat[id] = { error: (e && e.sesiHabis) ? e.message
                                                   : "Gagal memuat riwayat layanan" };
      gambarLayanan(dataLayanan);
    });
}

// Traffic: who fetches what from this device. Separate from the bandwidth table: interface counters know how many bytes but not the peer, while the access log knows who requested what but only for HTTP.
function gambarTraffic(d) {
  var box = document.getElementById("traffic");
  var ket = document.getElementById("traffic-ket");
  box.innerHTML = "";
  ket.textContent = "";

  if (!d || d.error) {
    ket.textContent = (d && d.error) || "Data lalu lintas tidak tersedia.";
    ringkasPanel("traffic", "tidak tersedia");
    return;
  }
  if (!d.ada_data) {
    ket.textContent = d.alasan || "Belum ada permintaan web tercatat.";
    ringkasPanel("traffic", "belum ada permintaan tercatat");
    return;
  }

  ket.textContent = d.total_permintaan + " permintaan, " + d.total_unduh_teks
    + " terunduh pada periode ini"
    + (d.permintaan_dari_nsm
        ? ". " + d.permintaan_dari_nsm + " di antaranya pemeriksaan NSM sendiri, "
          + "ikut dihitung dan tidak disembunyikan."
        : ".");
  ringkasPanel("traffic",
    d.total_permintaan + " permintaan, " + d.total_unduh_teks);

  var bagianKlien = el("div", "sub-bagian");
  bagianKlien.appendChild(el("h3", null, "Alamat yang mengambil data"));
  var tabelK = el("table");
  var theadK = el("thead");
  var trhK = el("tr");
  ["Alamat", "Permintaan", "Terunduh", "Gagal", "Berkas terbesar", "Terakhir"]
    .forEach(function (j) { trhK.appendChild(el("th", null, j)); });
  theadK.appendChild(trhK);
  tabelK.appendChild(theadK);
  var tbodyK = el("tbody");
  d.klien.forEach(function (k) {
    var tr = el("tr");
    tr.appendChild(selKlien(el("td"), k.ip, k.device));
    tr.appendChild(el("td", "byte", String(k.permintaan)));
    tr.appendChild(el("td", "byte", k.unduh_teks));
    // Failed column with details attached, so the red number is actionable.
    var tdGagal = el("td", "byte" + (k.gagal ? " merah" : ""), String(k.gagal || 0));
    if (k.gagal && k.gagal_rinci && k.gagal_rinci.length) {
      var rinci = k.gagal_rinci.map(function (g) {
        return jam(g.waktu) + "  " + g.status + " " + g.status_teks
          + "  " + (g.path || "-");
      }).join("\n");
      if (k.gagal > k.gagal_rinci.length) {
        rinci += "\n(" + k.gagal_rinci.length + " terbaru dari " + k.gagal + ")";
      }
      tdGagal.setAttribute("data-petunjuk",
        "Permintaan yang dijawab server dengan kode 400 ke atas:\n" + rinci);
      tdGagal.classList.add("bisa-ditanya");
    }
    tr.appendChild(tdGagal);
    var tdPath = el("td", "path", k.path_terbesar || "-");
    if (k.path_terbesar_teks) {
      tdPath.setAttribute("data-petunjuk", "Berkas terbesar yang diambil alamat "
        + "ini: " + k.path_terbesar_teks);
    }
    tr.appendChild(tdPath);
    tr.appendChild(el("td", "waktu", jam(k.terakhir)));
    tbodyK.appendChild(tr);
  });
  tabelK.appendChild(tbodyK);
  bagianKlien.appendChild(bungkusTabel(tabelK));
  box.appendChild(bagianKlien);

  if (d.path && d.path.length) {
    var bagianPath = el("div", "sub-bagian");
    bagianPath.appendChild(el("h3", null, "Berkas yang paling banyak diambil"));
    var tabelP = el("table");
    var theadP = el("thead");
    var trhP = el("tr");
    ["Path", "Permintaan", "Total terkirim"].forEach(function (j) {
      trhP.appendChild(el("th", null, j));
    });
    theadP.appendChild(trhP);
    tabelP.appendChild(theadP);
    var tbodyP = el("tbody");
    d.path.forEach(function (p) {
      var tr = el("tr");
      tr.appendChild(el("td", "path", p.path));
      tr.appendChild(el("td", "byte", String(p.permintaan)));
      tr.appendChild(el("td", "byte", p.teks));
      tbodyP.appendChild(tr);
    });
    tabelP.appendChild(tbodyP);
    bagianPath.appendChild(bungkusTabel(tabelP));
    box.appendChild(bagianPath);
  }

  // TCP connections: traffic OUTSIDE HTTP
  if (d.lawan && d.lawan.length) {
    var bagianFlow = el("div", "sub-bagian");
    bagianFlow.appendChild(el("h3", null, "Koneksi TCP yang sedang terbuka"));
    var ketFlow = el("div", "ket",
      "Potret terakhir diambil " + jam(d.waktu_flow) + ". Berbeda dari tabel di "
      + "atas yang hanya melihat HTTP, ini melihat seluruh TCP. Karena berupa "
      + "potret berkala, koneksi yang hidup sebentar lalu tutup di antara dua "
      + "potret bisa terlewat.");
    jelaskan(ketFlow, "flow-koneksi");
    bagianFlow.appendChild(ketFlow);
    var tabelF = el("table");
    var theadF = el("thead");
    var trhF = el("tr");
    ["Lawan bicara", "Koneksi", "Masuk", "Keluar"].forEach(function (j) {
      trhF.appendChild(el("th", null, j));
    });
    theadF.appendChild(trhF);
    tabelF.appendChild(theadF);
    var tbodyF = el("tbody");
    d.lawan.forEach(function (l) {
      var tr = el("tr");
      tr.appendChild(selKlien(el("td"), l.ip, l.device));
      tr.appendChild(el("td", "byte", String(l.koneksi)));
      tr.appendChild(el("td", "byte", l.masuk_teks));
      tr.appendChild(el("td", "byte", l.keluar_teks));
      tbodyF.appendChild(tr);
    });
    tabelF.appendChild(tbodyF);
    bagianFlow.appendChild(bungkusTabel(tabelF));
    box.appendChild(bagianFlow);
  }

  if (d.catatan_unggah) {
    box.appendChild(el("div", "catatan", d.catatan_unggah));
  }
}

// Land on the row an incident card points to. The browser handles #anchors only for elements present at load; here content is drawn after data arrives, so the jump is done once afterward (repeating on each refresh would steal the reading position).
var sudahMelompat = false;

function lompatKeJangkar() {
  if (sudahMelompat) return;
  var hash = window.location.hash;
  if (!hash || hash.length < 2) return;

  var sasaran = document.getElementById(hash.substring(1));
  if (!sasaran) return;

  sudahMelompat = true;
  // The wrapping panel is opened first so the link does not land inside a closed panel.
  if (window.NSMLipat) window.NSMLipat.bukaUntuk(sasaran);
  sasaran.scrollIntoView({ behavior: "smooth", block: "center" });
  sasaran.classList.add("disorot");
}

/* Service incident anchors are inside closed history panels, so all are opened once, then the page jumps after content arrives. Services per device are few, so this is a handful of requests. */
function bukaJangkarLayanan() {
  if (sudahMelompat) return;
  var hash = window.location.hash;
  if (!hash || hash.indexOf("#insiden-svc-") !== 0) return;
  if (!dataLayanan || !dataLayanan.layanan) return;

  var perlu = dataLayanan.layanan.filter(function (s) { return !svcTerbuka[s.id]; });
  if (!perlu.length) return;

  perlu.forEach(function (s) { svcTerbuka[s.id] = true; });
  gambarLayanan(dataLayanan);
  Promise.all(perlu.map(function (s) { return muatRiwayatLayanan(s.id); }))
    .then(lompatKeJangkar);
}

async function lihatDetail(id) {
  var panel = document.getElementById("panel");
  panel.innerHTML = "";
  var tunggu = el("div", "kartu-ssh", "Mengambil data lewat SSH…");
  panel.appendChild(tunggu);
  try {
    var r = await fetch("/api/devices/" + id + "/info");
    var j = await r.json();
    panel.innerHTML = "";
    var k = el("div", "kartu-ssh");
    // The panel title names the correct path; `dataTerakhir` is filled at page load, so the platform is known.
    var lewat = (dataTerakhir && dataTerakhir.device
                 && dataTerakhir.device.platform === "lokal")
      ? ": detail langsung dari mesin ini" : ": detail via SSH";
    k.appendChild(el("h3", null, (j.device || "Device") + lewat));

    // Fetch time. This block is filled once when the button is pressed while the rest of the page refreshes every 10 seconds, so a timestamp shows the two come from different moments.
    var diambil = new Date();
    var capWaktu = el("div", "waktu-ssh", "Diambil ");
    // The time sits in its own element because `pasangWaktuRelatif` overwrites the content of the elements it manages every 20 seconds.
    var nilaiWaktu = el("span");
    capWaktu.appendChild(nilaiWaktu);
    pasangWaktuRelatif(nilaiWaktu, diambil);
    k.appendChild(capWaktu);

    if (j.error) {
      k.appendChild(el("div", "galat", j.error));
    } else {
      Object.entries(j.data).forEach(function (pasangan) {
        k.appendChild(el("div", "label", pasangan[0]));
        k.appendChild(el("pre", null, pasangan[1]));
      });
    }
    panel.appendChild(k);

    // After a few minutes the content is dimmed: stale numbers stay comparable but must not look as authoritative as fresh ones.
    setTimeout(function () {
      if (k.isConnected) k.classList.add("basi");
    }, 5 * 60 * 1000);
  } catch (e) {
    panel.innerHTML = "";
    panel.appendChild(el("div", "kartu-ssh galat", "Gagal mengambil detail device"));
  }
}

/* Whole-period strip. The history table only lists status changes, so spans with no samples leave no row. Boxes without samples are hatched, not colored, because color means device state and "unknown" is a gap in observation. Source is /api/report/sparkline; each box's fraction comes from Python. */
function gambarPita(d) {
  var pita = document.getElementById("pita");
  var jamBar = document.getElementById("pita-jam");
  var kabar = document.getElementById("pita-kabar");
  if (!pita) return;
  pita.innerHTML = "";
  if (jamBar) jamBar.innerHTML = "";

  var kotak = (d && d.devices && d.devices[String(DEVICE_ID)]) || null;
  if (!kotak || !kotak.length) {
    if (kabar) kabar.textContent = "belum ada sampel pada periode ini";
    return;
  }

  var buta = 0;
  kotak.forEach(function (v) {
    var s = document.createElement("span");
    s.style.width = (100 / kotak.length) + "%";
    if (v === null || v === undefined) {
      s.className = "s-buta";
      s.setAttribute("data-petunjuk",
        "Tidak ada satu pun sampel pada potongan waktu ini. Bukan berarti "
        + "perangkat sehat dan bukan berarti mati — berarti NSM tidak sedang "
        + "melihat. Rentang ini tidak ikut dihitung ke Availability.");
      buta++;
    } else {
      // Threshold is 0.999, not 1: one failed ping among 700 samples gives 0.9986 and rounding it to green would hide the only event.
      s.className = v >= 0.999 ? "s-up" : (v <= 0 ? "s-down" : "s-sebagian");
      s.setAttribute("data-petunjuk",
        (v * 100).toFixed(1) + "% sampel pada potongan ini berhasil.");
    }
    pita.appendChild(s);
  });

  /* Time axis: five markers rather than one per box, which would overlap. */
  if (jamBar && d.mulai && d.selesai) {
    var t0 = new Date(d.mulai).getTime();
    var t1 = new Date(d.selesai).getTime();
    var PENANDA = 5;
    for (var i = 0; i < PENANDA; i++) {
      var t = new Date(t0 + (t1 - t0) * (i / (PENANDA - 1)));
      // Long periods need dates, since a bare "08.00" over 30 days is ambiguous.
      var teks = (t1 - t0) > 36 * 3600 * 1000
        ? t.toLocaleDateString("id-ID", { day: "2-digit", month: "short" })
        : t.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
      jamBar.appendChild(el("span", null, teks));
    }
  }

  if (kabar) {
    // The strip header states the easiest thing to miss: how many pieces were unobserved.
    kabar.textContent = buta
      ? buta + " dari " + kotak.length + " potongan tidak terpantau"
      : "seluruh periode terpantau";
  }
}

// ---------------------------------------------------------------------------
// Muat data
// ---------------------------------------------------------------------------
async function muat() {
  try {
    // Always bg=true: opening this page is already written to the audit log by ReportController, so polling requests must not add a row every 10 seconds.
    // Four requests run in parallel. Services and traffic are wrapped so their failure does not take the page down; incident history and charts are the core.
    var [rh, rb, dataSvc, dataTrf, dataPita] = await Promise.all([
      fetch("/api/devices/" + DEVICE_ID + "/history?period=" + periode
            + "&limit=500&bg=true"),
      fetch("/api/devices/" + DEVICE_ID + "/bandwidth?period=" + periode),
      ambilJson("/api/devices/" + DEVICE_ID + "/services?period=" + periode)
        .catch(function () { return null; }),
      ambilJson("/api/devices/" + DEVICE_ID + "/traffic?period=" + periode)
        .catch(function () { return null; }),
      // The whole-period strip is also wrapped in a `catch`, for the same reason as services and traffic.
      ambilJson("/api/report/sparkline?period=" + periode)
        .catch(function () { return null; })
    ]);
    var data = await rh.json();
    if (data.error) {
      document.getElementById("nama").textContent = data.error;
      document.getElementById("meta").textContent = "";
      return;
    }
    var dataBw = await rb.json();
    dataTerakhir = data;
    gambarKepala(data.device, data.dipantau_sejak);
    gambarDampakHilir(data.dampak_hilir);
    gambarRingkas(data);
    gambarPita(dataPita);
    gambarBandwidth(dataBw);
    if (dataSvc) gambarLayanan(dataSvc);
    gambarTraffic(dataTrf);
    gambarRiwayat(data);
    perbaruiExport(data);
    // Content now exists, so anchors from incident cards can be found.
    bukaJangkarLayanan();
    lompatKeJangkar();
    document.getElementById("meta").textContent =
      "Diperbarui " + new Date().toLocaleTimeString("id-ID");
  } catch (e) {
    document.getElementById("meta").textContent = "Gagal terhubung ke backend";
  }
}

/* Download links and print button for the device page. */
function perbaruiExport(data) {
  var unduh = document.getElementById("unduh-excel");
  if (unduh) {
    unduh.setAttribute("href",
      "/report/device/" + DEVICE_ID + "/export?period=" + periode);
  }
  isiKepalaCetak(data);
}

/* Identity block and footer on the print sheet. All values come from the same `data` that draws the screen, never recomputed (a separate calculation once gave 96.805% vs 96.528% for the same data). */
function isiKepalaCetak(data) {
  function isi(id, teks) {
    var el = document.getElementById(id);
    if (el) { el.textContent = teks || "-"; }
  }
  if (!data || !data.device) { return; }
  var r = data.ringkasan || {};

  isi("ic-perangkat", data.device.name);
  isi("ic-alamat", data.device.ip_address);
  isi("ic-lokasi", data.device.location);
  isi("ic-periode", data.periode_teks || periode);

  // The range is computed from `periode_detik` sent by the backend, since the device history endpoint does not send `mulai`/`selesai`. `waktuLengkap` comes from `js/waktu.js`.
  if (data.periode_detik) {
    var selesai = new Date();
    var mulai = new Date(selesai.getTime() - data.periode_detik * 1000);
    isi("ic-rentang", waktuLengkap(mulai) + "  s.d.  " + waktuLengkap(selesai));
  } else {
    isi("ic-rentang", "-");
  }

  // "Monitoring duration" differs from "period": a device can be registered mid-period and the poller can be off. The difference belongs on paper.
  var diamati = r.durasi_diamati_teks || "-";
  if (data.periode_penuh === false) {
    diamati += " (belum satu periode penuh)";
  }
  isi("ic-diamati", diamati);

  isi("ic-tanggal", new Date().toLocaleString("id-ID", {
    day: "2-digit", month: "long", year: "numeric",
    hour: "2-digit", minute: "2-digit"
  }));

  var sumber = "Sumber data: ping ICMP berkala dan pemeriksaan port TCP oleh " +
      "NSM. Ketersediaan dihitung dari durasi, dan waktu ketika NSM sendiri " +
      "tidak memantau (poller mati atau perangkat dijeda) DIKELUARKAN dari " +
      "hitungan, tidak dianggap sebagai perangkat mati.";
  if (data.periode_penuh === false) {
    sumber += " Perangkat ini belum diamati selama satu periode penuh, jadi " +
        "angkanya belum bisa disandingkan langsung dengan perangkat lain.";
  }
  if (r.tak_terpantau_teks) {
    sumber += " Tidak terpantau selama " + r.tak_terpantau_teks +
        " dalam periode ini.";
  }
  isi("kaki-sumber", sumber);

  isi("kaki-kanan", "Dicetak " + new Date().toLocaleString("id-ID", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit"
  }));
}

function pasangExport() {
  var cetak = document.getElementById("cetak");
  if (cetak) {
    cetak.addEventListener("click", function () {
      // Incident history is always fully drawn (pagination only uses `hidden`) and the print CSS in nsm.css forces hidden rows to print, so no redraw is needed before printing.
      window.print();
    });
  }
}

function pasangPeriode() {
  /* Only pills with `data-p`. The "Excel" and "Cetak" buttons share the `.pil` class, so a plain `#periode .pil` selector would turn the URL into `?period=null` and clear the active highlight. */
  var pils = document.querySelectorAll("#periode .pil[data-p]");
  pils.forEach(function (p) {
    if (p.getAttribute("data-p") === periode) p.classList.add("aktif");
    p.addEventListener("click", function () {
      periode = p.getAttribute("data-p");
      // Fetched service histories belong to the old period and are discarded; open panels stay open and are refilled.
      svcRiwayat = {};
      Object.keys(svcTerbuka).forEach(function (id) { muatRiwayatLayanan(id); });
      pils.forEach(function (x) { x.classList.remove("aktif"); });
      p.classList.add("aktif");
      // Keep the choice in the URL so it survives refresh and sharing.
      history.replaceState(null, "", "/report/device/" + DEVICE_ID + "?period=" + periode);
      muat();
    });
  });
}

pasangPeriode();
pasangExport();
// "?" icons are attached before the first data arrives, so explanations are available while the page loads.
pasangPenjelasanBagian();

// Two separate rhythms: the chart every 5 seconds (light request), the page every 10 seconds (heavy request). Merging them would make faster charts trigger heavy queries.
isiGrafikAwal().then(muat);
setInterval(denyutGrafik, JEDA_GRAFIK);
setInterval(muat, 10000);
