/* SSH data page for one device. Some command output is parsed into numbers and bars; if parsing fails the section is skipped and the raw text is still shown below. */

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

// ---------------------------------------------------------------------------
// Pengurai keluaran perintah
// ---------------------------------------------------------------------------

/* "1.6Gi", "829Mi", "25G", "512K" -> byte count; null if not recognized. */
function keByte(teks) {
  var m = String(teks).trim().match(/^([\d.]+)\s*([KMGTP]?)i?B?$/i);
  if (!m) return null;
  var angka = parseFloat(m[1]);
  if (!isFinite(angka)) return null;
  var pangkat = { "": 0, K: 1, M: 2, G: 3, T: 4, P: 5 }[m[2].toUpperCase()];
  return angka * Math.pow(1024, pangkat);
}

function ukuranEnak(byte) {
  if (byte === null || byte === undefined) return "-";
  var satuan = ["B", "KB", "MB", "GB", "TB"];
  var i = 0;
  while (byte >= 1024 && i < satuan.length - 1) { byte /= 1024; i++; }
  return (byte >= 100 ? byte.toFixed(0) : byte.toFixed(1)) + " " + satuan[i];
}

function uraiMemori(teks) {
  if (!teks) return null;
  var baris = String(teks).split("\n").filter(function (b) {
    return /^\s*Mem\s*:/i.test(b);
  })[0];
  if (!baris) return null;
  var k = baris.trim().split(/\s+/);        // Mem: total used free shared buff/cache available
  var total = keByte(k[1]), pakai = keByte(k[2]);
  if (!total || pakai === null) return null;
  return { total: total, pakai: pakai, persen: Math.round(pakai / total * 100) };
}

function uraiDisk(teks) {
  if (!teks) return null;
  var baris = String(teks).split("\n").filter(function (b) {
    return /\d+%/.test(b);
  })[0];
  if (!baris) return null;
  var k = baris.trim().split(/\s+/);        // Filesystem Size Used Avail Use% Mounted
  var persen = null;
  k.forEach(function (t) {
    var m = t.match(/^(\d+)%$/);
    if (m) persen = parseInt(m[1], 10);
  });
  if (persen === null) return null;
  return { total: keByte(k[1]), pakai: keByte(k[2]), persen: persen };
}

/* Keluaran `uptime`: "... load average: 0.00, 0.06, 0.14" */
function uraiBeban(teks) {
  if (!teks) return null;
  var m = String(teks).match(/load average[s]?:\s*([\d.,\s]+)/i);
  if (!m) return null;
  var angka = m[1].split(",").map(function (x) { return parseFloat(x.trim()); })
                  .filter(function (x) { return isFinite(x); });
  return angka.length ? angka : null;
}

/* Cisco: "CPU utilization for five seconds: 3%/0%; one minute: 2%; ..." */
function uraiCpuCisco(teks) {
  if (!teks) return null;
  var m = String(teks).match(/five seconds:\s*(\d+)%/i);
  return m ? parseInt(m[1], 10) : null;
}

function warnaPersen(p) {
  if (p >= 90) return "#f87171";
  if (p >= 75) return "#facc15";
  return "#4ade80";
}

function ubin(judul, isi, kelasIsi, kecil, persen, istilah) {
  var u = el("div", "ubin");
  if (istilah && typeof jelaskan === "function") jelaskan(u, istilah);
  u.appendChild(el("div", "judul", judul));
  u.appendChild(el("div", "isi " + (kelasIsi || ""), isi));
  if (kecil) u.appendChild(el("div", "kecil", kecil));
  if (typeof persen === "number") {
    var bilah = el("div", "bilah-pakai");
    var isiBilah = el("i");
    isiBilah.style.width = Math.min(100, Math.max(0, persen)) + "%";
    isiBilah.style.background = warnaPersen(persen);
    bilah.appendChild(isiBilah);
    u.appendChild(bilah);
  }
  return u;
}

