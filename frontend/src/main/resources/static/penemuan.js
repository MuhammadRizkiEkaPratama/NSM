/*
 * Device discovery: scan, identify, offer, never add. No path adds a device without someone pressing "Setujui", and added devices start inactive.
 * All decisions are in Python; this file renders and passes through the rejection reason as written.
 */
function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function kosongkan(n) { while (n.firstChild) n.removeChild(n.firstChild); }

function metaNilai(nama) {
  var m = document.querySelector('meta[name="' + nama + '"]');
  return m ? m.getAttribute("content") : "";
}

function kirimJson(url, badan) {
  var header = { "Content-Type": "application/json" };
  var namaHeader = metaNilai("_csrf_header");
  if (namaHeader) header[namaHeader] = metaNilai("_csrf");
  return ambilJson(url, {
    method: "POST", headers: header, body: JSON.stringify(badan || {})
  });
}

/* Rejection reason from Python (FastAPI `detail`), taken from `e.badan` set by `ambilJson`; falls back to anything available. */
function pesanGalat(e) {
  if (e && e.badan) {
    if (typeof e.badan.detail === "string") return e.badan.detail;
    if (e.badan.detail) return JSON.stringify(e.badan.detail);
    if (typeof e.badan.ditolak === "string") return e.badan.ditolak;
  }
  return e && e.message ? e.message : String(e);
}

/* Evidence level of the platform definition, as a badge. A device matched to a `dokumentasi` definition is recognized by sysObjectID, but its platform commands were never run on a real device; the approver should know before approving. Reuses the yellow `menunggu` badge. */
function lencanaBukti(teruji) {
  var kelas = { lab: "lencana-up", rekaman: "lencana-netral",
                dokumentasi: "lencana-menunggu" }[teruji] || "lencana-netral";
  var judul = {
    lab: "Perintah platform ini pernah dijalankan pada perangkat sungguhan.",
    rekaman: "Penguraiannya diuji terhadap keluaran asli yang direkam.",
    dokumentasi: "Disusun dari dokumentasi vendor -- BELUM PERNAH dijalankan "
               + "pada perangkat mana pun. Pengenalannya bisa benar, tetapi "
               + "tidak ada yang pernah membuktikannya."
  }[teruji] || "";
  var s = el("span", "lencana " + kelas, teruji);
  if (judul) s.title = judul;
  return s;
}

function selPlatform(t) {
  var td = el("td");
  if (!t.platform) {
    // Unrecognized is not a failure: ping, TCP, and service checks are vendor-neutral. Only config reading and the write path are missing.
    var kosong = el("span", "redup kecil", "belum dikenali");
    kosong.title = t.catatan || "";
    td.appendChild(kosong);
    return td;
  }
  td.appendChild(el("div", null, t.keterangan_platform || t.platform));
  var bawah = el("div", "kecil");
  bawah.appendChild(lencanaBukti(t.teruji));
  if (t.sysobjectid) {
    bawah.appendChild(document.createTextNode(" "));
    var oid = el("span", "mono redup", t.sysobjectid);
    oid.title = "sysObjectID yang dijawab perangkat";
    bawah.appendChild(oid);
  }
  td.appendChild(bawah);
  return td;
}

function selKeputusan(t) {
  var td = el("td");

  if (t.status === "disetujui") {
    var sudah = el("span", "lencana lencana-up", "sudah jadi perangkat");
    sudah.title = "Device #" + t.device_id + ", dibuat dalam keadaan BELUM AKTIF.";
    td.appendChild(sudah);
    return td;
  }
  if (t.status === "diabaikan") {
    var abai = el("span", "lencana lencana-netral", "diabaikan");
    abai.title = "Keputusan ini BERTAHAN: alamat ini tidak akan muncul lagi "
               + "di daftar tunggu walau ditemukan lagi.";
    td.appendChild(abai);
    return td;
  }

  var kotak = el("div", "aksi-temuan");

  var setuju = el("button", "tombol tombol-utama", "Setujui");
  setuju.type = "button";
  setuju.title = "Jadikan perangkat. Dibuat BELUM AKTIF -- belum di-ping, "
               + "belum menghasilkan insiden.";
  setuju.addEventListener("click", function () { mintaSetujui(t, setuju); });
  kotak.appendChild(setuju);

  var abaikan = el("button", "tombol", "Abaikan");
  abaikan.type = "button";
  abaikan.title = "Tandai bukan perangkat kita. Keputusannya BERTAHAN.";
  abaikan.addEventListener("click", function () { mintaAbaikan(t, abaikan); });
  kotak.appendChild(abaikan);

  td.appendChild(kotak);
  return td;
}

