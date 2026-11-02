/*
 * Backup monitor page. The healthy/problem verdict always comes from Python (backup_status.py);
 * JavaScript never judges a backup. Anti-XSS: textContent and createElement only (file names and
 * system error messages are untrusted). No auto-refresh, since backup state changes about once
 * a day; there is a Recheck button instead.
 */

var berkasTerbuka = null;

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

/*
 * Size in MB, always two decimals. Python sends round(x, 2) numbers, which drop trailing zeros
 * (0.10 becomes 0.1); the value stays numeric because it is summed, only the display is unified.
 */
function mb(n) {
  return (n === null || n === undefined) ? "-" : Number(n).toFixed(2) + " MB";
}

function waktuTampil(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}

function kosongkan(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/* ---------------------------------------------------------------------- */

/* One short fact chip for the verdict banner, scannable one by one instead of one long sentence. */
function fakta(label, nilai) {
  var f = el("span", "fakta");
  f.appendChild(document.createTextNode(label + " "));
  f.appendChild(el("b", null, nilai));
  return f;
}

function gambarVonis(d) {
  var kotak = document.getElementById("vonis");
  kosongkan(kotak);
  var lain = !!d.mesin_lain;

  /*
   * Four states. `mesin_lain` (backup does not run on this machine: the primary lab instance runs on
   * Linux while backups are scheduled from a Windows laptop) no longer means "cannot be checked":
   * if that machine reports its state (`lapor_backup.py` -> table `backup_laporan`), the verdict
   * follows the report, with its origin and age shown separately.
   *   this machine, healthy        -> ok
   *   this machine, problem        -> danger
   *   other machine + report       -> follow the report, noting its origin
   *   other machine, no report     -> other (the only empty case)
   */
  var pakaiLaporan = lain && !!d.dari_laporan;
  var lainKosong = lain && !d.dari_laporan;
  kotak.className = lainKosong ? "lain" : (d.sehat ? "aman" : "bahaya");

  var lambang = el("div", "lambang");
  lambang.appendChild(ikonUI(lainKosong ? "info"
    : (d.sehat ? "ceklis" : "peringatan"), 20));
  kotak.appendChild(lambang);

  var isiKotak = el("div", "isi");
  isiKotak.appendChild(el("h2", null, lainKosong
    ? "Backup dijalankan di mesin lain"
    : (d.sehat ? "Pencadangan berjalan normal" : "Pencadangan bermasalah")));

  /* Report origin and age, right under the title: a reader seeing "running normally" must know at once that it is what another machine reported hours ago. */
  if (pakaiLaporan) {
    var nota = el("div", "ket-lain" + (d.laporan_basi ? " basi" : ""),
                  d.mesin_lain_ket || "");
    isiKotak.appendChild(nota);
  }

  // On a machine where backups do not run, the fact rows and complaint list would be empty or misleading, so one explanation of where the backup actually lives replaces them.
  if (lainKosong) {
    if (d.mesin_lain_ket) {
      isiKotak.appendChild(el("div", "ket-lain", d.mesin_lain_ket));
    }
    kotak.appendChild(isiKotak);
    return;
  }

  var baris = el("div", "baris-fakta");
  if (d.terbaru) {
    baris.appendChild(fakta("terakhir", waktuTampil(d.terbaru.waktu)));
    if (d.umur_teks) baris.appendChild(fakta("umur", d.umur_teks));
    baris.appendChild(fakta("ukuran", mb(d.terbaru.ukuran_mb)));
    baris.appendChild(fakta("tersimpan", d.jumlah_berkas + " berkas"));
    baris.appendChild(fakta("lokasi kedua", d.jumlah_berkas_kedua + " berkas"));
  } else {
    baris.appendChild(el("span", "fakta", "Belum ada berkas backup sama sekali"));
  }
  isiKotak.appendChild(baris);

  if (d.masalah && d.masalah.length) {
    var ul = el("ul");
    d.masalah.forEach(function (m) { ul.appendChild(el("li", null, m)); });
    isiKotak.appendChild(ul);
  }
  kotak.appendChild(isiKotak);
}

/*
 * `arti` is shown as a hover on the value (dotted underline, the app-wide marker for "more
 * info here") instead of a paragraph under each card. Cards without `arti` get no underline.
 */
function selJadwal(label, nilai, kelas, arti) {
  var sel = el("div", "sel");
  sel.appendChild(el("div", "label", label));
  var v = el("div", "nilai" + (kelas ? " " + kelas : "") + (arti ? " beristilah" : ""),
    nilai === null || nilai === undefined || nilai === "" ? "-" : String(nilai));
  if (arti) {
    v.setAttribute("data-petunjuk", arti);
    v.setAttribute("tabindex", "0");
  }
  sel.appendChild(v);
  return sel;
}

function gambarJadwal(j, lain) {
  var kotak = document.getElementById("jadwal");
  kosongkan(kotak);

  // On a machine where backups do not run, a red "not registered" would accuse a missing schedule that exists elsewhere (Windows Task Scheduler is not visible from Linux).
  if (lain) {
    kotak.appendChild(selJadwal("Tugas terjadwal", "DI LAPTOP", "redup",
      "Tiga tugas terjadwal hidup di laptop Windows: backup penuh 02.00, "
      + "incremental 03.00, dan verifikasi pemulihan tiap Minggu 04.00. "
      + "Keadaannya hanya bisa dibaca dari laptop itu sendiri."));
    return;
  }

  if (!j || !j.tersedia) {
    kotak.appendChild(selJadwal("Tugas terjadwal", "TIDAK TERDAFTAR", "buruk",
      (j && j.alasan) ? j.alasan : null));
    return;
  }

  var kode = (j.hasil_terakhir || "").trim();
  var baik = (kode === "0" || kode === "0x0");
  kotak.appendChild(selJadwal("Nama tugas", j.nama));
  kotak.appendChild(selJadwal("Keadaan", j.status,
    j.status === "Ready" || j.status === "Siap" ? "baik" : null));
  kotak.appendChild(selJadwal("Terakhir dijalankan", j.terakhir_jalan));
  kotak.appendChild(selJadwal("Hasil terakhir", kode || "-",
    baik ? "baik" : "buruk", j.hasil_terakhir_teks));
  kotak.appendChild(selJadwal("Dijadwalkan berikutnya", j.berikutnya));
  kotak.appendChild(selJadwal("Dijalankan sebagai", j.jalankan_sebagai));
}

/*
 * Incremental backup, the main method, placed at the top. `daftar_berkas()` in Python uses a
 * non-recursive `os.listdir()`, so files in `backup/incremental/` are not counted as backup files elsewhere.
 */
function gambarIncremental(inc) {
  var ringkas = document.getElementById("inc-ringkas");
  var kotakIsi = document.getElementById("inc-isi");
  var kotakSal = document.getElementById("inc-salinan");
  if (!ringkas) return;                       
  kosongkan(kotakIsi);
  kosongkan(kotakSal);

  if (!inc || !inc.ada) {
    ringkas.textContent = inc && inc.folder
      ? "Folder backup incremental tidak ditemukan: " + inc.folder
      : "Keadaan backup incremental tidak tersedia.";
    return;
  }

  if (!inc.induk) {
    ringkas.textContent =
      "induk.zip belum ada. Backup incremental belum pernah berhasil dijalankan.";
    return;
  }

  var n = inc.posisi ? Object.keys(inc.posisi).length : 0;
  ringkas.textContent =
    "induk.zip · " + inc.induk.ukuran_mb + " MB · diperbarui "
    + inc.induk.umur_teks
    + (n ? " · " + n + " tabel deret-waktu dilacak posisinya" : "");

  /* Zip contents are itemized per file: "the file exists" and "its contents are restorable" are different things. */
  (inc.induk.isi || []).forEach(function (x) {
    var item = el("div", "isi-item" + (x.mb === null ? " hilang" : ""));
    item.appendChild(el("div", "nama", x.nama));
    item.appendChild(el("div", "guna", x.mb === null ? "" : x.mb + " MB"));
    kotakIsi.appendChild(item);
  });

  /* Periodic copies: the parent is only one restore point; these copies provide several, so their age is shown. */
  if (!(inc.salinan || []).length) {
    kotakSal.appendChild(el("div", "redup",
      "Belum ada salinan mingguan/bulanan. Keduanya dibuat sendiri saat "
      + "induk sudah cukup berumur."));
  } else {
    inc.salinan.forEach(function (sal) {
      var baris = el("div", "baris-jadwal" + (sal.terlambat ? " bahaya" : ""));
      baris.appendChild(el("div", "kunci", "Salinan " + sal.jenis));
      baris.appendChild(el("div", "nilai",
        sal.ukuran_mb + " MB · " + sal.umur_teks
        + (sal.terlambat ? " · TERLAMBAT disegarkan" : "")));
      kotakSal.appendChild(baris);
    });
  }
}


function gambarIsi(isi, namaBerkas, lain) {
  var kotak = document.getElementById("isi-terbaru");
  kosongkan(kotak);

  if (!isi) {
    kotak.appendChild(el("div", "redup", lain
      ? "Berkas backup tidak tersimpan di mesin ini, jadi isinya tidak bisa "
        + "diperiksa dari sini."
      : "Belum ada berkas backup untuk diperiksa."));
    return;
  }
  if (!isi.terbaca) {
    var rusak = el("div", "isi-item hilang");
    rusak.appendChild(el("div", "nama", "Berkas tidak bisa dibuka"));
    rusak.appendChild(el("div", "guna", isi.alasan || ""));
    kotak.appendChild(rusak);
    return;
  }

  if (namaBerkas) {
    var judul = el("div", "redup");
    judul.style.width = "100%";
    judul.style.fontSize = "var(--f-s)";
    judul.style.marginBottom = "6px";
    judul.textContent = namaBerkas;
    kotak.appendChild(judul);
  }

  isi.isi.forEach(function (x) {
    var item = el("div", "isi-item " + (x.ada ? "ada" : "hilang"));
    var nama = el("div", "nama");
    var lam = el("span", "lambang-kecil");
    lam.appendChild(ikonUI(x.ada ? "ceklis" : "peringatan", 14));
    nama.appendChild(lam);
    nama.appendChild(el("span", null, x.nama));
    item.appendChild(nama);
    item.appendChild(el("div", "guna", x.guna));
    item.appendChild(el("div", "ukuran",
      x.ada ? mb(x.ukuran_mb) : "tidak ada di dalam backup ini"));
    kotak.appendChild(item);
  });
}

/*
 * One table merging the folder contents with manifest.log entries, joined by FILE NAME as an
 * outer join so unmatched rows stay visible:
 *   file exists, no record  -> created before the manifest existed, or manifest lost/truncated
 *   record exists, no file  -> rotated out (normal) OR deleted outside NSM (not normal)
 */
function gambarBerkas(d) {
  var tbody = document.getElementById("baris-berkas");
  kosongkan(tbody);

  var namaKedua = {};
  (d.berkas_kedua || []).forEach(function (b) { namaKedua[b.nama] = true; });

  // Manifest entries are indexed by file name; the NEWEST wins, since the manifest is append-only and retries leave two lines.
  var catatan = {};
  (d.riwayat || []).forEach(function (h) {
    if (h.terurai && h.berkas) catatan[h.berkas] = h;
  });

  document.getElementById("ringkas-berkas").textContent =
    d.folder_utama + "  ·  " + mb(d.total_mb) + " total  ·  disimpan maksimal "
    + d.simpan_maksimal + " backup terakhir"
    + (d.folder_kedua ? ("  ·  lokasi kedua: " + d.folder_kedua)
                      : "  ·  lokasi kedua belum diatur");

  var punyaBerkas = d.berkas && d.berkas.length;
  var yatim = (d.riwayat || []).filter(function (h) {
    if (!h.terurai || !h.berkas) return false;
    return !(d.berkas || []).some(function (b) { return b.nama === h.berkas; });
  });

  if (!punyaBerkas && !yatim.length) {
    var tr = el("tr");
    var td = el("td", "redup", "Belum ada berkas backup.");
    td.colSpan = 7;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  function selHasil(tr, h) {
    if (!h) {
      var tdKosong = el("td", "redup", "tidak tercatat");
      tdKosong.setAttribute("data-petunjuk",
        "Berkasnya ada, tetapi manifest.log tidak memuat satu baris pun "
        + "untuknya. Bisa berarti berkas ini dibuat sebelum manifest dipakai, "
        + "atau manifest-nya pernah terpotong. Isinya tetap bisa diperiksa "
        + "lewat \"lihat isi\".");
      tr.appendChild(tdKosong);
      tr.appendChild(el("td", "redup", "-"));
      tr.appendChild(el("td", "redup", "-"));
      return;
    }
    tr.appendChild(el("td", null, h.status));
    tr.appendChild(el("td", "lama", h.lama_detik.toFixed(1) + " dtk"));
    tr.appendChild(el("td", h.ada_kendala ? null : "redup", h.kendala));
  }

  (d.berkas || []).forEach(function (b) {
    var h = catatan[b.nama];
    // Row color follows the creation RESULT, not whether the file exists: a file made with FAILED status is easy to misread as safe.
    var kelas = "berkas";
    if (h && h.status === "GAGAL") kelas += " gagal";
    else if (h && h.status === "SEBAGIAN") kelas += " sebagian";
    var tr = el("tr", kelas);

    var tdNama = el("td", null, b.nama);
    tdNama.appendChild(el("span", "redup", "  lihat isi"));
    tr.appendChild(tdNama);

    // One time format per event (the file time wins); the original manifest text stays available in the tooltip.
    var tdWaktu = el("td", "waktu", waktuTampil(b.waktu));
    if (h) {
      tdWaktu.setAttribute("data-petunjuk",
        "Apa adanya di manifest.log: " + h.waktu);
    }
    tr.appendChild(tdWaktu);

    tr.appendChild(el("td", "ukuran", mb(b.ukuran_mb)));

    var ada = !!namaKedua[b.nama];
    var tdSalin = el("td", null, d.folder_kedua
      ? (ada ? "tersalin" : "BELUM")
      : "tidak diatur");
    if (d.folder_kedua && !ada) tdSalin.classList.add("merah");
    tr.appendChild(tdSalin);

    selHasil(tr, h);
    tr.addEventListener("click", function () { bukaIsi(b.nama, tr); });
    tbody.appendChild(tr);
  });

  // Records whose file is gone. Shown at the bottom, dimmed: history, not a usable backup.
  yatim.forEach(function (h) {
    var tr = el("tr", "berkas yatim");
    var tdNama = el("td", "redup", h.berkas);
    tdNama.setAttribute("data-petunjuk",
      "Catatan pembuatannya ada di manifest.log, tetapi berkasnya sudah "
      + "tidak ada di folder. Biasanya wajar: hanya "
      + (d.simpan_maksimal || "beberapa") + " backup terakhir disimpan, "
      + "sisanya dirotasi keluar. Yang TIDAK wajar adalah kalau ini termasuk "
      + "backup yang masih dalam jangkauan rotasi.");
    tr.appendChild(tdNama);
    var tdWaktu = el("td", "waktu redup", waktuLengkap(h.waktu.replace(" ", "T")));
    if (tdWaktu.textContent === "-") tdWaktu.textContent = h.waktu;
    tr.appendChild(tdWaktu);
    tr.appendChild(el("td", "redup", "sudah dirotasi"));
    tr.appendChild(el("td", "redup", "-"));
    selHasil(tr, h);
    tbody.appendChild(tr);
  });

  // Pagination is attached AFTER the tbody is filled; the table is empty at load, so automatic setup on DOMContentLoaded would see zero rows.
  if (window.halamanTabel) halamanTabel.terapkan();
}

/* Opens the details of one file as an extra row below it. Only one is open at a time. */
function bukaIsi(nama, tr) {
  var lama = document.getElementById("baris-rincian");
  if (lama) lama.parentNode.removeChild(lama);
  if (berkasTerbuka === nama) { berkasTerbuka = null; return; }
  berkasTerbuka = nama;

  var baris = el("tr", "rincian");
  baris.id = "baris-rincian";
  var td = el("td", null, "Memuat isi berkas…");
  td.colSpan = 5;
  baris.appendChild(td);
  tr.parentNode.insertBefore(baris, tr.nextSibling);

  fetch("/api/backup/isi?nama=" + encodeURIComponent(nama))
    .then(function (r) { return r.json(); })
    .then(function (isi) {
      kosongkan(td);
      if (isi.error) { td.appendChild(el("span", "redup", isi.error)); return; }
      var kotak = el("div", "isi-kotak");
      if (!isi.terbaca) {
        var rusak = el("div", "isi-item hilang");
        rusak.appendChild(el("div", "nama", "Tidak bisa dibuka"));
        rusak.appendChild(el("div", "guna", isi.alasan || ""));
        kotak.appendChild(rusak);
      } else {
        isi.isi.forEach(function (x) {
          var item = el("div", "isi-item " + (x.ada ? "ada" : "hilang"));
          var n = el("div", "nama");
          var lam = el("span", "lambang-kecil");
          lam.appendChild(ikonUI(x.ada ? "ceklis" : "peringatan", 14));
          n.appendChild(lam);
          n.appendChild(el("span", null, x.nama));
          item.appendChild(n);
          item.appendChild(el("div", "ukuran",
            x.ada ? mb(x.ukuran_mb) : "tidak ada"));
          kotak.appendChild(item);
        });
      }
      td.appendChild(kotak);
    })
    .catch(function (e) {
      kosongkan(td);
      td.appendChild(el("span", "redup", "Gagal memuat isi berkas: " + e));
    });
}

/*
 * Leftover manifest.log lines that could NOT be parsed. Shown as-is on purpose, since they may
 * be a failure shape never seen before. The section is hidden entirely when there are none.
 */
function gambarRiwayat(riwayat) {
  var tbody = document.getElementById("baris-riwayat");
  kosongkan(tbody);

  var mentah = (riwayat || []).filter(function (h) { return !h.terurai; });
  var bagian = tbody.closest ? tbody.closest(".bagian") : null;
  if (bagian) bagian.style.display = mentah.length ? "" : "none";
  if (!mentah.length) return;

  mentah.forEach(function (h) {
    var trm = el("tr", "mentah");
    trm.appendChild(el("td", null, h.mentah));
    tbody.appendChild(trm);
  });

  if (window.halamanTabel) halamanTabel.terapkan();
}

function muat() {
  var meta = document.getElementById("meta");
  meta.textContent = "Memeriksa…";
  fetch("/api/backup/status")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      gambarVonis(d);
      gambarIncremental(d.incremental);
      gambarJadwal(d.jadwal, d.mesin_lain && !d.dari_laporan);
      gambarIsi(d.isi_terbaru, d.terbaru ? d.terbaru.nama : null,
                d.mesin_lain && !d.dari_laporan);
      gambarBerkas(d);
      gambarRiwayat(d.riwayat);
      meta.textContent = "Diperiksa " + waktuTampil(d.diperiksa);
    })
    .catch(function (e) {
      meta.textContent = "Gagal memuat";
      var kotak = document.getElementById("vonis");
      kosongkan(kotak);
      kotak.className = "bahaya";
      kotak.appendChild(el("h2", null, "Tidak bisa memeriksa backup"));
      // Distinguishes a network failure from a rendering failure; otherwise every error would blame the backend.
      kotak.appendChild(el("div", "ringkas",
        "Backend Python (uvicorn) kemungkinan mati. Pesan aslinya: " + e));
      if (window.console) console.error("gagal memuat status backup", e);
    });
}

document.getElementById("segarkan").addEventListener("click", muat);
muat();
