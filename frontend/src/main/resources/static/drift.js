/* Drift detection. Two pages share this file: the list (`konfig_drift.html`, #tabel-drift) and the per-device detail (`konfig_drift_device.html`, #judul-device). Read-only: it only displays `/api/drift/**`. */
function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}
/* Scroll wrapper for tables built from JS; tables in templates are already wrapped in `<div class="gulir-tabel">`. */
function bungkusTabel(t) {
  var w = el("div", "gulir-tabel");
  w.appendChild(t);
  return w;
}


function kosongkan(n) { while (n.firstChild) n.removeChild(n.firstChild); }

function metaNilai(nama) {
  var m = document.querySelector('meta[name="' + nama + '"]');
  return m ? m.getAttribute("content") : "";
}

function pesanGalat(e) {
  if (e && e.badan && e.badan.ditolak) return e.badan.ditolak;
  return e && e.message ? e.message : String(e);
}

/* Format any value (string/number/bool/list/null) as short readable text, used by the Intended/Observed columns. */
function formatNilai(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "ya" : "tidak";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "(kosong)";
  return String(v);
}

var LABEL_STATUS = {
  cocok: "Cocok", beda: "Beda", tidak_terbaca: "Tidak terbaca", hilang: "Hilang",
};
var LENCANA_STATUS = {
  cocok: "lencana-up", beda: "lencana-down",
  tidak_terbaca: "lencana-netral", hilang: "lencana-down",
};

function lencanaStatus(status) {
  return el("span", "lencana " + (LENCANA_STATUS[status] || "lencana-netral"),
    LABEL_STATUS[status] || status);
}

function lencanaRisiko(risiko) {
  var teks = risiko === "wajib_manusia" ? "Wajib manusia" : "Aman otomatis";
  return el("span", "lencana " + (risiko === "wajib_manusia" ? "lencana-menunggu" : "lencana-up"), teks);
}


/* ===========================================================================
 * HALAMAN DAFTAR
 * =========================================================================== */

function gambarDaftarDrift(daftar) {
  var tb = document.getElementById("baris-drift");
  if (!tb) return;
  kosongkan(tb);
  if (!daftar || !daftar.length) {
    var trK = el("tr");
    var tdK = el("td", "redup", "Belum ada perangkat yang punya katalog intent.");
    tdK.colSpan = 4;
    trK.appendChild(tdK);
    tb.appendChild(trK);
    return;
  }
  daftar.forEach(function (d) {
    var tr = el("tr");
    tr.appendChild(el("td", null, d.device));
    tr.appendChild(el("td", "mono", d.platform));

    var tdStatus = el("td");
    if (!d.didukung) {
      tdStatus.appendChild(el("span", "lencana lencana-netral", "Tidak didukung"));
    } else if (!d.punya_intent) {
      tdStatus.appendChild(el("span", "lencana lencana-netral", "Intent kosong"));
    } else if (!d.punya_potret) {
      tdStatus.appendChild(el("span", "lencana lencana-netral", "Belum ada potret"));
    } else if (d.selaras) {
      tdStatus.appendChild(el("span", "lencana lencana-up", "Selaras"));
    } else {
      var l = el("span", "lencana lencana-down",
        d.jumlah_menyimpang + " menyimpang");
      tdStatus.appendChild(l);
      if (d.jumlah_wajib_manusia) {
        tdStatus.appendChild(document.createTextNode(" "));
        tdStatus.appendChild(el("span", "kecil redup",
          "(" + d.jumlah_wajib_manusia + " wajib manusia)"));
      }
    }
    tr.appendChild(tdStatus);

    var tdTaut = el("td");
    if (d.didukung) {
      var a = el("a", null, "Lihat detail");
      a.href = "/admin/konfig/drift/" + d.device_id;
      tdTaut.appendChild(a);
    } else {
      tdTaut.appendChild(el("span", "redup kecil", d.alasan || "tidak didukung"));
    }
    tr.appendChild(tdTaut);

    tb.appendChild(tr);
  });
}

function muatDaftarDrift() {
  ambilJson("/api/drift")
    .then(gambarDaftarDrift)
    .catch(function (e) {
      var tb = document.getElementById("baris-drift");
      if (!tb) return;
      kosongkan(tb);
      var tr = el("tr");
      var td = el("td", "redup", "Gagal memuat: " + pesanGalat(e));
      td.colSpan = 4;
      tr.appendChild(td);
      tb.appendChild(tr);
    });
}


/* ===========================================================================
 * HALAMAN DETAIL
 * =========================================================================== */

