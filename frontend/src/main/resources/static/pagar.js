/* Automation guard page (docs/design/CLOSED-LOOP-AUTOMATION.md). Fully read-only: no button calls `pagar_otomasi.putuskan()`, since it always writes an audit row and counts toward rate limits. */
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

function gambarStatus(s) {
  var w = document.getElementById("status-pagar");
  if (!w) return;
  kosongkan(w);

  var kotak = el("div", "kotak-pratinjau");

  var baris1 = el("div");
  baris1.appendChild(el("b", null, "Daftar putih: "));
  baris1.appendChild(document.createTextNode(
    (s.daftar_putih && s.daftar_putih.length) ? s.daftar_putih.join(", ") : "(kosong -- tidak ada yang diotomasi)"));
  kotak.appendChild(baris1);

  var baris2 = el("div");
  baris2.appendChild(el("b", null, "Batas laju: "));
  baris2.appendChild(document.createTextNode(
    s.batas_per_device_per_jam + "/jam per device, " + s.batas_global_per_jam + "/jam global"));
  kotak.appendChild(baris2);

  // Gate 5 (circuit breaker). `|| "?"` keeps the page correct against an older backend that does not send this field.
  var baris2b = el("div");
  baris2b.appendChild(el("b", null, "Pemutus (circuit breaker): "));
  baris2b.appendChild(document.createTextNode(
    (s.gagal_beruntun_maks || "?")
    + " kegagalan BERUNTUN untuk satu (device, tindakan) -> berhenti dicoba. "
    + "Satu keberhasilan mengembalikan hitungan ke nol."));
  kotak.appendChild(baris2b);

  var baris3 = el("div");
  baris3.appendChild(el("b", null, "Jam kerja: "));
  baris3.appendChild(document.createTextNode(
    (s.jam_mulai < 10 ? "0" : "") + s.jam_mulai + ":00 - " +
    (s.jam_selesai < 10 ? "0" : "") + s.jam_selesai + ":00 " +
    "(" + (s.sedang_jam_kerja ? "sedang di dalam" : "SEDANG DI LUAR") + " jam kerja sekarang)"));
  kotak.appendChild(baris3);

  var baris4 = el("div");
  baris4.appendChild(el("b", null, "Jendela beku: "));
  if (s.jendela_beku && s.jendela_beku.length) {
    baris4.appendChild(document.createTextNode(
      s.jendela_beku.map(function (j) {
        return waktuLengkap(j.mulai) + " s.d. " + waktuLengkap(j.selesai);
      }).join("; ")));
  } else {
    baris4.appendChild(document.createTextNode("(tidak ada)"));
  }
  kotak.appendChild(baris4);

  w.appendChild(kotak);
}

function lencanaKeputusan(k) {
  return el("span", "lencana " + (k === "izin" ? "lencana-up" : "lencana-down"),
    k === "izin" ? "Izin" : "Tolak");
}

function gambarRiwayat(daftar) {
  var tb = document.getElementById("baris-riwayat-pagar");
  if (!tb) return;
  kosongkan(tb);
  if (!daftar || !daftar.length) {
    var tr = el("tr");
    var td = el("td", "redup",
      "Belum ada keputusan tercatat -- normal sampai Tahap 4-7 (pemulih otomatis) dibangun dan mulai memanggil pagar ini.");
    td.colSpan = 6;
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }
  daftar.forEach(function (r) {
    var tr = el("tr");
    tr.appendChild(el("td", null, r.waktu ? waktuLengkap(r.waktu) : "-"));
    tr.appendChild(el("td", null, r.device_id != null ? ("#" + r.device_id) : "-"));
    tr.appendChild(el("td", "mono", r.kategori + ":" + r.kunci));
    var tdK = el("td");
    tdK.appendChild(lencanaKeputusan(r.keputusan));
    tr.appendChild(tdK);
    tr.appendChild(el("td", "kecil", r.alasan));
    var tdV = el("td");
    if (r.status_verifikasi === null || r.status_verifikasi === undefined) {
      tdV.appendChild(el("span", "redup kecil", "belum diverifikasi"));
    } else {
      tdV.appendChild(el("span", "lencana " + (r.status_verifikasi ? "lencana-up" : "lencana-down"),
        r.status_verifikasi ? "Berhasil" : "Gagal"));
    }
    tr.appendChild(tdV);
    tb.appendChild(tr);
  });
}

ambilJson("/api/pagar/status")
  .then(gambarStatus)
  .catch(function (e) {
    var w = document.getElementById("status-pagar");
    if (w) { kosongkan(w); w.appendChild(el("div", "pesan-galat", pesanGalat(e))); }
  });

ambilJson("/api/pagar/riwayat")
  .then(gambarRiwayat)
  .catch(function (e) {
    var tb = document.getElementById("baris-riwayat-pagar");
    if (!tb) return;
    kosongkan(tb);
    var tr = el("tr");
    var td = el("td", "redup", "Gagal memuat: " + pesanGalat(e));
    td.colSpan = 6;
    tr.appendChild(td);
    tb.appendChild(tr);
  });
