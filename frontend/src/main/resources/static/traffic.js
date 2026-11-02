/*
 * Traffic page: who fetches what, and how much. All numbers come ready-made from Python.
 * Anti-XSS: textContent and createElement only; IPs, paths, and User-Agents are attacker-controlled.
 * Refresh is 30 seconds since the poller reads the access log every 60 seconds.
 */

var periode = (typeof PERIODE_AWAL === "string") ? PERIODE_AWAL : "24h";

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

function kartu(judul, angka, sub, istilah) {
  var c = el("div", "kartu");
  var j = el("div", "judul", judul);
  if (istilah && window.jelaskan) jelaskan(j, istilah);
  c.appendChild(j);
  c.appendChild(el("div", "angka", angka));
  if (sub) c.appendChild(el("div", "sub", sub));
  return c;
}

function barisKosong(tbody, kolom, teks) {
  var tr = el("tr");
  var td = el("td", "redup", teks);
  td.colSpan = kolom;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

/* Count in a tab header (`.tab-cacah`, set up by `js/tab.js`). Deferred until the page is parsed because the tab bar does not exist in the DOM before that. */
function tabCacah(kunci, angka, nol) {
  function pasang() {
    if (window.NSMTab && NSMTab.cacah) NSMTab.cacah(kunci, angka, nol ? "nol" : "");
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pasang);
  } else {
    pasang();
  }
}

/* Who talks to whom, for all protocols. The two byte columns are named from the monitored device's point of view, so direction cannot be swapped. */
function gambarPercakapan(f) {
  var tb = document.getElementById("baris-percakapan");
  var rk = document.getElementById("ringkas-flow");
  if (!tb) return;
  kosongkan(tb);
  if (rk) kosongkan(rk);

  var daftar = f.percakapan || [];
  if (!daftar.length) {
    barisKosong(tb, 6, "Belum ada koneksi TCP terekam pada periode ini. "
      + "Koneksi dibaca lewat SSH dari device Linux yang sedang hidup.");
    tabCacah("percakapan", 0, true);
    return;
  }

  if (rk) {
    var teks = f.koneksi + " koneksi terekam, dari " + f.lawan_jumlah
      + " alamat berbeda. Total " + f.total_masuk_teks + " masuk ke perangkat "
      + "yang dipantau dan " + f.total_keluar_teks + " keluar darinya.";

    // "No new addresses" and "cannot yet tell which are new" differ; the second must be stated explicitly.
    if (!f.bisa_nilai_baru) {
      teks += " Belum ada penilaian alamat baru: riwayat percakapan belum "
        + "mundur cukup jauh untuk dibandingkan dengan periode ini.";
    } else if (f.lawan_baru) {
      teks += " " + f.lawan_baru + " di antaranya baru pertama kali terlihat.";
    } else {
      teks += " Tidak ada alamat yang baru pertama kali terlihat.";
    }
    rk.textContent = teks;
  }
  tabCacah("percakapan", f.koneksi);

  daftar.forEach(function (p) {
    var tr = el("tr");

    var tdA = selKlien(el("td"), p.ip, p.device);
    if (p.luar_jaringan) {
      tdA.firstChild.appendChild(el("span", "tanda-luar", "di luar jaringan lab"));
    }
    if (p.baru_terlihat) {
      tdA.firstChild.appendChild(el("span", "tanda-baru", "baru terlihat"));
    }
    // The DNS name goes below the address, not instead of it: reverse lookups are controlled by the address owner and may lie, and the address is what was actually recorded.
    if (p.nama_dns) {
      tdA.appendChild(el("div", "nama-dns", p.nama_dns));
    }
    tr.appendChild(tdA);

    var tdP = el("td");
    tdP.appendChild(el("div", null, (p.pintu && p.pintu.length)
      ? p.pintu.join(", ") : "port tidak dikenali"));
    if (p.device_lokal && p.device_lokal.length) {
      tdP.appendChild(el("div", "pintu-daftar",
        "di perangkat: " + p.device_lokal.join(", ")));
    }
    tr.appendChild(tdP);

    tr.appendChild(el("td", "angka", String(p.koneksi)));
    tr.appendChild(el("td", "byte", p.keluar_teks));
    tr.appendChild(el("td", "byte", p.masuk_teks));
    tr.appendChild(el("td", null, jam(p.terakhir)));
    tb.appendChild(tr);
  });
}