function blok(label, teks) {
  var b = el("div", "blok");
  var atas = el("div", "atas");
  atas.appendChild(el("span", "label", label));
  var salin = el("button", "salin", "Salin");
  salin.addEventListener("click", function () {
    navigator.clipboard.writeText(teks).then(function () {
      salin.textContent = "Tersalin";
      setTimeout(function () { salin.textContent = "Salin"; }, 1400);
    }).catch(function () {
      salin.textContent = "Gagal salin";
      setTimeout(function () { salin.textContent = "Salin"; }, 1400);
    });
  });
  atas.appendChild(salin);
  b.appendChild(atas);
  b.appendChild(el("pre", null, teks));
  return b;
}

var SUDAH_DIRINGKAS = ["Hostname", "OS", "Kernel", "Uptime", "Versi IOS"];

function gambarHasil(data) {
  var kotak = document.getElementById("hasil");
  kotak.innerHTML = "";
  // Must be cleared on every new fetch, otherwise refreshed data would stay dimmed.
  kotak.classList.remove("basi");

  /* Fetch time. The page is filled once on open or on "Ambil Ulang" with no auto-refresh (each refresh opens a new SSH session), so the timestamp shows how old the data is. */
  var diambil = new Date();
  var cap = el("div", "waktu-ambil", "Diambil ");
  // The value lives in its own element because `pasangWaktuRelatif` overwrites the whole content of its element every 20 seconds.
  var nilai = el("span");
  cap.appendChild(nilai);
  pasangWaktuRelatif(nilai, diambil);
  kotak.appendChild(cap);

  // After five minutes the content is dimmed so stale numbers do not look as fresh as new ones.
  setTimeout(function () {
    if (kotak.isConnected) kotak.classList.add("basi");
  }, 5 * 60 * 1000);

  var mem = uraiMemori(data["Memori"]);
  var disk = uraiDisk(data["Disk (/)"]);
  var beban = uraiBeban(data["Beban CPU (load average)"] || data["Uptime"]);
  var cpuCisco = uraiCpuCisco(data["CPU"]);

  // --- ubin ringkasan ---
  var ubinKotak = el("div");
  ubinKotak.id = "ubin";

  if (data["Hostname"]) ubinKotak.appendChild(ubin("Hostname", data["Hostname"]));
  if (data["OS"]) ubinKotak.appendChild(ubin("Sistem Operasi", data["OS"],
    null, data["Kernel"] ? "Kernel " + data["Kernel"] : null));
  if (data["Versi IOS"]) ubinKotak.appendChild(ubin("Versi IOS", data["Versi IOS"]));
  if (data["Uptime"]) ubinKotak.appendChild(ubin("Sudah Menyala", data["Uptime"]));

  if (mem) {
    ubinKotak.appendChild(ubin("Memori Terpakai", mem.persen + "%",
      mem.persen >= 90 ? "merah" : mem.persen >= 75 ? "kuning" : "hijau",
      ukuranEnak(mem.pakai) + " dari " + ukuranEnak(mem.total), mem.persen));
  }
  if (disk) {
    ubinKotak.appendChild(ubin("Disk Terpakai", disk.persen + "%",
      disk.persen >= 90 ? "merah" : disk.persen >= 75 ? "kuning" : "hijau",
      (disk.pakai ? ukuranEnak(disk.pakai) + " dari " + ukuranEnak(disk.total) : "partisi /"),
      disk.persen));
  }
  if (beban) {
    // Load average is a count of processes waiting for CPU, not a percent; 1.0 is roughly one fully used core. The big number is the 1-minute load.
    ubinKotak.appendChild(ubin(
      "Beban CPU",
      beban[0].toFixed(2),
      beban[0] >= 4 ? "merah" : beban[0] >= 2 ? "kuning" : "hijau",
      "rata-rata 5 menit " + (beban[1] !== undefined ? beban[1].toFixed(2) : "-")
        + " · 15 menit " + (beban[2] !== undefined ? beban[2].toFixed(2) : "-"),
      null,
      "beban-cpu"));
  }
  if (cpuCisco !== null) {
    ubinKotak.appendChild(ubin("CPU (5 detik)", cpuCisco + "%",
      cpuCisco >= 90 ? "merah" : cpuCisco >= 75 ? "kuning" : "hijau",
      null, cpuCisco));
  }

  if (ubinKotak.children.length) {
    kotak.appendChild(el("h2", null, "Ringkasan"));
    kotak.appendChild(ubinKotak);
  }

  kotak.appendChild(el("h2", null, "Keluaran Lengkap"));
  Object.keys(data).forEach(function (label) {
    var isi = String(data[label]);
    if (SUDAH_DIRINGKAS.indexOf(label) >= 0 && isi.indexOf("\n") < 0) return;
    kotak.appendChild(blok(label, isi));
  });
}