function tabelMedan(medan) {
  if (!medan || !medan.length) return null;
  var tabel = el("table", "tabel-rincian");
  var thead = el("thead");
  var trh = el("tr");
  ["Medan", "Status", "Intended", "Observed"].forEach(function (t) {
    trh.appendChild(el("th", null, t));
  });
  thead.appendChild(trh);
  tabel.appendChild(thead);
  var tbody = el("tbody");
  medan.forEach(function (m) {
    var tr = el("tr");
    tr.appendChild(el("td", null, m.label || m.medan));
    var tdS = el("td");
    tdS.appendChild(lencanaStatus(m.status));
    tr.appendChild(tdS);
    tr.appendChild(el("td", "mono", formatNilai(m.intended)));
    tr.appendChild(el("td", "mono", formatNilai(m.observed)));
    tbody.appendChild(tr);
  });
  tabel.appendChild(tbody);
  return tabel;
}

function gambarKategoriBerulang(idWadah, daftar) {
  var wadah = document.getElementById(idWadah);
  var bagian = wadah ? wadah.closest("div[id^='bagian-']") : null;
  if (!wadah) return;
  kosongkan(wadah);
  if (!daftar || !daftar.length) {
    if (bagian) bagian.style.display = "none";
    return;
  }
  if (bagian) bagian.style.display = "";
  daftar.forEach(function (item) {
    var kartu = el("div", "kotak-pratinjau");
    var atas = el("div", "kb-atas");
    atas.appendChild(el("span", "kb-judul", item.judul));
    atas.appendChild(lencanaStatus(item.status));
    atas.appendChild(lencanaRisiko(item.risiko));
    kartu.appendChild(atas);

    if (item.catatan) {
      kartu.appendChild(el("div", "kecil redup", item.catatan));
    }
    var tabel = tabelMedan(item.medan);
    if (tabel) kartu.appendChild(bungkusTabel(tabel));

    wadah.appendChild(kartu);
  });
}

function gambarRingkasan(r) {
  var w = document.getElementById("ringkasan-drift");
  if (!w) return;
  kosongkan(w);
  if (r.selaras) {
    w.appendChild(el("div", "pesan-sukses",
      "Selaras penuh -- " + r.jumlah_diperiksa + " kunci diperiksa, tidak ada penyimpangan."));
  } else {
    w.appendChild(el("div", "pesan-hati-hati",
      r.jumlah_menyimpang + " dari " + r.jumlah_diperiksa + " diperiksa menyimpang "
      + "(" + r.jumlah_wajib_manusia + " wajib manusia, "
      + r.jumlah_aman_otomatis + " aman diotomasi), "
      + r.jumlah_tidak_terbaca + " tidak terbaca dari potret."));
  }
  w.appendChild(el("div", "kecil redup",
    "Dibandingkan terhadap potret " + waktuLengkap(r.potret_waktu) + "."));
}

function muatDetailDrift() {
  var deviceId = metaNilai("_drift_device_id");
  ambilJson("/api/drift/" + deviceId)
    .then(function (r) {
      var judul = document.getElementById("judul-device");
      if (judul) judul.textContent = r.device + " (" + r.platform + ")";
      document.title = "Deteksi Penyimpangan: " + r.device + " - NSM";

      var pesan = document.getElementById("pesan-drift");
      if (!r.didukung || !r.punya_intent || !r.punya_potret) {
        if (pesan) {
          kosongkan(pesan);
          pesan.appendChild(el("div", "pesan-hati-hati", r.alasan));
        }
        return;
      }
      if (pesan) kosongkan(pesan);

      gambarRingkasan(r);

      var tbNilai = document.getElementById("baris-nilai");
      var bagianNilai = document.getElementById("bagian-nilai");
      if (tbNilai) {
        kosongkan(tbNilai);
        if (r.nilai && r.nilai.length) {
          if (bagianNilai) bagianNilai.style.display = "";
          r.nilai.forEach(function (h) {
            var tr = el("tr");
            tr.appendChild(el("td", null, h.judul));
            var tdS = el("td");
            tdS.appendChild(lencanaStatus(h.status));
            tr.appendChild(tdS);
            tr.appendChild(el("td", "mono", formatNilai(h.intended)));
            tr.appendChild(el("td", "mono", formatNilai(h.observed)));
            var tdR = el("td");
            tdR.appendChild(lencanaRisiko(h.risiko));
            tr.appendChild(tdR);
            tbNilai.appendChild(tr);
          });
        } else if (bagianNilai) {
          bagianNilai.style.display = "none";
        }
      }

      gambarKategoriBerulang("isi-interface", r.interface);
      gambarKategoriBerulang("isi-vlan", r.vlan);
      gambarKategoriBerulang("isi-rute", r.rute);
    })
    .catch(function (e) {
      var judul = document.getElementById("judul-device");
      if (judul) judul.textContent = "Gagal memuat: " + pesanGalat(e);
    });
}


if (document.getElementById("tabel-drift")) {
  muatDaftarDrift();
}
if (document.getElementById("judul-device") && metaNilai("_drift_device_id")) {
  muatDetailDrift();
}