/* The device name is asked for, not derived from the address, because auto-names would never be renamed. */
function mintaSetujui(t, tombol) {
  var nama = window.prompt(
    "Nama perangkat untuk " + t.ip_address + "?\n\n"
    + "Perangkat dibuat dalam keadaan BELUM AKTIF -- ia belum akan di-ping "
    + "maupun menghasilkan insiden sampai kamu menyalakannya di halaman "
    + "device.", "");
  if (nama === null) return;
  nama = nama.trim();
  if (!nama) {
    lapor(t, "Nama tidak boleh kosong.", true);
    return;
  }
  tombol.disabled = true;
  kirimJson("/api/penemuan/" + t.id + "/setujui", { nama: nama })
    .then(function (h) {
      lapor(t, "Dibuat sebagai device #" + h.device_id + " (" + h.nama
               + "), BELUM AKTIF. Isi kredensial dan ambangnya di halaman "
               + "device, lalu aktifkan.", false);
      muatDaftar();
    })
    .catch(function (e) {
      tombol.disabled = false;
      lapor(t, pesanGalat(e), true);
    });
}

function mintaAbaikan(t, tombol) {
  if (!window.confirm(
        "Tandai " + t.ip_address + " sebagai BUKAN perangkat kita?\n\n"
        + "Keputusan ini bertahan: alamat itu tidak akan muncul lagi di "
        + "daftar tunggu walau ditemukan lagi pada pemindaian berikutnya.")) {
    return;
  }
  tombol.disabled = true;
  kirimJson("/api/penemuan/" + t.id + "/abaikan")
    .then(function () { muatDaftar(); })
    .catch(function (e) {
      tombol.disabled = false;
      lapor(t, pesanGalat(e), true);
    });
}

/* Messages are shown next to their row, not in one box far above it where they would be missed. */
function lapor(t, teks, galat) {
  var baris = document.getElementById("temuan-" + t.id);
  if (!baris) return;
  var lama = baris.querySelector(".kabar-temuan");
  if (lama) lama.parentNode.removeChild(lama);
  var td = baris.lastChild;
  td.appendChild(el("div", "kabar-temuan kecil " + (galat ? "pesan-galat" : "redup"), teks));
}

function gambarDaftar(d) {
  var tb = document.getElementById("baris-penemuan");
  if (!tb) return;
  kosongkan(tb);

  var daftar = (d && d.temuan) || [];
  if (!daftar.length) {
    var tr = el("tr");
    var td = el("td", "redup",
      d && d.status === "baru"
        ? "Belum ada temuan yang menunggu keputusan. Pindai sebuah jaringan di atas."
        : "Tidak ada temuan dengan status itu.");
    td.colSpan = 6;
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }

  daftar.forEach(function (t) {
    var tr = el("tr");
    tr.id = "temuan-" + t.id;

    var tdIp = el("td");
    tdIp.appendChild(el("div", "mono", t.ip_address));
    if (t.rtt_ms !== null && t.rtt_ms !== undefined) {
      tdIp.appendChild(el("div", "kecil redup", t.rtt_ms + " ms"));
    }
    tr.appendChild(tdIp);

    var tdPort = el("td", "mono",
      (t.port_terbuka && t.port_terbuka.length) ? t.port_terbuka.join(", ") : "-");
    if (!t.port_terbuka || !t.port_terbuka.length) {
      tdPort.className = "redup";
      tdPort.title = "Menjawab ping, tetapi tidak satu pun dari port 22/80/443/161 "
                   + "menerima koneksi. Itu keadaan yang wajar -- perangkat bisa "
                   + "hidup tanpa satu pun layanan yang dipindai.";
    }
    tr.appendChild(tdPort);

    tr.appendChild(selPlatform(t));
    tr.appendChild(el("td", "kecil", t.pertama_terlihat ? waktuLengkap(t.pertama_terlihat) : "-"));
    tr.appendChild(el("td", "kecil", t.terakhir_terlihat ? waktuLengkap(t.terakhir_terlihat) : "-"));
    tr.appendChild(selKeputusan(t));
    tb.appendChild(tr);
  });
}