function gambarPintu(f) {
  var tb = document.getElementById("baris-pintu");
  if (!tb) return;
  kosongkan(tb);

  var daftar = f.pintu || [];
  if (!daftar.length) {
    barisKosong(tb, 6, "Belum ada koneksi TCP terekam pada periode ini.");
    tabCacah("pintu", 0, true);
    return;
  }
  tabCacah("pintu", daftar.length);

  // Short labels in table cells (SIEM badge style), with the full explanation in `title` (hover).
  var ARAH = { masuk: "Masuk", keluar: "Keluar", "?": "Tidak Diketahui" };
  var ARAH_JUDUL = {
    masuk: "Pihak lain menyambung KE perangkat ini (kita berperan server).",
    keluar: "Perangkat ini menyambung KELUAR ke pihak lain (kita berperan klien).",
    "?": "Arahnya tidak bisa ditentukan."
  };

  daftar.forEach(function (q) {
    var tr = el("tr");
    tr.appendChild(el("td", null, q.device));

    var tdL = el("td");
    tdL.appendChild(el("div", null, q.nama || "port " + q.port));
    if (q.nama) tdL.appendChild(el("div", "pintu-daftar", "port " + q.port));
    tr.appendChild(tdL);

    var lencanaArah = el("span", "arah", ARAH[q.arah] || q.arah);
    lencanaArah.title = ARAH_JUDUL[q.arah] || "";
    var tdArah = el("td");
    tdArah.appendChild(lencanaArah);
    tr.appendChild(tdArah);
    tr.appendChild(el("td", "angka", String(q.lawan)));
    tr.appendChild(el("td", "byte", q.keluar_teks));
    tr.appendChild(el("td", "byte", q.masuk_teks));
    tb.appendChild(tr);
  });
}

function gambar(d) {
  var kk = document.getElementById("kartu");
  kosongkan(kk);

  var f = d.flow || {};
  var dariNsm = (d.klien || []).reduce(function (a, k) { return a + (k.dari_nsm || 0); }, 0);

  // The first card's sub-label states its scope: only HTTP on web servers that have an access log.
  kk.appendChild(kartu("Terunduh lewat web", d.total_unduh_teks || "-",
    "dari access log saja, bukan seluruh jaringan", "access-log"));
  kk.appendChild(kartu("Permintaan web", String(d.total_permintaan || 0),
    "halaman dan berkas yang diminta", "access-log"));

  // Counted from both sources, not the access log alone.
  var jumlahAlamat = (typeof d.alamat_terlihat === "number")
    ? d.alamat_terlihat : (d.klien || []).length;
  var subAlamat = "dari access log dan koneksi TCP";
  if (f.lawan_luar) {
    subAlamat = f.lawan_luar + " di antaranya di luar jaringan lab";
  }
  kk.appendChild(kartu("Alamat terlihat", String(jumlahAlamat), subAlamat,
    f.lawan_luar ? "luar-jaringan-lab" : null));

  /* The fourth card names its divisor, so it reads as part of the requests total rather than a separate count (most requests come from NSM's own monitoring). */
  var totalPermintaan = d.total_permintaan || 0;
  var subNsm = totalPermintaan
    ? "dari " + totalPermintaan + " permintaan, sisanya "
      + (totalPermintaan - dariNsm) + " dari pengguna"
    : "pemeriksaan otomatis, ikut dihitung";
  kk.appendChild(kartu("Permintaan NSM sendiri", String(dariNsm), subNsm,
    "dari-nsm"));

  gambarPercakapan(f);
  gambarPintu(f);

  var tb = document.getElementById("baris-klien");
  kosongkan(tb);

  if (!d.klien || !d.klien.length) {
    var tr = el("tr");
    var td = el("td", "redup",
      "Belum ada permintaan web tercatat pada periode ini. Access log hanya "
      + "dibaca dari device yang punya layanan HTTP terdaftar di NSM.");
    td.colSpan = 4;
    tr.appendChild(td);
    tb.appendChild(tr);
    tabCacah("klien", 0, true);
    return;
  }
  tabCacah("klien", d.klien.length);

  d.klien.forEach(function (k) {
    var tr = el("tr");

    tr.appendChild(selKlien(el("td"), k.ip, k.device));

    var tdP = el("td", "angka", String(k.permintaan));
    if (k.dari_nsm) {
      tdP.appendChild(el("span", "lencana-nsm", k.dari_nsm + " dari NSM"));
    }
    tr.appendChild(tdP);

    tr.appendChild(el("td", "byte", k.unduh_teks));
    tr.appendChild(el("td", null, jam(k.terakhir)));
    tb.appendChild(tr);
  });

  gambarBerkas(d);
}

