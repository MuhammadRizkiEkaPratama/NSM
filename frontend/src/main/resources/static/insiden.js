/*
 * Incidents. Two pages share this file: the list (`insiden.html`, #terbuka) and one incident's timeline (`insiden_detail.html`, #garis-waktu); the job is chosen from the elements present in the document. Read-only (no POST, so no CSRF token).
 *
 * All text is inserted with textContent, never innerHTML: `detail` and `ringkas` contain device names from the database, and names can be typed by users.
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

function pesanGalat(e) {
  if (e && e.badan && e.badan.ditolak) return e.badan.ditolak;
  return e && e.message ? e.message : String(e);
}

function tampilGalat(wadah, e) {
  kosongkan(wadah);
  wadah.appendChild(el("p", "ins-kosong", pesanGalat(e)));
}

/* Human-readable duration. Deliberately not `waktuRelatif()`, which answers "how long ago", not "how long". */
function durasi(detik) {
  if (detik === null || detik === undefined) return "-";
  detik = Math.max(0, Math.round(detik));
  if (detik < 60) return detik + " detik";
  var menit = Math.floor(detik / 60);
  var sisaDetik = detik % 60;
  if (menit < 60) {
    return sisaDetik ? menit + " mnt " + sisaDetik + " dtk" : menit + " menit";
  }
  var jam = Math.floor(menit / 60);
  var sisaMenit = menit % 60;
  if (jam < 24) {
    return sisaMenit ? jam + " jam " + sisaMenit + " mnt" : jam + " jam";
  }
  var hari = Math.floor(jam / 24);
  return hari + " hari " + (jam % 24) + " jam";
}

var LABEL_PARAH = { bahaya: "Bahaya", perhatian: "Perhatian", info: "Info" };
var LENCANA_PARAH = {
  bahaya: "lencana-down", perhatian: "lencana-menunggu", info: "lencana-netral"
};

function lencanaParah(p) {
  var kunci = LABEL_PARAH[p] ? p : "info";
  return el("span", "lencana " + LENCANA_PARAH[kunci], LABEL_PARAH[kunci]);
}

function lencanaStatus(status) {
  return status === "terbuka"
    ? el("span", "lencana lencana-down", "Berlangsung")
    : el("span", "lencana lencana-up", "Pulih");
}


/* ===========================================================================
 * HALAMAN 1 -- daftar insiden
 * =========================================================================*/

function kartuInsiden(i) {
  var parah = LABEL_PARAH[i.keparahan] ? i.keparahan : "info";
  var a = el("a", "ins-kartu p-" + parah);
  a.href = "/insiden/" + i.id;

  var atas = el("div", "baris-atas");
  atas.appendChild(el("span", "akar", i.akar || "Akar belum bisa dipastikan"));
  atas.appendChild(lencanaStatus(i.status));
  atas.appendChild(lencanaParah(i.keparahan));

  var kapan = el("span", "kapan");
  kapan.title = waktuLengkap(i.mulai);
  pasangWaktuRelatif(kapan, i.mulai);
  atas.appendChild(kapan);
  a.appendChild(atas);

  if (i.ringkas) a.appendChild(el("div", "ringkas", i.ringkas));

  var angka = el("div", "angka-baris");

  var g = el("span");
  g.appendChild(el("b", null, String(i.jumlah_gejala || 0)));
  g.appendChild(document.createTextNode(" gejala"));
  angka.appendChild(g);

  // MTTR is only written once the incident is resolved; "MTTR 0 seconds" on an ongoing incident would read as instant recovery.
  if (i.status !== "terbuka" && i.mttr_detik !== null &&
      i.mttr_detik !== undefined) {
    var m = el("span");
    m.appendChild(document.createTextNode("MTTR "));
    m.appendChild(el("b", null, durasi(i.mttr_detik)));
    angka.appendChild(m);
  } else if (i.status === "terbuka" && i.mulai) {
    var lama = el("span");
    lama.appendChild(document.createTextNode("berlangsung "));
    lama.appendChild(el("b", null,
      durasi((Date.now() - new Date(i.mulai).getTime()) / 1000)));
    angka.appendChild(lama);
  }

  // "Root cause uncertain" is stated rather than hidden, since guessed and proven causes call for different actions.
  if (i.akar_pasti === false) {
    angka.appendChild(el("span", "redup",
      "akar belum pasti (graf ketergantungan tidak yakin)"));
  }
  a.appendChild(angka);
  return a;
}