function tampilGalat(pesan, nama) {
  document.getElementById("hasil").innerHTML = "";
  var g = el("div", "galat");
  g.appendChild(el("div", null, "Gagal mengambil data dari " + (nama || "device") + "."));
  g.appendChild(el("div", null, pesan));
  var bantu = el("div");
  bantu.style.marginTop = "10px";
  bantu.style.color = "#c98b8b";
  bantu.appendChild(el("div", null, "Yang biasanya jadi penyebab:"));
  ["Device baru saja mati atau kehilangan jaringan",
   "Layanan SSH di device tidak berjalan",
   "Username atau password device berubah",
   "Platform di database tidak cocok dengan device sebenarnya"
  ].forEach(function (t) { bantu.appendChild(el("div", null, "• " + t)); });
  g.appendChild(bantu);
  document.getElementById("hasil").appendChild(g);
}

// ---------------------------------------------------------------------------
// Muat
// ---------------------------------------------------------------------------
var devicePunya = null;

async function muatKepala() {
  try {
    var r = await fetch("/api/devices");
    var semua = await r.json();
    var d = semua.filter(function (x) { return x.id === DEVICE_ID; })[0];
    if (!d) return;
    devicePunya = d;

    var jenis = jenisIkon(d);
    var kotakIkon = document.getElementById("kotak-ikon");
    kotakIkon.innerHTML = "";
    kotakIkon.appendChild(ikonDevice(jenis, d.is_reachable, 50));

    document.getElementById("nama").textContent = d.name;
    var sub = document.getElementById("sub");
    sub.innerHTML = "";
    sub.appendChild(titikStatus(d.is_reachable));
    sub.appendChild(el("span",
      d.is_reachable ? "hijau" : "merah",
      d.is_reachable ? " UP" : " DOWN"));
    sub.appendChild(el("span", null,
      "  •  " + d.ip_address + "  •  " + (NAMA_JENIS[jenis] || jenis) +
      "  •  platform " + (d.platform || "belum diisi")));

    document.getElementById("ke-riwayat")
      .setAttribute("href", "/report/device/" + DEVICE_ID + "?period=24h");
  } catch (e) { /* a header that fails to load does not block fetching the data */ }
}

async function ambilData() {
  document.getElementById("tunggu").style.display = "block";
  document.getElementById("hasil").innerHTML = "";
  try {
    var r = await fetch("/api/devices/" + DEVICE_ID + "/info");
    var j = await r.json();
    document.getElementById("tunggu").style.display = "none";
    if (j.error) {
      tampilGalat(j.error, j.device);
      return;
    }
    gambarHasil(j.data);
  } catch (e) {
    document.getElementById("tunggu").style.display = "none";
    tampilGalat("Tidak bisa menghubungi backend NSM.", null);
  }
}

document.getElementById("ambil-ulang").addEventListener("click", ambilData);

muatKepala();
ambilData();