/* Anomaly findings. Built with textContent (`el()`) only: file names, addresses, and user-agents are written by the requester. */
function gambarAnomali(d) {
  var kotak = document.getElementById("anomali");
  if (!kotak) return;
  kosongkan(kotak);

  // The Anomaly panel border follows the most severe finding present. The default is neutral, not green, so it never claims "all clear" before data arrives.
  var panel = document.getElementById("panel-anomali");
  if (panel) {
    panel.classList.remove("ada-temuan-tinggi", "ada-temuan-sedang");
    var daftarKeparahan = (d.temuan || []).map(function (t) { return t.keparahan; });
    if (daftarKeparahan.indexOf("tinggi") >= 0) panel.classList.add("ada-temuan-tinggi");
    else if (daftarKeparahan.indexOf("sedang") >= 0) panel.classList.add("ada-temuan-sedang");
  }

  // Baseline state is shown first, including when it cannot be computed yet, so "zero spike findings" is not read as "no spikes".
  var kd = document.getElementById("dasar-anomali");
  if (kd) {
    kosongkan(kd);
    var gd = d.garis_dasar || {};
    if (gd.siap) {
      kd.className = "ket";
      // "Garis dasar" (baseline) is a term, so the glossary key is attached to that word only.
      var kata = el("b", null, "Garis dasar");
      if (window.jelaskan) jelaskan(kata, "garis-dasar");
      kd.appendChild(kata);
      kd.appendChild(document.createTextNode(": " + gd.byte_median_teks
        + " per jam, diambil dari median " + gd.jam_terkumpul
        + " jam yang berisi data. Inilah pembanding yang dipakai menilai "
        + "apakah sebuah angka menonjol atau biasa saja."));
    } else if (gd.alasan) {
      kd.className = "dasar-belum";
      kd.textContent = gd.alasan;
    }
  }

  var daftar = d.temuan || [];
  if (!daftar.length) {
    kotak.appendChild(el("div", "redup",
      "Tidak ada yang menonjol pada periode ini. "
      + (d.diperiksa || 0) + " permintaan pengguna diperiksa"
      + (d.dilewati_dari_nsm
         ? " (" + d.dilewati_dari_nsm + " permintaan NSM sendiri dilewati)."
         : ".")));
    return;
  }

  daftar.forEach(function (t) {
    var kartu = el("div", "kartu-anomali " + (t.keparahan || "rendah"));

    var kepala = el("div", "kepala-anomali");
    kepala.appendChild(el("span", "judul", t.judul));
    // `kapan_teks` is used when the time is a range ("29 Jul 16:00–19:00") rather than a single instant.
    kepala.appendChild(el("span", "kapan", t.kapan_teks || jam(t.kapan)));
    kartu.appendChild(kepala);

    var ba = el("div", "baris-angka");
    ba.appendChild(el("span", "nilai", t.angka));
    if (t.pembanding) ba.appendChild(el("span", "banding", t.pembanding));
    kartu.appendChild(ba);

    if (t.kenapa) kartu.appendChild(el("div", "alasan-anomali", t.kenapa));

    if (t.bukti && t.bukti.length) {
      var b = el("div", "bukti-anomali");
      t.bukti.forEach(function (x) {
        var bagian = [];
        if (x.ip) bagian.push(x.ip);
        if (x.path) bagian.push(x.path);
        if (x.jumlah) bagian.push(x.jumlah + "×");
        if (x.byte_teks) bagian.push(x.byte_teks);
        if (x.agen) bagian.push(x.agen);
        if (bagian.length) b.appendChild(el("div", null, bagian.join("  ")));
      });
      if (b.firstChild) kartu.appendChild(b);
    }

    kotak.appendChild(kartu);
  });
}