function gambarDaftar(data) {
  var wTerbuka = document.getElementById("terbuka");
  var wPulih = document.getElementById("pulih");
  var terbuka = data.terbuka || [];
  var pulih = data.pulih || [];

  kosongkan(wTerbuka);
  if (!terbuka.length) {
    wTerbuka.appendChild(el("p", "ins-kosong",
      "Tidak ada gangguan yang sedang berlangsung."));
  } else {
    terbuka.forEach(function (i) { wTerbuka.appendChild(kartuInsiden(i)); });
  }

  kosongkan(wPulih);
  if (!pulih.length) {
    wPulih.appendChild(el("p", "ins-kosong",
      "Belum ada insiden yang pulih dalam jendela ini."));
  } else {
    pulih.forEach(function (i) { wPulih.appendChild(kartuInsiden(i)); });
  }

  gambarRingkas(terbuka, pulih, data.jam);

  var meta = document.getElementById("meta");
  if (meta) meta.textContent = "diperbarui " + jamSaja(new Date());
}

function kartuMini(judul, isi, kelasAngka) {
  var k = el("div", "kartu-mini");
  k.appendChild(el("div", "judul", judul));
  k.appendChild(el("div", "isi angka-mini" + (kelasAngka ? " " + kelasAngka : ""),
                   isi));
  return k;
}

function gambarRingkas(terbuka, pulih, jam) {
  var wadah = document.getElementById("ringkas-insiden");
  if (!wadah) return;
  kosongkan(wadah);

  wadah.appendChild(kartuMini("Sedang berlangsung", String(terbuka.length),
                              terbuka.length ? "buruk" : "aman"));
  wadah.appendChild(kartuMini("Pulih (" + jam + " jam)", String(pulih.length)));

  // Average MTTR counts only incidents that have a value; counting missing ones as zero would understate recovery time.
  var punya = pulih.filter(function (i) {
    return i.mttr_detik !== null && i.mttr_detik !== undefined;
  });
  var rata = punya.length
    ? punya.reduce(function (a, i) { return a + i.mttr_detik; }, 0) / punya.length
    : null;
  wadah.appendChild(kartuMini("MTTR rata-rata",
    rata === null ? "belum ada" : durasi(rata)));

  // Number of alarm rows readers no longer need to read because they were merged into incidents.
  var semua = terbuka.concat(pulih);
  var gejala = semua.reduce(function (a, i) {
    return a + (i.jumlah_gejala || 0);
  }, 0);
  var hemat = gejala - semua.length;
  wadah.appendChild(kartuMini("Alarm yang disatukan",
    semua.length ? gejala + " gejala → " + semua.length + " insiden"
                 : "belum ada",
    hemat > 0 ? "aman" : null));
}

function muatDaftar() {
  var pilih = document.getElementById("jendela");
  var jam = pilih ? pilih.value : "24";
  ambilJson("/api/insiden?jam=" + encodeURIComponent(jam))
    .then(gambarDaftar)
    .catch(function (e) {
      tampilGalat(document.getElementById("terbuka"), e);
      var wPulih = document.getElementById("pulih");
      if (wPulih) kosongkan(wPulih);
    });
}



function tahap(kelas, waktu, pokok, ket, lencana) {
  var d = el("div", "ins-tahap " + kelas);
  var w = el("div", "waktu", waktuLengkap(waktu));
  d.appendChild(w);

  var p = el("div", "pokok");
  p.appendChild(document.createTextNode(pokok));
  if (lencana) {
    p.appendChild(document.createTextNode(" "));
    p.appendChild(lencana);
  }
  d.appendChild(p);

  if (ket) d.appendChild(el("div", "ket", ket));
  return d;
}

