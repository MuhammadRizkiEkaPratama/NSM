/*
 * NSM Report: availability and summary of all devices. All numbers come ready-made from Python; anti-XSS (textContent / createElement only).
 * Auto-refresh is 10 seconds (heavier than the 5-second dashboard), with one request per cycle so cards and table use the same calculation.
 * Incident history lives on each device's page: /report/device/{id}.
 */

var periode = (typeof PERIODE_AWAL === "string") ? PERIODE_AWAL : "24h";
var dataDevice = [];
// Summary of the period currently shown. Kept because each table row needs the period length to judge how much of it was observed; recomputing it from the period name would duplicate Python's translation.
var ringkasTerakhir = null;

/* Up/down pattern per device. Kept apart from dataDevice because it comes from a much more expensive endpoint, so it is fetched on page open, on period change, and then once a minute. */
var dataSparkline = {};
var lebarPetakDetik = 0;

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function jam(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", { day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Five-level availability scale. 100% is distinguished from merely good, and there is an orange step between yellow and red so drops do not jump straight from "fair" to "bad" (red under 99% was too strict for the GNS3 emulated routers).
function warnaAvail(nilai) {
  if (nilai === null || nilai === undefined) return "abu";
  if (nilai >= 100) return "hijau-gelap";
  if (nilai >= 99) return "hijau";
  if (nilai >= 95) return "kuning";
  if (nilai >= 90) return "oranye";
  return "merah";
}

function teksAvail(nilai) {
  return (nilai === null || nilai === undefined) ? "-" : nilai.toFixed(2) + "%";
}

// ---------------------------------------------------------------------------
// 4 card utama + strip sekunder
// ---------------------------------------------------------------------------
/* `penjelasan` shows on hover over the card instead of being printed below it. */
function kartu(judul, angka, kelasAngka, sub, penjelasan) {
  var c = el("div", "kartu");
  if (penjelasan) c.setAttribute("data-petunjuk", penjelasan);
  c.appendChild(el("div", "judul", judul));
  c.appendChild(el("div", "angka " + (kelasAngka || ""), angka));
  c.appendChild(el("div", "sub", sub || ""));
  return c;
}

/* Put the answer into the header of a collapsed panel. Safe to call before lipatan.js has run, since the page refreshes itself every 10 seconds. */
function ringkasPanel(kunci, teks, kelas) {
  if (window.NSMLipat) window.NSMLipat.ringkas(kunci, teks, kelas);
}

function gambarCards(s) {
  var box = document.getElementById("cards");
  box.innerHTML = "";

  var semuaUp = s.device_down === 0;
  box.appendChild(kartu(
    "Device Hidup Sekarang",
    s.device_up + " / " + s.total_device,
    semuaUp ? "hijau" : "merah",
    semuaUp ? "Semua device merespons" : s.device_down + " device tidak merespons",
    "Keadaan saat ini, bukan sepanjang periode. Device yang sedang dijeda "
    + "tidak ikut dihitung karena memang sengaja tidak diperiksa."
  ));

  // If monitoring has not covered the requested period, say so plainly: 85% of 40 minutes is not a badly failing device, only a small denominator. The range stated is the span, not the longest device window.
  var ketAvail;
  var jelasAvail = "Persentase pemeriksaan ping yang berhasil, dirata-rata dari "
    + "semua device pada periode ini. Hijau tua 100 persen, hijau di atas 99, "
    + "kuning di atas 95, oranye di atas 90, merah di bawah itu.";
  if (s.periode_penuh) {
    ketAvail = "Rata-rata semua device pada periode ini";
  } else if (s.diamati_beragam) {
    ketAvail = "Baru dipantau " + s.diamati_teks + " sampai " + s.diamati_maks_teks
      + ", belum " + s.periode_teks + " penuh";
    jelasAvail += " Jendela pengamatan tiap device berbeda: yang paling sedikit "
      + "diamati baru " + s.diamati_teks + ", yang paling banyak "
      + s.diamati_maks_teks + ". Device yang jarang diamati punya peluang lebih "
      + "kecil ketahuan bermasalah, jadi angkanya belum setara untuk dibandingkan.";
  } else {
    ketAvail = "Baru dipantau " + s.diamati_teks + ", belum " + s.periode_teks + " penuh";
  }
  // Availability is the main number of the page, so it is larger than the other cards.
  var kartuAvail = kartu(
    "Availability Keseluruhan",
    teksAvail(s.availability_rata),
    warnaAvail(s.availability_rata),
    ketAvail,
    jelasAvail
  );
  kartuAvail.classList.add("kartu-sorot");
  box.appendChild(kartuAvail);

  // The total incident count is shown unchanged; unstable devices are mentioned in the sub-label so the big number is not read as all separate failures.
  var subInsiden = "Total waktu down: " + s.total_down_teks;
  if (s.device_flapping > 0) {
    subInsiden += " · " + s.device_flapping + " device tidak stabil";
  }
  box.appendChild(kartu(
    "Insiden Gangguan",
    String(s.insiden_total),
    s.insiden_total === 0 ? "hijau" : "kuning",
    subInsiden,
    "Satu insiden dihitung sejak device berhenti merespons sampai pulih. "
    + "Device yang putus-nyambung ditandai TIDAK STABIL kalau terjadi 3 kali "
    + "atau lebih dalam 15 menit, dan baru dianggap stabil lagi setelah "
    + "hening (tanpa gangguan sama sekali) selama 10 menit penuh."
  ));

  var lambat = s.device_paling_lambat
    ? "Paling lambat: " + s.device_paling_lambat.name + " (" + s.device_paling_lambat.ms + " ms)"
    : "Belum ada data latency";
  box.appendChild(kartu(
    "Latency Rata-rata",
    s.latency_rata_ms === null ? "-" : s.latency_rata_ms + " ms",
    "biru",
    lambat,
    "Waktu balasan ping, dirata-rata dari semua device. Angka besar berarti "
    + "jalur lambat atau perangkat sibuk, bukan berarti device mati."
  ));

  var mini = document.getElementById("sekunder");
  mini.innerHTML = "";

  function kotak(judul, isi, penjelasan) {
    var m = el("div", "kartu-mini");
    if (penjelasan) m.setAttribute("data-petunjuk", penjelasan);
    m.appendChild(el("div", "judul", judul));
    m.appendChild(el("div", "isi", isi));
    return m;
  }

  mini.appendChild(kotak("MTTR (rata-rata waktu pulih)", s.mttr_teks || "-",
    "Mean Time To Recovery: rata-rata lama device kembali merespons setelah "
    + "gangguan. Makin kecil makin baik."));

  // Worst device. If it is unstable NOW, say for how long; that is current state, which can differ from the incident count over the period.
  var topTeks = "Tidak ada gangguan";
  if (s.top_offender) {
    topTeks = s.top_offender.flapping
      ? s.top_offender.name + ": tidak stabil · " + s.top_offender.tidak_stabil_lama_teks
      : s.top_offender.name + ", " + s.top_offender.insiden + "x (" + s.top_offender.total_down_teks + ")";
  }
  mini.appendChild(kotak("Device paling bermasalah", topTeks));

  // This panel is collapsed by default, so its header shows MTTR, a single number, rather than a long sentence.
  ringkasPanel("sekunder", "MTTR " + (s.mttr_teks || "-"));

  mini.appendChild(kotak("Tanpa gangguan selama", s.uptime_streak_teks || "-",
    "Sudah berapa lama tidak ada satu pun device yang tercatat bermasalah. "
    + "Dihitung sejak gangguan terakhir berakhir, bukan sejak poller dinyalakan."));
}

// Latest incident panel: which layer failed, which layer proved healthy, and the next step. All sentences come from Python. Fetched from a separate endpoint because the content can be long and the summary is polled every 10 seconds.

/* Links come from the server but their shape is still checked before use as an href, to block `javascript:` URLs. */
var POLA_TAUTAN = /^\/report\/device\/\d+\?period=(1h|24h|7d|30d)(#insiden(-svc)?-\d+)?$/;

function gambarInsiden(ins) {
  var box = document.getElementById("insiden");
  if (!box) return;
  box.innerHTML = "";

  if (!ins) {
    // The title belongs to the panel header, so it is not repeated inside; the header carries the answer so a collapsed panel still reports state.
    ringkasPanel("insiden", "belum pernah ada gangguan", "baik");
    var kosong = el("div", "panel-insiden aman");
    kosong.appendChild(el("div", "sebab",
      "Belum pernah ada gangguan tercatat. Ini bisa berarti dua hal yang "
      + "berbeda: memang belum ada yang bermasalah, atau NSM memang baru mulai "
      + "memantau. Lihat kolom Terakhir Cek di tabel untuk membedakannya."));
    box.appendChild(kosong);
    return;
  }

  var bisaDiklik = typeof ins.tautan === "string" && POLA_TAUTAN.test(ins.tautan);
  var panel = el(bisaDiklik ? "a" : "div",
                 "panel-insiden" + (ins.berlangsung ? "" : " pulih"));
  if (bisaDiklik) {
    panel.setAttribute("href", ins.tautan);
    panel.setAttribute("title",
      "Buka halaman device dan langsung menuju baris kejadian ini");
  }

  ringkasPanel("insiden",
    (ins.jenis === "layanan" ? ins.layanan + " di " + ins.device : ins.device)
    + (ins.berlangsung ? " — belum pulih" : " — sudah pulih"),
    ins.berlangsung ? "buruk" : "hati");

  var baris = el("div", "baris-utama");
  // The target is written as is: a service failure and a device failure are different things ("Web Server BSP on VM testUbuntu" means the machine may be fine).
  baris.appendChild(el("span", "sasaran", ins.jenis === "layanan"
    ? ins.layanan + " di " + ins.device
    : ins.device));
  baris.appendChild(el("span", "lencana " + (ins.berlangsung ? "lencana-down" : "lencana-menunggu"),
    ins.berlangsung ? "belum pulih, " + ins.lama_teks : "pulih setelah " + ins.lama_teks));
  baris.appendChild(el("span", "kapan", jam(ins.waktu) + "  •  " + ins.ip));
  panel.appendChild(baris);

  if (ins.kategori_teks) {
    // The cause can contain separate paragraphs; keep them as paragraphs.
    (ins.detail || ins.kategori_teks).split("\n\n").forEach(function (p) {
      if (p.trim()) panel.appendChild(el("div", "sebab", p.trim()));
    });
  }

  if (ins.bukti && ins.bukti.length) {
    var ul = el("ul", "bukti");
    ins.bukti.forEach(function (b) {
      ul.appendChild(el("li",
        b.ok === true ? "ok" : b.ok === false ? "gagal" : "netral", b.teks));
    });
    panel.appendChild(ul);
  }

  if (ins.saran) panel.appendChild(el("div", "saran", "Saran: " + ins.saran));

  if (bisaDiklik) {
    var ket = "Buka rincian di halaman device";
    // The link's period may differ from the one being viewed: this card shows the latest incident in all history, while the device page is limited by period.
    if (ins.periode_saran && ins.periode_saran !== periode) {
      ket += " (periode disesuaikan ke " + ins.periode_saran
           + " supaya kejadiannya ikut terlihat)";
    }
    if (ins.punya_diagnosa) {
      ket += " — termasuk potret keadaan device yang diambil pada detik kejadian";
    }
    panel.appendChild(el("div", "ke-tkp", ket + " →"));
  }

  box.appendChild(panel);
}

function sel(teks, kelas) {
  var td = el("td", kelas);
  td.textContent = (teks === null || teks === undefined) ? "-" : teks;
  return td;
}

// Incident count column. The raw count is kept; a small pill with duration is added if the device is unstable NOW (see `hitung_kestabilan` in report_service.py). Built with the DOM API.
function selInsiden(d) {
  var td = el("td", d.insiden > 0 ? "kuning" : "");
  td.textContent = (d.insiden === null || d.insiden === undefined)
    ? "-" : String(d.insiden);
  if (d.flapping) {
    var teksPil = d.tidak_stabil_lama_teks
      ? "tidak stabil · " + d.tidak_stabil_lama_teks
      : "tidak stabil";
    var pil = el("span", "lencana lencana-menunggu", teksPil);
    pil.style.marginLeft = "6px";
    td.appendChild(pil);
  }
  return td;
}

// Quality column, deliberately separate from Availability (see `report_service.hitung_kualitas_sambungan`): availability is up/down, quality is path quality from packet loss, independent of DOWN_THRESHOLD.
var KUALITAS_LABEL = { bagus: "Bagus", cukup: "Cukup", buruk: "Buruk",
                       sangat_buruk: "Sangat buruk" };
var KUALITAS_KELAS = { bagus: "hijau", cukup: "kuning", buruk: "oranye",
                       sangat_buruk: "merah" };

function selKualitas(d) {
  var td = el("td");
  if (!d.kualitas_vonis) {
    td.className = "redup";
    td.textContent = "-";
    return td;
  }
  td.appendChild(el("span", KUALITAS_KELAS[d.kualitas_vonis] || "abu",
    KUALITAS_LABEL[d.kualitas_vonis] || d.kualitas_vonis));
  var petunjuk = "Kehilangan paket " + d.kehilangan_persen.toFixed(1)
    + "% pada periode ini";
  if (d.latensi_maks_ms !== null && d.latensi_maks_ms !== undefined) {
    petunjuk += ", latensi tertinggi " + d.latensi_maks_ms + " ms";
  }
  petunjuk += ". Ini BEDA dari Availability: availability menjawab device "
    + "hidup atau mati, ini menjawab bagus atau jeleknya jalur -- device "
    + "bisa saja hidup 100% tapi masih membuang banyak paket.";
  td.setAttribute("data-petunjuk", petunjuk);
  td.dataset.nilai = d.kehilangan_persen;
  return td;
}

function barisDevice(d) {
  var tr = el("tr");

  // A PAUSED device's status is unknown, not UP: NSM stopped checking it. Matches the Dashboard (gray icon, no UP/DOWN).
  var dijeda = d.aktif === false;
  var tdStatus = el("td");
  var isiStatus = el("span", "sel-device");
  isiStatus.appendChild(titikStatus(dijeda ? null : d.is_reachable));
  isiStatus.appendChild(el("span",
    dijeda ? "abu" : d.is_reachable === true ? "hijau"
           : d.is_reachable === false ? "merah" : "abu",
    dijeda ? "tidak dipantau"
           : d.is_reachable === true ? "UP"
           : d.is_reachable === false ? "DOWN" : "?"));
  if (dijeda) {
    tdStatus.setAttribute("data-petunjuk",
      "Pemantauan device ini sedang dijeda, jadi NSM berhenti memeriksanya dan "
      + "statusnya sekarang tidak diketahui. Angka pada baris ini berasal dari "
      + "periode sebelum dijeda dan tidak lagi bertambah.");
  }
  tdStatus.appendChild(isiStatus);
  tr.appendChild(tdStatus);

  // Ikon device + nama. Klik ikonnya -> kartu detail singkat muncul.
  var tdNama = el("td");
  tdNama.appendChild(selDevice(d));
  // Paused devices are still shown, marked so it is clear their numbers stopped updating.
  if (d.aktif === false) {
    var tanda = el("span", "lencana lencana-netral", "dijeda");
    tanda.style.marginLeft = "8px";
    tdNama.appendChild(tanda);
    tr.classList.add("baris-dijeda");
  }
  tr.appendChild(tdNama);

  tr.appendChild(sel(d.ip_address));

  var tdAvail = el("td");
  var bar = el("span", "bilah-nilai");
  var isi = el("i");
  var persen = (d.availability === null || d.availability === undefined) ? 0 : d.availability;
  isi.style.width = persen + "%";
  // Colors come from tokens and must match `warnaAvail()` below exactly.
  var gaya = getComputedStyle(document.documentElement);
  isi.style.background = gaya.getPropertyValue(
    persen >= 100 ? "--up-gelap" : persen >= 99 ? "--up"
    : persen >= 95 ? "--hati-hati" : persen >= 90 ? "--waspada"
    : "--down").trim();
  bar.appendChild(isi);

  // The observation window affects how the bar looks: the less a device is observed, the better its number tends to look. So when less than half the period was observed, the bar is visually marked as not comparable.
  var pecahan = null;
  if (d.durasi_diamati_detik && ringkasTerakhir && ringkasTerakhir.periode_detik) {
    pecahan = d.durasi_diamati_detik / ringkasTerakhir.periode_detik;
  }
  if (pecahan !== null && pecahan < 0.5 && d.availability !== null
      && d.availability !== undefined) {
    bar.classList.add("belum-layak");
    var persenAmat = Math.round(pecahan * 100);
    bar.setAttribute("data-petunjuk",
      "Bilah ini diarsir karena perangkat ini baru diamati "
      + (d.durasi_diamati_teks || "-") + ", yaitu " + persenAmat + "% dari "
      + (ringkasTerakhir.periode_teks || "periode ini") + ". Lebih banyak "
      + "waktu yang TIDAK dilihat daripada yang dilihat, jadi angkanya belum "
      + "layak disandingkan dengan perangkat yang diamati penuh. Arahnya "
      + "terbalik dari dugaan: makin sedikit diamati, makin kecil peluang "
      + "gangguannya tertangkap, dan makin bagus angkanya terlihat.");
  }

  tdAvail.appendChild(bar);
  tdAvail.appendChild(el("span", warnaAvail(d.availability), teksAvail(d.availability)));
  // When coverage is too thin, the sentence points back to the number above and states the observed duration as a plain fact (for example "dipantau 8j 54m dari 24j") rather than a second percentage.
  if (pecahan !== null && pecahan < 0.5 && d.availability !== null
      && d.availability !== undefined) {
    tdAvail.appendChild(el("div", "catatan-jeda belum-layak",
      "dipantau baru " + (d.durasi_diamati_teks || "-") + " dari "
      + (ringkasTerakhir.periode_teks || "periode ini")
      + " — angka di atas belum bisa dibandingkan"));
  }
  // The number covers only observed time; if there were gaps, say how long. Availability is deliberately not published when observation is too short, and the cell says why instead of showing a bare "-".
  if (d.cukup_diamati === false) {
    var alasanPendek = el("div", "catatan-jeda",
      "diamati " + (d.durasi_diamati_teks || "-") + ", terlalu singkat");
    alasanPendek.setAttribute("data-petunjuk",
      "NSM hanya sempat mengamati device ini selama "
      + (d.durasi_diamati_teks || "-") + " pada periode ini, jadi angka "
      + "availability tidak diterbitkan sama sekali. Persentase dari "
      + "pengamatan sesingkat itu menyatakan sesuatu tentang periode yang "
      + "tidak pernah diukur, dan tidak bisa dibandingkan dengan device lain "
      + "di tabel yang sama.");
    tdAvail.appendChild(alasanPendek);
  }

  if (d.tak_terpantau_teks) {
    tdAvail.appendChild(el("div", "catatan-jeda",
      d.tak_terpantau_teks + " tak terpantau"));
    tdAvail.setAttribute("data-petunjuk",
      "NSM tidak memantau device ini selama " + d.tak_terpantau_teks
      + " pada periode ini (poller mati atau device dijeda). Waktu itu "
      + "dikeluarkan dari hitungan, tidak dianggap mati dan tidak dianggap hidup.");
  }
  // Raw value for sorting (see js/urut.js); the cell contains a bar, text, and sometimes a note, so its textContent is not comparable.
  if (typeof d.availability === "number") tdAvail.dataset.nilai = d.availability;
  tr.appendChild(tdAvail);

  // Up/down pattern, placed right after the availability number so they read as one.
  var tdPola = el("td");
  var deret = dataSparkline[String(d.id)];
  if (deret && deret.length) {
    var kanvas = document.createElement("canvas");
    kanvas.className = "sparkline";
    tdPola.appendChild(kanvas);
    tdPola.setAttribute("data-petunjuk", ringkasSparkline(deret, lebarPetakDetik));
    // Drawn after the element is in the page, since its width is zero before that.
    requestAnimationFrame(function () { gambarSparkline(kanvas, deret); });
  } else {
    tdPola.className = "redup";
    tdPola.textContent = "-";
  }
  tr.appendChild(tdPola);

  var tdInsiden = selInsiden(d);
  // An unknown incident count must not sort as zero. Without `data-nilai`, urut.js puts it last.
  if (typeof d.insiden === "number") tdInsiden.dataset.nilai = d.insiden;
  tr.appendChild(tdInsiden);

  var tdDown = sel(d.total_down_teks);
  // Seconds, not text, so durations sort correctly.
  tdDown.dataset.nilai = d.total_down_detik || 0;
  tr.appendChild(tdDown);

  var tdLat = sel(d.avg_latency_ms === null ? "-" : d.avg_latency_ms + " ms");
  if (typeof d.avg_latency_ms === "number") tdLat.dataset.nilai = d.avg_latency_ms;
  tr.appendChild(tdLat);

  tr.appendChild(selKualitas(d));

  // Last check time is relative; the exact time is in the hover title.
  var tdCek = el("td", "nowrap redup");
  if (d.last_checked) {
    tdCek.textContent = waktuRelatif(d.last_checked);
    tdCek.setAttribute("data-petunjuk", waktuLengkap(d.last_checked));
    var t = Date.parse(d.last_checked);
    if (!isNaN(t)) tdCek.dataset.nilai = t;
  } else {
    tdCek.textContent = "-";
  }
  tr.appendChild(tdCek);

  var tdAksi = el("td");
  var tautan = el("a", "tombol nowrap",
                  d.insiden > 0 ? "Riwayat (" + d.insiden + ")" : "Riwayat");
  tautan.setAttribute("href", "/report/device/" + d.id + "?period=" + periode);
  tdAksi.appendChild(tautan);
  tr.appendChild(tdAksi);

  return tr;
}

function gambarTabel() {
  var tbody = document.getElementById("rows");
  var pertamaKali = !tbody.dataset.pernahDigambar;
  tbody.innerHTML = "";
  dataDevice.forEach(function (d, urutan) {
    var tr = barisDevice(d);
    // Rows animate in once only; the table refreshes every 10 seconds and repeated animation would flicker.
    if (pertamaKali) {
      tr.classList.add("muncul");
      tr.style.animationDelay = (Math.min(urutan, 8) * 40) + "ms";
    }
    tbody.appendChild(tr);
  });
  tbody.dataset.pernahDigambar = "1";
}

// ---------------------------------------------------------------------------
// Muat data
// ---------------------------------------------------------------------------
async function muat() {
  try {
    var rs = await fetch("/api/report/summary?period=" + periode);
    var s = await rs.json();

    ringkasTerakhir = s;
    gambarCards(s);
    // Use `devices_semua`, not `devices`: `devices` holds only active devices (for card numbers, so paused ones do not skew averages) while `devices_semua` feeds the table so paused devices stay visible and match the downloaded Excel and Word files.
    dataDevice = s.devices_semua || s.devices || [];
    gambarTabel();
    perbaruiExport();

    document.getElementById("meta").textContent =
      "Diperbarui " + new Date().toLocaleTimeString("id-ID");
  } catch (e) {
    var pesan = (e instanceof TypeError && String(e.message).indexOf("fetch") >= 0)
      ? "Gagal terhubung ke backend"
      : "Data diterima, tetapi halaman gagal menggambarnya: " + e.message;
    document.getElementById("meta").textContent = pesan;
    console.error("[NSM] gagal memuat report:", e);
  }
}

/* Latest incident, fetched separately every 30 seconds. A failed fetch leaves the already drawn panel unchanged. */
/* SLO and error budget. Shows the remaining allowed downtime before the target is breached, since a bare availability percentage cannot drive a decision. Sorted with the thinnest budget first. */
function batangAnggaran(sisaPersen) {
  var luar = el("div", "slo-batang");
  var isi = el("div", "slo-isi");
  // Clamped to 0-100 only for the bar width; the real value (possibly well below zero) is still printed next to it.
  var lebar = Math.max(0, Math.min(100, sisaPersen));
  isi.style.width = lebar + "%";
  luar.appendChild(isi);
  return luar;
}

function barisSlo(d) {
  var baris = el("div", "slo-baris " + d.vonis);

  var kiri = el("div", "slo-kiri");
  kiri.appendChild(el("div", "slo-nama", d.device));
  kiri.appendChild(el("div", "slo-target",
    "target " + d.target_persen + "% \u00b7 tercapai " +
    (d.availability_persen === null ? "-" : d.availability_persen + "%")));
  baris.appendChild(kiri);

  var tengah = el("div", "slo-tengah");
  tengah.appendChild(batangAnggaran(d.sisa_persen));
  var ket = el("div", "slo-ket");
  ket.textContent = "terpakai " + d.terpakai_teks + " dari " + d.anggaran_teks
    + " \u00b7 diamati " + d.jendela_teks;
  tengah.appendChild(ket);
  baris.appendChild(tengah);

  var kanan = el("div", "slo-kanan");
  kanan.appendChild(el("div", "slo-sisa", d.sisa_teks));
  kanan.appendChild(el("div", "slo-persen", d.sisa_persen + "%"));
  baris.appendChild(kanan);

  // The "what it means" sentence goes in the title (hover), not printed on every row.
  baris.title = d.arti;
  return baris;
}

function gambarSlo(j) {
  var kotak = document.getElementById("slo");
  if (!kotak) return;
  kotak.textContent = "";

  if (!j || !j.device || !j.device.length) {
    kotak.appendChild(el("div", "redup",
      "Belum ada device yang cukup lama diamati untuk dinilai."));
  } else {
    j.device.forEach(function (d) { kotak.appendChild(barisSlo(d)); });
  }

  // Skipped devices are listed instead of silently dropped.
  if (j && j.belum_cukup_diamati && j.belum_cukup_diamati.length) {
    kotak.appendChild(el("div", "redup slo-catatan",
      "Belum dinilai karena pengamatannya masih terlalu pendek: "
      + j.belum_cukup_diamati.join(", ")
      + ". Angka SLO dari pengamatan sependek itu melompat-lompat dan tidak "
      + "memberi tahu apa pun."));
  }
}

/* The window is fixed at 30 days and does not follow the period picker: an error budget only means something over a span long enough to include several incidents. */
async function muatSlo() {
  try {
    var j = await ambilJson("/api/report/slo");
    gambarSlo(j);
  } catch (e) {
    console.warn("[NSM] SLO tidak bisa diambil:", e);
  }
}

async function muatInsiden() {
  try {
    var j = await ambilJson("/api/report/insiden-terakhir");
    gambarInsiden(j.insiden);
  } catch (e) {
    console.warn("[NSM] insiden terakhir tidak bisa diambil:", e);
  }
}

/* Fetched separately and rarely. Failure is non-fatal: the sparkline is decoration, so the table still shows without it. */
async function muatSparkline() {
  try {
    var r = await fetch("/api/report/sparkline?period=" + periode);
    var j = await r.json();
    dataSparkline = j.devices || {};
    lebarPetakDetik = j.lebar_detik || 0;
    if (dataDevice.length) gambarTabel();
  } catch (e) {
    console.warn("[NSM] pola naik-turun tidak bisa diambil:", e);
  }
}

/* Download and print-report links, updated on each period change. Printing this page directly is deliberately not offered; the report has its own print page. */
function perbaruiExport() {
  var unduh = document.getElementById("unduh-excel");
  if (unduh) unduh.setAttribute("href", "/report/export?period=" + periode);
  var unduhWord = document.getElementById("unduh-word");
  if (unduhWord) unduhWord.setAttribute("href", "/report/export-word?period=" + periode);
  var cetak = document.getElementById("ke-cetak");
  if (cetak) cetak.setAttribute("href", "/report/cetak?period=" + periode + "&print=1");
}

function pasangPeriode() {
  var pils = document.querySelectorAll("#alat .pil[data-p]");
  pils.forEach(function (p) {
    if (p.getAttribute("data-p") === periode) p.classList.add("aktif");
    function pilih() {
      periode = p.getAttribute("data-p");
      pils.forEach(function (x) { x.classList.remove("aktif"); });
      p.classList.add("aktif");
      history.replaceState(null, "", "/report?period=" + periode);
      dataSparkline = {};
      muat();
      muatSparkline();
      // The incident itself is period-independent, but the link's "period adjusted" note changes, so the panel is redrawn.
      muatInsiden();
      // `muatSlo()` is deliberately not called here: its window is fixed at 30 days.
    }
    p.addEventListener("click", pilih);
    // The period picker is a <span>, so Enter and Space are handled manually for keyboard use.
    p.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pilih(); }
    });
  });
}

pasangPeriode();
perbaruiExport();
muat();
muatSparkline();
muatInsiden();
// Loaded once: the window is fixed at 30 days.
muatSlo();

/* Refresh stops while the tab is hidden (no point polling the database six times a minute), and data is fetched once when the tab becomes visible again. */
var jamMuat = setInterval(function () {
  if (!document.hidden) muat();
}, 10000);

var jamSparkline = setInterval(function () {
  if (!document.hidden) muatSparkline();
}, 60000);

var jamInsiden = setInterval(function () {
  if (!document.hidden) muatInsiden();
}, 30000);

document.addEventListener("visibilitychange", function () {
  if (!document.hidden) { muat(); muatSparkline(); muatInsiden(); }
});