/* List of files actually fetched. File names come from the access log and are written by the requester, so everything is built with textContent (`el()`), never innerHTML. */
function gambarBerkas(d) {
  var tb = document.getElementById("baris-berkas");
  if (!tb) return;
  kosongkan(tb);

  var daftar = d.path || [];
  if (!daftar.length) {
    var tr0 = el("tr");
    var td0 = el("td", "redup",
      "Belum ada permintaan web tercatat pada periode ini. Nama berkas hanya "
      + "terbaca dari device yang punya layanan HTTP terdaftar di NSM.");
    td0.colSpan = 5;
    tr0.appendChild(td0);
    tb.appendChild(tr0);
    tabCacah("berkas", 0, true);
    return;
  }
  tabCacah("berkas", daftar.length);

  daftar.forEach(function (p) {
    var tr = el("tr");

    tr.appendChild(el("td", "path", p.path || "-"));

    var tdN = el("td", "angka", String(p.permintaan));
    // NSM's own requests are labeled, not dropped; `/hello.php` appearing thousands of times is monitoring.
    if (p.dari_nsm) {
      tdN.appendChild(el("span", "lencana-nsm", p.dari_nsm + " dari NSM"));
    }
    tr.appendChild(tdN);

    tr.appendChild(el("td", "byte", p.teks));
    tr.appendChild(el("td", "byte redup", p.rata_teks || "-"));
    tr.appendChild(el("td", null, jam(p.terakhir)));
    tb.appendChild(tr);
  });
}

/* SFTP transfers: the only part of this page that names people. An unknown name is shown as "(tidak diketahui)": the session started before NSM began reading the log, so its opening line was never seen. Such rows are kept because long sessions usually mean large files. */
/* One "person" cell: bold uid, with full name and title below. The uid is what the log actually records; name and title come from a directory copy that may have changed since. */
function selOrang(o) {
  var td = el("td", o.dikenali ? null : "tanpa-nama");
  td.appendChild(el("div", "nama-klien", o.pengguna));
  if (o.nama_lengkap || o.jabatan) {
    var ket = o.nama_lengkap || "";
    if (o.jabatan) ket += (ket ? " · " : "") + o.jabatan;
    td.appendChild(el("div", "ip-klien", ket));
  }
  return td;
}

/* Action labels from Python (see connectors/sftplog.py) are translated to common SIEM terms. Display only; raw values are used everywhere else. */
var AKSI_INGGRIS = {
  AMBIL: "UNDUH", KIRIM: "UNGGAH", BUKA: "BUKA",
  HAPUS: "HAPUS", GANTI_NAMA: "GANTI NAMA",
  BUAT_FOLDER: "BUAT FOLDER", HAPUS_FOLDER: "HAPUS FOLDER",
  // Copy-paste performed entirely on the server (SMB2 Server-Side Copy); labeled separately from a download plus upload.
  SALIN: "SALIN",
  SAMBUNG: "SAMBUNG", PUTUS: "PUTUS",
  // Shell commands over SSH (auditd), merged into the same event log as file activity.
  PERINTAH: "PERINTAH"
};