function gambarDetail(d) {
  var wKepala = document.getElementById("kepala-insiden");
  var wGaris = document.getElementById("garis-waktu");

  if (!d || d.ada === false) {
    tampilGalat(wKepala, new Error(d && d.alasan
      ? d.alasan : "Insiden ini tidak ditemukan."));
    kosongkan(wGaris);
    return;
  }

  // ---- kepala: akar, keparahan, MTTR --------------------------------
  var parah = LABEL_PARAH[d.keparahan] ? d.keparahan : "info";
  kosongkan(wKepala);
  var kartu = el("div", "ins-kartu p-" + parah);

  var atas = el("div", "baris-atas");
  atas.appendChild(el("span", "akar", d.akar || "Akar belum bisa dipastikan"));
  atas.appendChild(lencanaStatus(d.status));
  atas.appendChild(lencanaParah(d.keparahan));
  atas.appendChild(el("span", "kapan", "insiden #" + d.id));
  kartu.appendChild(atas);

  if (d.ringkas) kartu.appendChild(el("div", "ringkas", d.ringkas));

  var angka = el("div", "angka-baris");
  var mulai = el("span");
  mulai.appendChild(document.createTextNode("mulai "));
  mulai.appendChild(el("b", null, waktuLengkap(d.mulai)));
  angka.appendChild(mulai);

  if (d.selesai) {
    var sel = el("span");
    sel.appendChild(document.createTextNode("pulih "));
    sel.appendChild(el("b", null, waktuLengkap(d.selesai)));
    angka.appendChild(sel);
  }
  if (d.status !== "terbuka" && d.mttr_detik !== null &&
      d.mttr_detik !== undefined) {
    var m = el("span");
    m.appendChild(document.createTextNode("MTTR "));
    m.appendChild(el("b", null, durasi(d.mttr_detik)));
    angka.appendChild(m);
  }
  var jg = el("span");
  jg.appendChild(el("b", null, String((d.gejala || []).length)));
  jg.appendChild(document.createTextNode(" gejala"));
  angka.appendChild(jg);

  if (d.akar_pasti === false) {
    angka.appendChild(el("span", "redup",
      "akar belum pasti (graf ketergantungan tidak yakin)"));
  }
  kartu.appendChild(angka);
  wKepala.appendChild(kartu);

  // Timeline: events are re-ordered from the data rather than shown as an unsorted symptom list, because readers look for the sequence.
  var kejadian = [];
  kejadian.push({
    t: d.mulai, kelas: "mulai",
    pokok: "Insiden dimulai",
    ket: d.akar
      ? ("Akar menurut graf ketergantungan: " + d.akar + ".")
      : "Akar belum bisa dipastikan dari graf ketergantungan."
  });

  (d.gejala || []).forEach(function (g) {
    var nama = g.device || "(perangkat tidak dikenal)";
    var ket = g.detail || "";
    if (g.jumlah > 1) {
      ket += (ket ? "  " : "") + "Terlihat " + g.jumlah + " kali, terakhir " +
             waktuLengkap(g.waktu_terakhir || g.waktu) + ".";
    }
    kejadian.push({
      t: g.waktu,
      kelas: "gejala" + (g.pulih ? " sudah-pulih" : ""),
      pokok: nama,
      ket: ket,
      lencana: g.adalah_akar
        ? el("span", "lencana-akar", "akar")
        : el("span", "lencana-hilir", "terdampak")
    });

    // A recovery row is only added for symptoms whose time was actually recorded; older rows (before the `pulih_pada` column) get no invented time.
    if (g.pulih && g.pulih_pada) {
      kejadian.push({
        t: g.pulih_pada, kelas: "pulih",
        pokok: nama + " pulih",
        ket: "Terjangkau lagi setelah " +
             durasi((new Date(g.pulih_pada).getTime() -
                     new Date(g.waktu).getTime()) / 1000) + "."
      });
    }
  });

  if (d.selesai) {
    kejadian.push({
      t: d.selesai, kelas: "pulih",
      pokok: "Insiden ditutup",
      ket: "Seluruh gejala pulih. Penutupan menunggu 300 detik lebih dulu " +
           "supaya perangkat yang berkedip tetap satu insiden."
    });
  }

  kejadian.sort(function (a, b) {
    return new Date(a.t).getTime() - new Date(b.t).getTime();
  });

  kosongkan(wGaris);
  var garis = el("div", "ins-garis");
  kejadian.forEach(function (k) {
    garis.appendChild(tahap(k.kelas, k.t, k.pokok, k.ket, k.lencana));
  });
  wGaris.appendChild(garis);
}

function muatDetail(id) {
  ambilJson("/api/insiden/" + encodeURIComponent(id))
    .then(gambarDetail)
    .catch(function (e) {
      tampilGalat(document.getElementById("kepala-insiden"), e);
      kosongkan(document.getElementById("garis-waktu"));
    });
}


/* ===========================================================================
 * Pemilihan halaman
 * =========================================================================*/
(function () {
  var wDaftar = document.getElementById("terbuka");
  var wDetail = document.getElementById("garis-waktu");

  if (wDaftar) {
    var pilih = document.getElementById("jendela");
    if (pilih) pilih.addEventListener("change", muatDaftar);
    muatDaftar();
    // Ongoing incidents refresh every 30 seconds.
    setInterval(muatDaftar, 30000);
  } else if (wDetail) {
    var id = metaNilai("insiden-id");
    if (id) {
      muatDetail(id);
      setInterval(function () { muatDetail(id); }, 30000);
    }
  }
})();