function muatDaftar() {
  var sel = document.getElementById("saring-status");
  var status = sel ? sel.value : "baru";
  ambilJson("/api/penemuan?status=" + encodeURIComponent(status))
    .then(gambarDaftar)
    .catch(function (e) {
      var tb = document.getElementById("baris-penemuan");
      if (!tb) return;
      kosongkan(tb);
      var tr = el("tr");
      var td = el("td", "redup", "Gagal memuat: " + pesanGalat(e));
      td.colSpan = 6;
      tr.appendChild(td);
      tb.appendChild(tr);
    });
}

function gambarHasilPindai(h) {
  var w = document.getElementById("hasil-pindai");
  if (!w) return;
  kosongkan(w);

  var kotak = el("div", "kotak-pratinjau");
  var ringkas = el("div");
  ringkas.appendChild(el("b", null, h.total + " alamat menjawab"));
  ringkas.appendChild(document.createTextNode(
    " di " + h.jaringan + " -- " + h.baru + " baru, "
    + h.diperbarui + " sudah pernah terlihat."));
  kotak.appendChild(ringkas);

  if (!h.total) {
    kotak.appendChild(el("div", "kecil redup",
      "Tidak ada yang menjawab. Itu bukan kegagalan: rentangnya bisa saja "
      + "memang kosong, atau perangkat di dalamnya tidak membalas ping."));
  } else {
    kotak.appendChild(el("div", "kecil redup",
      "Semuanya masuk daftar tunggu di bawah. Tidak satu pun ditambahkan "
      + "sebagai perangkat."));
  }
  w.appendChild(kotak);
}

function pindai() {
  var isian = document.getElementById("jaringan");
  var tombol = document.getElementById("tombol-pindai");
  var w = document.getElementById("hasil-pindai");
  var jaringan = (isian.value || "").trim();
  if (!jaringan) {
    kosongkan(w);
    w.appendChild(el("div", "pesan-galat", "Isi dulu jaringan yang mau dipindai."));
    return;
  }

  // The button is disabled during a scan: a /24 scan takes tens of seconds and repeat clicks would send more packets.
  tombol.disabled = true;
  var teksAsli = tombol.textContent;
  tombol.textContent = "Memindai…";
  kosongkan(w);
  w.appendChild(el("div", "kecil redup",
    "Mengirim ping ke tiap alamat di " + jaringan
    + ". Satu /24 memakan sekitar setengah menit."));

  kirimJson("/api/penemuan/pindai", { jaringan: jaringan })
    .then(function (h) {
      gambarHasilPindai(h);
      var sel = document.getElementById("saring-status");
      if (sel) sel.value = "baru";
      muatDaftar();
    })
    .catch(function (e) {
      kosongkan(w);
      w.appendChild(el("div", "pesan-galat", pesanGalat(e)));
    })
    .then(function () {
      tombol.disabled = false;
      tombol.textContent = teksAsli;
    });
}

document.addEventListener("DOMContentLoaded", function () {
  var tombol = document.getElementById("tombol-pindai");
  if (tombol) tombol.addEventListener("click", pindai);

  var isian = document.getElementById("jaringan");
  if (isian) {
    isian.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); pindai(); }
    });
  }

  var sel = document.getElementById("saring-status");
  if (sel) sel.addEventListener("change", muatDaftar);

  muatDaftar();
});