/* File type guessed from the file name extension, purely in the display layer. */
var JENIS_BERKAS = [
  [/\.(xlsx?|csv|ods)$/i, "Spreadsheet"],
  [/\.(docx?|odt|rtf)$/i, "Dokumen"],
  [/\.pdf$/i, "PDF"],
  [/\.(zip|rar|7z|tar|gz|tgz)$/i, "Arsip"],
  [/\.(jpe?g|png|gif|bmp|svg|webp)$/i, "Gambar"],
  [/\.(mp4|mkv|avi|mov|webm)$/i, "Video"],
  [/\.(sql|db|sqlite)$/i, "Basis Data"],
  [/\.(txt|log|md)$/i, "Teks"],
  [/\.(json|xml|ya?ml|conf|ini)$/i, "Konfigurasi"],
];

function jenisBerkas(jalur) {
  if (!jalur) return "-";
  for (var i = 0; i < JENIS_BERKAS.length; i++) {
    if (JENIS_BERKAS[i][0].test(jalur)) return JENIS_BERKAS[i][1];
  }
  var titik = jalur.lastIndexOf(".");
  var garis = Math.max(jalur.lastIndexOf("/"), jalur.lastIndexOf("\\"));
  if (titik > garis && titik < jalur.length - 1) {
    return jalur.slice(titik + 1).toUpperCase().slice(0, 8);
  }
  return "Berkas";
}

/* Final "truncated" row, inside the table so it paginates with it. Also called when not truncated so the old row disappears when the period changes. */
function catatanPotong(tbody, dipotong, batas, apa) {
  if (!tbody || !dipotong) return;
  var kolom = tbody.parentNode
    ? tbody.parentNode.querySelectorAll("thead th").length : 5;
  var tr = el("tr", "baris-potong");
  var td = el("td", "redup", "Hanya " + batas + " " + apa
    + " yang ditampilkan. Persempit periodenya untuk melihat yang lain.");
  td.setAttribute("colspan", String(kolom || 5));
  tr.appendChild(td);
  tbody.appendChild(tr);
}

