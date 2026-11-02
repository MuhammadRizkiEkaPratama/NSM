/* Printable report. Builds a document rather than a dashboard: no auto-refresh, no buttons in tables, and incidents of all devices merged and sorted. */

var periode = (typeof PERIODE_AWAL === "string") ? PERIODE_AWAL : "24h";

// When opened from the "Unduh PDF" button on /report (`?print=1`), the print dialog opens once after the data has loaded (earlier prints a blank page).
var autoCetak = new URLSearchParams(location.search).get("print") === "1";

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function waktuLengkap(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Same thresholds as `warnaAvail()` in report.js.
function kelasAvail(n) {
  if (n === null || n === undefined) return "abu";
  if (n >= 100) return "hijau-gelap";
  if (n >= 99) return "hijau";
  if (n >= 95) return "kuning";
  if (n >= 90) return "oranye";
  return "merah";
}

function barisRingkas(label, nilai, kelas, catatan) {
  var b = el("div", "baris");
  b.appendChild(el("div", "k", label));
  b.appendChild(el("div", "n " + (kelas || ""), nilai));
  b.appendChild(el("div", "c", catatan || ""));
  return b;
}

function gambar(s) {
  var sekarang = new Date();

  // --- identitas laporan ---
  document.getElementById("i-periode").textContent =
    s.periode_teks || periode;
  document.getElementById("i-rentang").textContent =
    waktuLengkap(s.mulai) + "  s.d.  " + waktuLengkap(s.selesai);
  // Each device's observation window can differ, so it is shown per device rather than as one number.
  document.getElementById("i-diamati").textContent =
    (s.diamati_beragam
      ? (s.diamati_teks || "-") + " s.d. " + (s.diamati_maks_teks || "-")
        + " (berbeda tiap perangkat)"
      : (s.diamati_teks || "-")) +
    (s.periode_penuh ? "" : "  (periode belum terpenuhi seluruhnya)");
  document.getElementById("i-jumlah").textContent =
    s.total_device + " perangkat dipantau" +
    (s.device_dijeda ? ", " + s.device_dijeda + " dijeda" : "");
  document.getElementById("i-tanggal").textContent =
    waktuLengkap(sekarang.toISOString());

  // --- I. Ringkasan ---
  var r = document.getElementById("ringkas");
  r.innerHTML = "";
  r.appendChild(barisRingkas("Perangkat merespons saat laporan dibuat",
    s.device_up + " dari " + s.total_device,
    s.device_down ? "merah" : "hijau",
    s.device_down ? s.device_down + " perangkat tidak merespons"
                  : "Seluruh perangkat merespons"));
  r.appendChild(barisRingkas("Ketersediaan keseluruhan",
    s.availability_rata === null ? "-" : s.availability_rata.toFixed(3) + "%",
    kelasAvail(s.availability_rata),
    "Rata-rata seluruh perangkat aktif pada periode ini"));
  r.appendChild(barisRingkas("Jumlah gangguan", String(s.insiden_total),
    s.insiden_total ? "kuning" : "hijau",
    "Total waktu tidak merespons: " + s.total_down_teks));
  r.appendChild(barisRingkas("Rata-rata waktu pemulihan (MTTR)",
    s.mttr_teks || "-", "",
    "Total waktu pulih dibagi jumlah gangguan yang telah selesai"));
  r.appendChild(barisRingkas("Latency rata-rata",
    s.latency_rata_ms === null ? "-" : s.latency_rata_ms + " ms", "",
    s.device_paling_lambat
      ? "Terlambat: " + s.device_paling_lambat.name +
        " (" + s.device_paling_lambat.ms + " ms)" : ""));
  r.appendChild(barisRingkas("Perangkat paling bermasalah",
    s.top_offender ? s.top_offender.name : "Tidak ada", "",
    s.top_offender
      ? s.top_offender.insiden + " gangguan, total " +
        s.top_offender.total_down_teks : ""));
  r.appendChild(barisRingkas("Berjalan tanpa gangguan",
    s.uptime_streak_teks || "-", "",
    s.insiden_terakhir
      ? "Gangguan terakhir: " + s.insiden_terakhir.device + " pada " +
        waktuLengkap(s.insiden_terakhir.waktu) : "Belum pernah ada gangguan"));

  var perhatian = document.getElementById("perhatian");
  perhatian.innerHTML = "";
  document.getElementById("ket-perhatian").textContent =
    "Perangkat disorot bila ketersediaannya di bawah 99%, mengalami 3 gangguan " +
    "atau lebih, atau sedang tidak merespons saat laporan dibuat.";

  var perlu = (s.devices_semua || s.devices).filter(function (d) {
    if (d.aktif === false) return false;      // dijeda memang sengaja tak diawasi
    return (d.availability !== null && d.availability < 99) ||
           d.insiden >= 3 || d.is_reachable === false;
  }).sort(function (a, b) {
    return (a.availability === null ? 101 : a.availability) -
           (b.availability === null ? 101 : b.availability);
  });

  if (!perlu.length) {
    var aman = el("div", "aman-kotak",
      "Tidak ada perangkat yang memerlukan perhatian pada periode ini. " +
      "Seluruh perangkat aktif berada di atas 99% ketersediaan dan sedang " +
      "merespons.");
    perhatian.appendChild(aman);
  } else {
    perlu.forEach(function (d) {
      var k = el("div", "perhatian-kotak");
      k.appendChild(el("div", "nama",
        d.name + "  (" + d.ip_address + (d.location ? ", " + d.location : "") + ")"));
      k.appendChild(el("div", "angka",
        "Ketersediaan " +
        (d.availability === null ? "-" : d.availability.toFixed(2) + "%") +
        "  •  " + d.insiden + " gangguan  •  total tidak merespons " +
        d.total_down_teks +
        (d.is_reachable === false ? "  •  SEDANG TIDAK MERESPONS" : "")));

      // The reason for highlighting is written explicitly, not left for the reader to guess
      var sebab = [];
      if (d.is_reachable === false) sebab.push("sedang tidak merespons");
      if (d.availability !== null && d.availability < 99)
        sebab.push("ketersediaan di bawah 99%");
      if (d.insiden >= 3) sebab.push(d.insiden + " gangguan pada periode ini");
      // Stability is decided by Python (`hitung_kestabilan()` in report_service.py): the current state with hysteresis (3 or more disruptions in 15 minutes, recovered after 10 quiet minutes), not a count over the report period.
      if (d.flapping) {
        sebab.push("sedang tidak stabil" +
                   (d.tidak_stabil_lama_teks ? " (sejak " + d.tidak_stabil_lama_teks + ")" : ""));
      }
      k.appendChild(el("div", "sebab", "Alasan disorot: " + sebab.join("; ") + "."));
      perhatian.appendChild(k);
    });
  }

  var tb = document.getElementById("baris-device");
  tb.innerHTML = "";
  (s.devices_semua || s.devices).forEach(function (d) {
    var status = d.aktif === false ? "DIJEDA"
               : d.is_reachable === true ? "UP"
               : d.is_reachable === false ? "DOWN" : "-";
    var kelasStatus = status === "UP" ? "hijau"
                    : status === "DOWN" ? "merah" : "abu";
    var tr = el("tr");
    var tdS = el("td", "tengah " + kelasStatus, status);
    tr.appendChild(tdS);
    tr.appendChild(el("td", null, d.name));
    tr.appendChild(el("td", null, d.ip_address));
    tr.appendChild(el("td", null, d.location || "-"));
    tr.appendChild(el("td", "angka " + kelasAvail(d.availability),
      d.availability === null ? "-" : d.availability.toFixed(3) + "%"));
    var tdIns = el("td", "angka", String(d.insiden));
    if (d.flapping) {
      var tandai = el("span", null,
        " (tidak stabil" + (d.tidak_stabil_lama_teks ? " · " + d.tidak_stabil_lama_teks : "") + ")");
      tandai.style.cssText = "font-size:8pt;font-style:italic;";
      tdIns.appendChild(tandai);
    }
    tr.appendChild(tdIns);
    tr.appendChild(el("td", null, d.total_down_teks));
    tr.appendChild(el("td", "angka",
      d.avg_latency_ms === null ? "-" : d.avg_latency_ms + " ms"));
    tb.appendChild(tr);
  });
}

async function gambarGangguan(devices) {
  var tb = document.getElementById("baris-gangguan");
  tb.innerHTML = "";

  // Each device's history is fetched and merged into one event timeline.
  var semua = [];
  for (var i = 0; i < devices.length; i++) {
    var d = devices[i];
    try {
      var res = await fetch("/api/devices/" + d.id +
                            "/history?period=" + periode + "&limit=500&bg=true");
      var h = await res.json();
      (h.riwayat || []).forEach(function (g) { semua.push({ d: d, g: g }); });
    } catch (e) { /* one failing device does not fail the report */ }
  }
  semua.sort(function (a, b) { return a.g.mulai < b.g.mulai ? 1 : -1; });

  document.getElementById("ket-gangguan").textContent =
    semua.length
      ? "Seluruh gangguan pada periode ini, diurutkan dari yang terbaru. " +
        "Sebab diambil dari pemeriksaan otomatis saat ping gagal."
      : "";

  if (!semua.length) {
    var kosong = el("tr");
    var td = el("td", "tengah abu", "Tidak ada gangguan pada periode ini");
    td.setAttribute("colspan", "6");
    kosong.appendChild(td);
    tb.appendChild(kosong);
    return;
  }

  semua.forEach(function (x, i) {
    var tr = el("tr");
    tr.appendChild(el("td", "tengah", String(i + 1)));
    tr.appendChild(el("td", null, x.d.name));
    tr.appendChild(el("td", null, waktuLengkap(x.g.mulai)));
    tr.appendChild(el("td", x.g.berlangsung ? "kuning" : null,
      x.g.berlangsung ? "belum pulih" : waktuLengkap(x.g.selesai)));
    tr.appendChild(el("td", null,
      x.g.durasi_teks + (x.g.berlangsung ? " (berjalan)" : "")));
    tr.appendChild(el("td", null, x.g.kategori_teks));
    tb.appendChild(tr);
  });
}

function tulisCatatan(s) {
  var c = document.getElementById("catatan");
  c.innerHTML = "";
  var isi = [
    "Ketersediaan dihitung atas lama pemantauan yang sebenarnya, bukan " +
    "diandaikan periode penuh. Perangkat yang baru mulai dipantau akan " +
    "menunjukkan angka yang lebih peka terhadap satu gangguan.",
    "Penyebab gangguan berasal dari pemeriksaan otomatis saat ping gagal: " +
    "“Tidak ada respons” berarti ping gagal dan tidak ada port TCP " +
    "yang menjawab; “Ping diblokir” berarti ping gagal tetapi port " +
    "TCP masih menjawab. Penyebab fisik seperti listrik padam, kabel lepas, " +
    "atau perangkat yang berhenti bekerja tidak dapat dibedakan dari jaringan.",
    "Perangkat yang dijeda tidak ikut menghitung angka keseluruhan, namun " +
    "riwayat gangguannya tetap tersimpan dan ditampilkan.",
  ];
  if (!s.periode_penuh) {
    isi.unshift("Periode yang diminta belum terpenuhi seluruhnya. Angka pada " +
      "laporan ini dihitung dari " + (s.diamati_teks || "-") + " pemantauan.");
  }
  isi.forEach(function (t, i) {
    c.appendChild(el("div", null, (i + 1) + ". " + t));
  });

  var kaki = document.getElementById("kaki");
  kaki.innerHTML = "";
  kaki.appendChild(el("div", null,
    "Dibuat otomatis oleh NSM (Network Status Monitor)"));
  kaki.appendChild(el("div", "kanan",
    "Data per " + waktuLengkap(s.selesai)));
}

async function muat() {
  var status = document.getElementById("status");
  status.textContent = "Menyusun laporan…";
  try {
    var r = await fetch("/api/report/summary?period=" + periode);
    var s = await r.json();
    gambar(s);
    tulisCatatan(s);
    await gambarGangguan(s.devices_semua || s.devices);
    document.getElementById("unduh-excel").setAttribute(
      "href", "/report/export?period=" + periode);
    document.getElementById("unduh-word").setAttribute(
      "href", "/report/export-word?period=" + periode);
    status.textContent = "Siap dicetak";
    if (autoCetak) {
      autoCetak = false;
      setTimeout(function () { window.print(); }, 500);
    }
  } catch (e) {
    status.textContent = "Gagal mengambil data";
  }
}

document.querySelectorAll("#kendali .pil").forEach(function (p) {
  if (p.getAttribute("data-p") === periode) p.classList.add("aktif");
  p.addEventListener("click", function () {
    periode = p.getAttribute("data-p");
    document.querySelectorAll("#kendali .pil").forEach(function (x) {
      x.classList.remove("aktif");
    });
    p.classList.add("aktif");
    history.replaceState(null, "", "/report/cetak?period=" + periode);
    muat();
  });
});
document.getElementById("cetak").addEventListener("click", function () {
  window.print();
});

muat();