function gambarSftp(d) {
  var tOrang = document.getElementById("baris-orang");
  var tBerkas = document.getElementById("baris-berkas-sftp");
  var tBaru = document.getElementById("baris-sftp-terbaru");
  var tRiwayat = document.getElementById("baris-riwayat-perintah");
  var catatan = document.getElementById("catatan-sftp");
  if (!tOrang || !tBerkas || !tBaru) return;

  kosongkan(tOrang);
  kosongkan(tBerkas);
  kosongkan(tBaru);
  if (tRiwayat) kosongkan(tRiwayat);
  if (catatan) kosongkan(catatan);

  if (!d || !d.ada_data) {
    var alasan = (d && d.alasan) || "Belum ada data.";
    barisKosong(tOrang, 6, alasan);
    barisKosong(tBerkas, 5, alasan);
    barisKosong(tBaru, 10, alasan);
    if (tRiwayat) barisKosong(tRiwayat, 5, alasan);
    tabCacah("sftp", 0, true);
    return;
  }

  if (catatan && d.catatan) catatan.appendChild(el("div", null, d.catatan));

  (d.orang || []).forEach(function (o) {
    var tr = el("tr");
    tr.appendChild(selOrang(o));
    tr.appendChild(el("td", "angka", String(o.kejadian)));
    tr.appendChild(el("td", "byte", o.ambil_teks));
    tr.appendChild(el("td", "byte", o.kirim_teks));
    var td = el("td", "path");
    if (o.berkas_terbesar) {
      td.appendChild(el("span", null, o.berkas_terbesar));
      td.appendChild(el("span", "redup", "  " + o.berkas_terbesar_teks));
    } else {
      td.appendChild(el("span", "redup", "-"));
    }
    tr.appendChild(td);
    tr.appendChild(el("td", null, jam(o.terakhir)));
    tOrang.appendChild(tr);
  });
  if (!(d.orang || []).length) barisKosong(tOrang, 6, "Belum ada kejadian.");

  (d.berkas || []).forEach(function (b) {
    var tr = el("tr");
    tr.appendChild(el("td", "path", b.jalur));
    tr.appendChild(el("td", "angka", b.kali + "x"));
    tr.appendChild(el("td", "angka", String(b.orang)));
    tr.appendChild(el("td", "byte", b.total_teks));
    tr.appendChild(el("td", null, jam(b.terakhir)));
    tBerkas.appendChild(tr);
  });
  if (!(d.berkas || []).length) {
    barisKosong(tBerkas, 5, "Belum ada berkas berpindah pada periode ini.");
  }

  (d.terbaru || []).forEach(function (r) {
    var tr = el("tr");
    var tdW = el("td");
    tdW.appendChild(el("div", null, jam(r.waktu)));
    // `jumlah_kali` > 1 means this row summarizes several identical real events (see `_gabung_sesi_baca()` in report_service.py); the badge says so.
    if (r.jumlah_kali > 1) {
      var badge = el("div", "redup",
        r.jumlah_kali + "× • " + r.durasi_teks);
      badge.setAttribute("data-petunjuk",
        "Berkas ini disentuh " + r.jumlah_kali + " kali berturut-turut "
        + "dalam rentang " + r.durasi_teks + " (dari " + jam(r.waktu_mulai)
        + " sampai " + jam(r.waktu) + "), digabung jadi satu baris supaya "
        + "tidak terbaca sebagai " + r.jumlah_kali + " tindakan terpisah. "
        + "Semua kejadian aslinya tetap tersimpan utuh di basis data.");
      tdW.appendChild(badge);
    }
    tr.appendChild(tdW);
    tr.appendChild(selOrang(r));
    var tdA = el("td");
    var lencanaAksi = el("span", "arah", AKSI_INGGRIS[r.aksi] || r.aksi);
    if (r.aksi === "SALIN") {
      lencanaAksi.setAttribute("data-petunjuk",
        "Copy-paste antar folder DI DALAM share yang sama. Bedanya dari "
        + "Unduh+Unggah terpisah: filenya tidak pernah keluar dari "
        + "server ke laptop lalu balik lagi -- servernya sendiri yang "
        + "menyalin di dalam disknya.");
    }
    tdA.appendChild(lencanaAksi);
    tr.appendChild(tdA);
    var tdJ = el("td", "path");
    tdJ.appendChild(el("span", null, r.jalur));
    // A rename shows both names.
    if (r.jalur_baru) {
      tdJ.appendChild(el("span", "redup", "  →  " + r.jalur_baru));
    }
    tr.appendChild(tdJ);
    // The Type column guesses from the file name suffix. Every row here is real file activity (SMB/SFTP); command rows live in the separate command history table.
    tr.appendChild(el("td", "redup", jenisBerkas(r.jalur)));
    tr.appendChild(el("td", "byte", r.ukuran_teks));
    tr.appendChild(el("td", "ip-klien", r.ip_klien || "-"));

    // Client machine name (%m from Samba). SFTP does not report it, so "-" means the protocol does not know it.
    tr.appendChild(el("td", null, r.mesin_klien || "-"));

    var tdProto = el("td");
    tdProto.appendChild(el("span", "arah", r.sumber || "SFTP"));
    tr.appendChild(tdProto);

    // Status has three states: Gagal (attempt rejected, the most noteworthy), Selesai (succeeded), and "-" (unknown, since SFTP does not record failures; deliberately not "Selesai").
    var tdS = el("td");
    if (r.hasil === "gagal") {
      var gagal = el("span", "hapus", "Gagal");
      gagal.setAttribute("data-petunjuk",
        "Percobaan ini DITOLAK sistem berkas — misalnya berkasnya sudah "
        + "tidak ada, atau orang ini tidak punya hak atasnya. Baris seperti "
        + "ini layak diperiksa lebih dulu daripada yang berhasil.");
      tdS.appendChild(gagal);
    } else if (r.hasil === "ok") {
      tdS.appendChild(el("span", "tambah", "Selesai"));
    } else {
      var tdk = el("span", "redup", "-");
      tdk.setAttribute("data-petunjuk",
        "Tidak diketahui: log SFTP tidak merekam percobaan yang gagal, jadi "
        + "NSM tidak bisa memastikan berhasil atau tidaknya.");
      tdS.appendChild(tdk);
    }
    tr.appendChild(tdS);
    tBaru.appendChild(tr);
  });
  if (!(d.terbaru || []).length) barisKosong(tBaru, 10, "Belum ada kejadian.");
  // If the period holds more than the server sent, say so; otherwise the summary count and the rows silently disagree.
  catatanPotong(tBaru, d.terbaru_dipotong, d.batas_log,
                "aktivitas berkas terbaru");

  if (tRiwayat) {
    (d.riwayat_perintah || []).forEach(function (p) {
      var tr = el("tr");
      tr.appendChild(el("td", null, jam(p.waktu)));
      tr.appendChild(selOrang(p));
      tr.appendChild(el("td", "path", p.perintah));
      tr.appendChild(el("td", "ip-klien", p.ip_klien || "-"));
      var tdS = el("td");
      if (p.hasil === "gagal") {
        var gagal = el("span", "hapus", "Gagal");
        gagal.setAttribute("data-petunjuk",
          "Perintah ini DITOLAK sistem -- misalnya mencoba menghapus/membuka "
          + "berkas yang bukan haknya. Baris seperti ini layak diperiksa "
          + "lebih dulu daripada yang berhasil.");
        tdS.appendChild(gagal);
      } else {
        tdS.appendChild(el("span", "tambah", "Selesai"));
      }
      tr.appendChild(tdS);
      tRiwayat.appendChild(tr);
    });
    if (!(d.riwayat_perintah || []).length) {
      barisKosong(tRiwayat, 5, "Belum ada perintah tercatat pada periode ini.");
    }
    catatanPotong(tRiwayat, d.perintah_dipotong, d.batas_log,
                  "perintah terbaru");
  }

  tabCacah("sftp", d.total_kejadian);
}

/* Reattach pagination after any table is drawn. The page pulls from three endpoints that finish at different times, and `terapkan()` is cheap and idempotent. */
function rapikanTabel() {
  if (window.halamanTabel) halamanTabel.terapkan();
}

function muat() {
  var meta = document.getElementById("meta");

  // Separate request from /api/traffic on purpose: the anomaly check reads the whole period plus the previous one and is much slower, and its failure must not take down the other numbers.
  ambilJson("/api/traffic/anomali?period=" + encodeURIComponent(periode))
    .then(gambarAnomali).then(rapikanTabel)
    .catch(function (e) {
      var kotak = document.getElementById("anomali");
      if (!kotak) return;
      kosongkan(kotak);
      kotak.appendChild(el("div", "redup", "Gagal memuat temuan: " + e));
    });

  // Separate request for the same reason (different source: the SFTP log).
  ambilJson("/api/traffic/berkas?period=" + encodeURIComponent(periode))
    .then(gambarSftp).then(rapikanTabel)
    .catch(function (e) {
      var tb = document.getElementById("baris-orang");
      if (!tb) return;
      kosongkan(tb);
      barisKosong(tb, 6, "Gagal memuat perpindahan berkas: " + e);
    });

  ambilJson("/api/traffic?period=" + encodeURIComponent(periode))
    .then(function (d) {
      gambar(d);
      meta.textContent = "Diperbarui " + new Date().toLocaleTimeString("id-ID");
      rapikanTabel();
    })
    .catch(function (e) {
      meta.textContent = (e && e.sesiHabis) ? e.message : "Gagal memuat";
      if (window.console) console.error("gagal memuat lalu lintas", e);
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
      // The period is kept in the URL so the page can be refreshed or shared.
      history.replaceState(null, "", "/traffic?period=" + periode);
      muat();
    }
    p.addEventListener("click", pilih);
    p.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pilih(); }
    });
  });
}

if (window.NSMTab) NSMTab.pasang(".tab-bar");
pasangPeriode();
muat();

// Stop refreshing while the tab is hidden and fetch once when it becomes visible again.
setInterval(function () { if (!document.hidden) muat(); }, 30000);
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) muat();
});
