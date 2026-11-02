/*
 * Configuration page family: the home page (`/admin/konfig`) plus five content pages (commands, compliance, identity, firewall, snapshots) share this file. Each renderer checks its elements exist, and `muat()` calls only the endpoints the open page uses.
 * Display only: diffs, secret masking, and the changed-or-not decision are done by Python.
 * All elements are built with the DOM API, never innerHTML, since config content comes from devices.
 */
function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}
/* Scroll wrapper for tables built from JS; without it a wide table pushes the whole page sideways. */
function bungkusTabel(t) {
  var w = el("div", "gulir-tabel");
  w.appendChild(t);
  return w;
}


function kosongkan(n) { while (n.firstChild) n.removeChild(n.firstChild); }

/* One icon from the /ikon-tabler.svg sprite, built with createElementNS (elements from createElement would be in the HTML namespace and never render). */
var SVG_NS = "http://www.w3.org/2000/svg";
function ikonEl(nama, kelas) {
  var svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "ikon" + (kelas ? " " + kelas : ""));
  svg.setAttribute("aria-hidden", "true");
  var use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", "/ikon-tabler.svg#i-" + nama);
  svg.appendChild(use);
  return svg;
}

/* Device icon. Cosmetic only: no decision depends on it, so it may guess from the name to tell apart Linux machines whose device_type is all "server" (directory, web, database). */
function ikonJenis(p) {
  var t = p.device_type || "";
  var n = (p.device || "").toLowerCase();
  if (t === "router") return "router";
  if (t === "switch") return "git-branch";
  if (/ldap|direktori/.test(n)) return "users";
  if (/data|basis|mysql|db\b/.test(n)) return "database";
  if (/web|apache|http/.test(n)) return "server";
  if (t === "server") return "server";
  if (t === "pc") return "hard-drive";
  return "cpu";
}

function kartu(judul, angka, sub) {
  var k = el("div", "kartu-mini");
  k.appendChild(el("div", "judul", judul));
  k.appendChild(el("div", "isi", angka));
  if (sub) k.appendChild(el("div", "sub", sub));
  return k;
}

/* Gateway cards on the Configuration home page. Each card carries the ANSWER for its section; the page behind it carries the evidence. An unknown state is never given a good color. */

/* The card tone is applied to both the left edge and the answer text so they cannot diverge. */
function nadaKartu(idKartu, idJawab, teks, nada) {
  var k = document.getElementById(idKartu);
  var j = document.getElementById(idJawab);
  if (k) {
    ["g-buruk", "g-hati", "g-baik", "g-netral"].forEach(function (c) {
      k.classList.remove(c);
    });
    k.classList.add(nada === "buruk" ? "g-buruk"
      : nada === "hati" ? "g-hati"
      : nada === "baik" ? "g-baik" : "g-netral");
  }
  if (j) {
    j.className = "jawab" + (nada && nada !== "netral" ? " " + nada : "");
    j.textContent = teks;
  }
}

/* A load failure is distinguished from an empty state: one means "checked, nothing", the other "nobody knows". */
function gagalKartu(idKartu, idJawab, idRinci, pesan) {
  nadaKartu(idKartu, idJawab, "Gagal memuat", "belum");
  var r = document.getElementById(idRinci);
  if (r) { kosongkan(r); r.appendChild(el("span", null, String(pesan))); }
}

/* Only the first four rows are printed and the rest are counted, with the remaining count shown, so the card does not stretch with the device count or silently truncate. */
var BARIS_KARTU = 4;

/* Small shapes replacing sentences, built from plain <div>s (width/height inline, color via class). Color never stands alone: each bar has a number or word beside it, and details are in the hover title. */

/* Severity distribution bar for one device. `maks` is the largest finding total, a shared scale so bars compare across devices. */
function batangKeparahan(cacah, maks, dinilai) {
  var b = el("div", "batang");
  if (!dinilai) {
    b.classList.add("belum");
    return b;
  }
  var c = cacah || {};
  [["tinggi", c.tinggi], ["sedang", c.sedang], ["rendah", c.rendah]]
    .forEach(function (p) {
      if (!p[1]) return;
      var s = el("span", "seg s-" + p[0]);
      s.style.width = (p[1] / maks * 100) + "%";
      b.appendChild(s);
    });
  return b;
}

/* Proportion bar: one bar for all devices. `bagian` is [[class, count], ...]. */
function bilahProporsi(bagian, total) {
  var b = el("div", "proporsi");
  bagian.forEach(function (p) {
    if (!p[1]) return;
    var s = el("span", "seg " + p[0]);
    s.style.width = (p[1] / total * 100) + "%";
    b.appendChild(s);
  });
  return b;
}

/* Timeline: changes per day over the last `hari` days. Day grouping is display only; days with no changes are drawn as a baseline. */
function garisWaktuUbah(potret, hari) {
  var ember = [];
  var i;
  for (i = 0; i < hari; i++) ember.push(0);

  var sekarang = new Date();
  sekarang.setHours(0, 0, 0, 0);
  var awalHariIni = sekarang.getTime();
  var SEHARI = 86400000;

  potret.forEach(function (p) {
    if (p.pertama) return;
    var t = Date.parse(p.waktu);
    if (isNaN(t)) return;
    var d = new Date(t);
    d.setHours(0, 0, 0, 0);
    var selisih = Math.round((awalHariIni - d.getTime()) / SEHARI);
    if (selisih < 0 || selisih >= hari) return;
    ember[hari - 1 - selisih] += 1;
  });

  var maks = 0;
  ember.forEach(function (v) { if (v > maks) maks = v; });

  var kotak = el("div", "waktu-ubah");
  ember.forEach(function (v, idx) {
    var h = el("div", "hari" + (v ? "" : " nol"));
    if (v) h.style.height = Math.max(12, v / maks * 100) + "%";
    var kapan = idx === hari - 1 ? "hari ini"
      : idx === hari - 2 ? "kemarin"
      : (hari - 1 - idx) + " hari lalu";
    h.setAttribute("data-petunjuk",
      kapan + ": " + (v ? v + " perubahan" : "tidak ada perubahan"));
    kotak.appendChild(h);
  });
  return kotak;
}

function barisRinci(kotak, kiri, kanan, kelasKanan) {
  var b = el("div", "baris");
  b.appendChild(el("span", "nama-perangkat", kiri));
  if (kanan !== undefined && kanan !== null) {
    b.appendChild(el("span", kelasKanan || "redup", kanan));
  }
  kotak.appendChild(b);
  return b;
}

/* --- Kepatuhan ---------------------------------------------------------- */
function ringkasKepatuhan(d) {
  var kotak = document.getElementById("rinci-kepatuhan");
  if (!kotak) return;
  kosongkan(kotak);

  var perangkat = (d && d.perangkat) || [];
  var dinilai = perangkat.filter(function (p) { return p.dinilai; });
  if (!perangkat.length) {
    nadaKartu("kartu-kepatuhan", "jawab-kepatuhan",
      "Belum ada potret yang bisa dinilai", "belum");
    return;
  }

  var t = 0, s = 0, r = 0;
  dinilai.forEach(function (p) {
    var c = p.cacah || {};
    t += c.tinggi || 0; s += c.sedang || 0; r += c.rendah || 0;
  });

  if (t) {
    nadaKartu("kartu-kepatuhan", "jawab-kepatuhan",
      t + " temuan keparahan tinggi", "buruk");
  } else if (s) {
    nadaKartu("kartu-kepatuhan", "jawab-kepatuhan",
      s + " temuan keparahan sedang", "hati");
  } else if (r) {
    nadaKartu("kartu-kepatuhan", "jawab-kepatuhan",
      r + " temuan keparahan rendah", "netral");
  } else if (dinilai.length) {
    nadaKartu("kartu-kepatuhan", "jawab-kepatuhan",
      "Tidak ada temuan di " + dinilai.length + " perangkat yang dinilai", "baik");
  } else {
    nadaKartu("kartu-kepatuhan", "jawab-kepatuhan",
      "Belum ada perangkat yang dinilai", "belum");
  }

  // Devices with findings come first, so the interesting ones are never truncated.
  var urut = perangkat.slice().sort(function (a, b) {
    function berat(p) {
      var c = (p && p.cacah) || {};
      return (c.tinggi || 0) * 100 + (c.sedang || 0) * 10 + (c.rendah || 0);
    }
    return berat(b) - berat(a);
  });

  var maks = 1;
  perangkat.forEach(function (p) {
    var c = (p.cacah || {});
    var jml = (c.tinggi || 0) + (c.sedang || 0) + (c.rendah || 0);
    if (jml > maks) maks = jml;
  });

  urut.slice(0, BARIS_KARTU).forEach(function (p) {
    var c = p.cacah || {};
    var jml = (c.tinggi || 0) + (c.sedang || 0) + (c.rendah || 0);
    var b = el("div", "baris");
    b.appendChild(el("span", "nama-perangkat", p.device));
    b.appendChild(batangKeparahan(c, maks, p.dinilai));

    // One word beside the bar: the most severe level present. The full distribution is in the row's hover title.
    var teks, kelas;
    if (!p.dinilai) {
      // "Not assessed" is not the same as "zero findings".
      teks = "belum dinilai"; kelas = "redup";
      b.setAttribute("data-petunjuk", p.device
        + ": belum ada potret yang bisa dinilai, jadi NSM tidak tahu apa-apa "
        + "tentang kepatuhan perangkat ini.");
    } else if (!jml) {
      teks = "bersih"; kelas = "baik";
      b.setAttribute("data-petunjuk", p.device + ": tidak ada temuan pada "
        + (p.patuh || []).length + " aturan yang berlaku untuk perangkat ini.");
    } else {
      teks = c.tinggi ? c.tinggi + " tinggi"
        : c.sedang ? c.sedang + " sedang"
        : c.rendah + " rendah";
      kelas = c.tinggi ? "buruk" : c.sedang ? "hati" : "redup";
      b.setAttribute("data-petunjuk", p.device + ": "
        + (c.tinggi || 0) + " tinggi, " + (c.sedang || 0) + " sedang, "
        + (c.rendah || 0) + " rendah — dari " + (p.patuh || []).length
        + " aturan yang terpenuhi.");
    }
    b.appendChild(el("span", kelas, teks));
    kotak.appendChild(b);
  });
  if (urut.length > BARIS_KARTU) {
    barisRinci(kotak, "+" + (urut.length - BARIS_KARTU) + " perangkat lagi");
  }

  // Legend, drawn only when something is colored.
  if (t || s || r) {
    var leg = el("div", "legenda");
    [["s-tinggi", "tinggi"], ["s-sedang", "sedang"], ["s-rendah", "rendah"]]
      .forEach(function (p) {
        var x = el("span");
        x.appendChild(el("i", p[0]));
        x.appendChild(document.createTextNode(p[1]));
        leg.appendChild(x);
      });
    kotak.appendChild(leg);
  }
}

/* --- Potret ------------------------------------------------------------- */
function ringkasPotret(d) {
  var kotak = document.getElementById("rinci-potret");
  if (!kotak) return;
  kosongkan(kotak);

  var potret = (d && d.potret) || [];
  if (!potret.length) {
    nadaKartu("kartu-potret", "jawab-potret", "Belum ada potret", "belum");
    return;
  }

  var perangkat = {};
  potret.forEach(function (p) { perangkat[p.device] = 1; });

  // A device's first snapshot is a baseline, not a change; counting it would overcount by one per device (the Snapshots page card counts the same way).
  var perubahan = potret.filter(function (p) { return !p.pertama; }).length;

  var terbaru = null;
  potret.forEach(function (p) {
    var t = Date.parse(p.waktu);
    if (isNaN(t)) return;
    if (!terbaru || t > terbaru.t) terbaru = { t: t, p: p };
  });

  var belum = (d && d.belum_terpotret) || [];
  nadaKartu("kartu-potret", "jawab-potret",
    perubahan ? perubahan + " perubahan tercatat"
              : "Belum ada perubahan sejak potret pertama",
    belum.length ? "hati" : "netral");

  // Timeline rather than a list of numbers, since the question is "when did it change".
  kotak.appendChild(garisWaktuUbah(potret, 14));
  var kaki = el("div", "baris");
  kaki.appendChild(el("span", "nama-perangkat", "14 hari terakhir"));
  kaki.appendChild(el("span", "redup", terbaru
    ? "terakhir " + waktuRelatif(terbaru.p.waktu) : ""));
  kotak.appendChild(kaki);

  // Devices never snapshotted are named, since "0 changes" would look like a device that did not change.
  if (belum.length) {
    barisRinci(kotak, belum.length + " perangkat belum terpotret",
      belum.join(", "), "hati");
  }
}

/* --- Identitas ---------------------------------------------------------- */
function ringkasIdentitas(d) {
  var kotak = document.getElementById("rinci-identitas");
  if (!kotak) return;
  kosongkan(kotak);

  var perangkat = (d && d.perangkat) || [];
  if (!perangkat.length) {
    nadaKartu("kartu-identitas", "jawab-identitas", "Belum ada perangkat", "belum");
    return;
  }

  function cacah(vonis) {
    return perangkat.filter(function (p) { return p.vonis === vonis; }).length;
  }
  var bentrok = cacah("bertentangan");
  var belum = cacah("belum_diketahui");
  var boleh = perangkat.filter(function (p) { return p.boleh_ditulisi; }).length;

  if (bentrok) {
    nadaKartu("kartu-identitas", "jawab-identitas",
      bentrok + " perangkat identitasnya BERTENTANGAN", "buruk");
  } else if (belum) {
    // Deliberately not a bad tone: an empty marker means NSM has never asked.
    nadaKartu("kartu-identitas", "jawab-identitas",
      belum + " dari " + perangkat.length + " perangkat belum dikenali", "netral");
  } else {
    nadaKartu("kartu-identitas", "jawab-identitas",
      perangkat.length + " perangkat, identitas semuanya cocok", "baik");
  }

  var cocok = perangkat.length - bentrok - belum;
  kotak.appendChild(bilahProporsi(
    [["p-cocok", cocok], ["p-belum", belum], ["p-bentrok", bentrok]],
    perangkat.length));

  var b = el("div", "baris");
  b.appendChild(el("span", "nama-perangkat", cocok + " terbukti sama"));
  if (belum) b.appendChild(el("span", "redup", belum + " belum dikenali"));
  if (bentrok) b.appendChild(el("span", "buruk", bentrok + " bertentangan"));
  b.setAttribute("data-petunjuk",
    "Dari " + perangkat.length + " perangkat: " + cocok + " penandanya cocok, "
    + belum + " belum pernah dikenali, " + bentrok + " menjawab dengan "
    + "identitas berbeda. " + boleh + " boleh ditulisi.");
  kotak.appendChild(b);
}

/* --- Firewall ----------------------------------------------------------- */
var KEADAAN_FW = {
  aktif: "menyala",
  tanpa_aturan: "menyala, tanpa aturan",
  mati: "MATI",
  belum_terbaca: "belum terbaca"
};

function ringkasFirewall(d) {
  var kotak = document.getElementById("rinci-firewall");
  if (!kotak) return;
  kosongkan(kotak);

  var daftar = (d && d.device) || [];
  if (!daftar.length) {
    nadaKartu("kartu-firewall", "jawab-firewall",
      "Tidak ada perangkat Linux yang dipantau", "belum");
    return;
  }

  function cacah(keadaan) {
    return daftar.filter(function (f) { return f.keadaan === keadaan; }).length;
  }
  var mati = cacah("mati");
  var tanpa = cacah("tanpa_aturan");
  var belum = cacah("belum_terbaca");

  if (mati) {
    nadaKartu("kartu-firewall", "jawab-firewall",
      mati + " dari " + daftar.length + " perangkat firewallnya MATI", "buruk");
  } else if (tanpa) {
    nadaKartu("kartu-firewall", "jawab-firewall",
      tanpa + " perangkat menyala tanpa satu pun aturan", "hati");
  } else if (belum === daftar.length) {
    nadaKartu("kartu-firewall", "jawab-firewall",
      "Belum satu pun firewall terbaca", "belum");
  } else {
    nadaKartu("kartu-firewall", "jawab-firewall",
      daftar.length + " perangkat, semua firewall menyala", "baik");
  }

  // Sorted so that DOWN devices are never in the truncated part.
  var pangkat = { mati: 0, tanpa_aturan: 1, belum_terbaca: 2, aktif: 3 };
  var urut = daftar.slice().sort(function (a, b) {
    return (pangkat[a.keadaan] === undefined ? 9 : pangkat[a.keadaan])
         - (pangkat[b.keadaan] === undefined ? 9 : pangkat[b.keadaan]);
  });
  urut.slice(0, BARIS_KARTU).forEach(function (f) {
    var nada = f.keadaan === "mati" ? "buruk"
      : f.keadaan === "tanpa_aturan" ? "hati"
      : f.keadaan === "aktif" ? "baik" : "";
    var b = el("div", "baris");
    // Dot and word, never a dot alone.
    b.appendChild(el("span", "titik-keadaan " + nada));
    b.appendChild(el("span", "nama-perangkat", f.device));
    b.appendChild(el("span", nada === "baik" ? "redup" : nada,
      KEADAAN_FW[f.keadaan] || "?"));
    b.setAttribute("data-petunjuk", f.device + " (" + (f.ip || "?") + "): "
      + (KEADAAN_FW[f.keadaan] || "keadaan tidak diketahui")
      + (f.aktif ? ", kebijakan masuk " + (f.kebijakan_masuk || "?") : "")
      + ", " + (f.aturan || []).length + " aturan tercatat.");
    kotak.appendChild(b);
  });
  if (urut.length > BARIS_KARTU) {
    barisRinci(kotak, "+" + (urut.length - BARIS_KARTU) + " perangkat lagi");
  }

  // ACL denials are events, not state, so the card mentions them.
  var p = d && d.penolakan;
  if (p && p.ada_data) {
    var asal = (p.per_asal || []).length;
    barisRinci(kotak, "ditolak ACL router", asal + " alamat asal", "hati");
  }
}

/* Command builder card: the only useful number is how many devices can have commands composed, counted with the same filter as the commands page (`isiPilihanDevice`). */
function ringkasPerintah(devices) {
  var bisa = (devices || []).filter(bisaDisusun);
  var j = document.getElementById("jawab-perintah");
  if (!j) return;
  j.className = "jawab";
  j.textContent = bisa.length
    ? bisa.length + " perangkat bisa disusun perintahnya"
    : "Belum ada perangkat yang platformnya didukung";
}

var idTerpilih = null;

/* Daftar potret. */
function gambar(d) {
  var kk = document.getElementById("kartu");
  if (!kk) return;
  kosongkan(kk);

  var potret = d.potret || [];
  var perangkat = {};
  potret.forEach(function (p) { perangkat[p.device] = 1; });
  var jmlPerangkat = Object.keys(perangkat).length;

  // A real change is a snapshot that has a comparison; the first snapshot is a baseline.
  var perubahan = potret.filter(function (p) { return !p.pertama; }).length;

  kk.appendChild(kartu("Potret Tersimpan", String(potret.length),
    "satu baris = satu perubahan"));
  kk.appendChild(kartu("Perubahan Tercatat", String(perubahan),
    perubahan ? "di luar potret awal" : "belum ada sejak potret pertama"));
  kk.appendChild(kartu("Perangkat", String(jmlPerangkat),
    "punya riwayat konfigurasi"));

  var belum = d.belum_terpotret || [];
  kk.appendChild(kartu("Belum Terpotret", String(belum.length),
    belum.length ? belum.join(", ") : "semua sudah punya potret"));

  var gw = document.getElementById("garis-waktu-potret");
  if (gw) {
    kosongkan(gw);
    gw.appendChild(garisWaktuUbah(potret, 30));
    var ket = el("div", "kaki-waktu");
    ket.appendChild(el("span", null, "30 hari lalu"));
    ket.appendChild(el("span", null, "hari ini"));
    gw.appendChild(ket);
  }

  var tb = document.getElementById("baris-potret");
  kosongkan(tb);

  if (!potret.length) {
    var tr = el("tr");
    var td = el("td", "redup",
      "Belum ada potret konfigurasi. Poller mengambilnya tiap 15 menit dari "
      + "perangkat yang platformnya mendukung (saat ini Cisco IOS dan "
      + "MikroTik RouterOS) dan sedang hidup.");
    td.colSpan = 7;
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }

  potret.forEach(function (p) {
    var tr = el("tr");
    tr.dataset.id = p.id;
    tr.style.cursor = "pointer";

    var tdW = el("td", "nowrap", waktuRelatif(p.waktu));
    tdW.setAttribute("data-petunjuk", waktuLengkap(p.waktu));
    var t = Date.parse(p.waktu);
    if (!isNaN(t)) tdW.dataset.nilai = t;
    tr.appendChild(tdW);

    tr.appendChild(el("td", null, p.device));

    // The first snapshot is marked instead of showing zero changed rows, which would read as "nothing changed".
    var tdU = el("td");
    if (p.pertama) {
      tdU.appendChild(el("span", "lencana-awal", "potret awal"));
      tdU.dataset.nilai = -1;
    } else if (!p.baris_tambah && !p.baris_hapus) {
      // This snapshot was saved because its saved-status changed, not its configuration, so "+0 / -0" is not shown.
      var s = el("span", "lencana-awal", "status simpan berubah");
      s.setAttribute("data-petunjuk",
        "Konfigurasi yang berjalan TIDAK berubah dibanding potret sebelumnya. "
        + "Potret ini tersimpan karena hubungan running dengan startup-config "
        + "berubah: NSM baru mulai membacanya, konfigurasinya baru disimpan "
        + "permanen, atau startup-config-nya sendiri yang berubah.");
      tdU.appendChild(s);
      tdU.dataset.nilai = 0;
    } else {
      tdU.appendChild(el("span", "tambah", "+" + p.baris_tambah));
      tdU.appendChild(document.createTextNode(" / "));
      tdU.appendChild(el("span", "hapus", "-" + p.baris_hapus));
      tdU.dataset.nilai = (p.baris_tambah || 0) + (p.baris_hapus || 0);
    }
    tr.appendChild(tdU);

    var tdP = el("td");
    tdP.appendChild(elPelaku(p.pelaku));
    tdP.dataset.nilai = !p.pelaku ? -1 : (p.pelaku.lewat_nsm ? 1 : 0);
    tr.appendChild(tdP);

    // Saved status has three states: a platform without startup-config must not be reported as "saved".
    var tdS = el("td");
    if (!p.punya_startup) {
      tdS.appendChild(el("span", "redup", "tidak diperiksa"));
      tdS.dataset.nilai = -1;
    } else if (p.belum_disimpan) {
      var per = el("span", "belum-simpan", p.belum_disimpan + " baris belum disimpan");
      per.setAttribute("data-petunjuk",
        "Baris ini ada di konfigurasi yang berjalan sekarang tetapi tidak ada "
        + "di konfigurasi simpanan, jadi akan HILANG kalau perangkat "
        + "dinyalakan ulang. Di perangkat Cisco, menyimpannya dengan "
        + "`write memory`. Klik baris ini untuk melihat baris mana persisnya.");
      // Clicking this marker opens a different comparison: what would be lost if the device rebooted now, not what changed since the last snapshot.
      per.style.cursor = "pointer";
      per.addEventListener("click", function (e) {
        e.stopPropagation(); // do not also open the change diff
        bukaBelumDisimpan(p.id);
      });
      tdS.appendChild(per);
      tdS.dataset.nilai = p.belum_disimpan;
    } else {
      tdS.appendChild(el("span", "tambah", "tersimpan"));
      tdS.dataset.nilai = 0;
    }
    tr.appendChild(tdS);

    var tdB = el("td", "angka", String(p.baris));
    tdB.dataset.nilai = p.baris;
    tr.appendChild(tdB);

    tr.appendChild(el("td", "sidik", p.sidik));

    tr.addEventListener("click", function () { bukaBeda(p.id); });
    tb.appendChild(tr);
  });

  // Pagination is attached after rows exist; snapshots only accumulate.
  if (window.halamanTabel) halamanTabel.terapkan();

  // Reopen a previously open diff after a refresh so it does not close every 30 seconds.
  if (idTerpilih) bukaBeda(idTerpilih, true);
}

/* "Who changed this" badge, shared by the snapshots table and its diff panel. States: null (not applicable), `{lewat_nsm:true, oleh:[..]}` (matches NSM block/unblock history), `{lewat_nsm:false}` (changed with no NSM record, i.e. directly on the device). */
function elPelaku(pelaku) {
  if (!pelaku) {
    var kosong = el("span", "redup", "—");
    kosong.setAttribute("data-petunjuk",
      "Tidak berlaku untuk potret ini — potret pertama sebuah perangkat, "
      + "atau perubahan yang cuma status-simpannya (bukan isinya) yang "
      + "berbeda, tidak punya \"pelaku\" untuk dicari.");
    return kosong;
  }
  if (pelaku.lewat_nsm) {
    var namaOleh = (pelaku.oleh || []).join(", ") || "?";
    var lencanaN = el("span", "tambah", "lewat NSM (" + namaOleh + ")");
    lencanaN.setAttribute("data-petunjuk",
      "Cocok dengan " + pelaku.jumlah + " baris di riwayat blokir/buka NSM "
      + "(\"Perubahan lewat NSM\" di halaman Firewall) pada rentang waktu "
      + "yang sama: " + (pelaku.aksi || []).join(", ") + ".");
    return lencanaN;
  }
  var lencanaL = el("span", "belum-simpan", "di luar NSM");
  lencanaL.setAttribute("data-petunjuk",
    "Baris konfigurasi berubah, tapi TIDAK ADA catatan di riwayat NSM yang "
    + "menjelaskannya. Kemungkinan besar seseorang mengetik perintah "
    + "langsung di perangkat (console/SSH manual), di luar NSM sama sekali.");
  return lencanaL;
}

/* Content of the comparison box for one snapshot. */
function bukaBeda(id, diam) {
  idTerpilih = id;
  var kotak = document.getElementById("kotak-beda");
  var kepala = document.getElementById("kepala-beda");
  var isi = document.getElementById("isi-beda");

  ambilJson("/api/konfig/" + id + "/beda").then(function (d) {
    kosongkan(kepala);
    kosongkan(isi);
    kotak.hidden = false;

    // Python error replies arrive with HTTP 200 and body `{"error": "..."}`; check for it or the panel opens empty.
    if (d.error) {
      kepala.appendChild(el("span", "judul", "Tidak bisa dimuat"));
      isi.appendChild(el("div", "baris b-hapus", d.error));
      return;
    }

    kepala.appendChild(el("span", "judul", d.device || "-"));
    kepala.appendChild(el("span", "redup", waktuLengkap(d.waktu)));

    if (!d.ada_pembanding) {
      isi.appendChild(el("div", "baris b-sama", d.alasan || ""));
      return;
    }

    // Snapshot saved because only its saved-status changed, not its configuration.
    if (!d.baris_tambah && !d.baris_hapus) {
      kepala.appendChild(el("span", "redup",
        "konfigurasi yang berjalan tidak berubah dibanding potret sebelumnya"));
      isi.appendChild(el("div", "baris b-sama",
        "Potret ini tersimpan bukan karena konfigurasinya berubah, melainkan "
        + "karena status simpannya berubah — misalnya NSM baru mulai membaca "
        + "startup-config, atau konfigurasinya baru disimpan permanen. Untuk "
        + "melihat apa yang belum disimpan, klik penanda di kolom Tersimpan."));
      return;
    }

    var ringkas = el("span", "redup");
    ringkas.appendChild(el("span", "tambah", "+" + d.baris_tambah));
    ringkas.appendChild(document.createTextNode(" / "));
    ringkas.appendChild(el("span", "hapus", "-" + d.baris_hapus));
    ringkas.appendChild(document.createTextNode(
      " dibanding potret " + waktuLengkap(d.waktu_sebelum)));
    kepala.appendChild(ringkas);
    kepala.appendChild(elPelaku(d.pelaku));

    // The line kind is decided by Python, not guessed from a "+" or "-" prefix.
    var KELAS = {
      tambah: "b-tambah", hapus: "b-hapus",
      posisi: "b-posisi", sama: "b-sama"
    };
    (d.baris || []).forEach(function (b) {
      isi.appendChild(el("div", "baris " + (KELAS[b.jenis] || "b-sama"), b.teks));
    });
  }).catch(function (e) {
    kosongkan(isi);
    kotak.hidden = false;
    isi.appendChild(el("div", "baris b-hapus", "Gagal memuat perbandingan: " + e));
  });

  if (!diam) kotak.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* What would be lost if the device rebooted now. Separate from `bukaBeda()`, which answers "what changed since the previous snapshot". */
function bukaBelumDisimpan(id) {
  idTerpilih = null; // not a change diff, so do not reattach
  var kotak = document.getElementById("kotak-beda");
  var kepala = document.getElementById("kepala-beda");
  var isi = document.getElementById("isi-beda");

  ambilJson("/api/konfig/" + id + "/belum-disimpan").then(function (d) {
    kosongkan(kepala);
    kosongkan(isi);
    kotak.hidden = false;

    // Same reason as `bukaBeda()`: errors arrive with HTTP 200.
    if (d.error) {
      kepala.appendChild(el("span", "judul", "Tidak bisa dimuat"));
      isi.appendChild(el("div", "baris b-hapus", d.error));
      return;
    }

    kepala.appendChild(el("span", "judul", d.device || "-"));
    kepala.appendChild(el("span", "redup", "belum disimpan ke startup-config"));

    if (!d.punya_startup) {
      isi.appendChild(el("div", "baris b-sama", d.alasan || ""));
      return;
    }

    var ringkas = el("span", "redup");
    ringkas.appendChild(el("span", "tambah", d.akan_hilang + " baris akan hilang"));
    if (d.akan_kembali) {
      ringkas.appendChild(document.createTextNode(", "));
      ringkas.appendChild(el("span", "hapus", d.akan_kembali + " baris akan kembali"));
    }
    ringkas.appendChild(document.createTextNode(" saat perangkat dinyalakan ulang"));
    kepala.appendChild(ringkas);

    var KELAS = {
      tambah: "b-tambah", hapus: "b-hapus",
      posisi: "b-posisi", sama: "b-sama"
    };
    (d.baris || []).forEach(function (b) {
      isi.appendChild(el("div", "baris " + (KELAS[b.jenis] || "b-sama"), b.teks));
    });

    if (d.catatan) isi.appendChild(el("div", "baris b-sama", "\n" + d.catatan));
  }).catch(function (e) {
    kosongkan(isi);
    kotak.hidden = false;
    isi.appendChild(el("div", "baris b-hapus", "Gagal memuat: " + e));
  });

  kotak.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* Configuration compliance. This file knows no rules; all assessment, reasons, and fixes come from Python. */

/* Count badges per severity: three separate numbers, not one percentage. */
function lencanaKeparahan(cacah) {
  var kotak = el("span", "cacah-keparahan");
  [["tinggi", "down"], ["sedang", "hati-hati"], ["rendah", "redup"]]
    .forEach(function (pasang) {
      var n = (cacah || {})[pasang[0]] || 0;
      var l = el("span", "lencana lencana-" + pasang[1],
                 n + " " + pasang[0]);
      if (!n) l.classList.add("nol");
      kotak.appendChild(l);
    });
  return kotak;
}


/* Severity class -> short letter for the CSS class (t/s/r). */
var SEV_KELAS = { tinggi: "t", sedang: "s", rendah: "r" };
var SEV_URUT = { tinggi: 0, sedang: 1, rendah: 2 };
var SEV_IKON = { tinggi: "shield-alert", sedang: "shield", rendah: "shield-check" };
var SEV_KATA = { tinggi: "Tinggi", sedang: "Sedang", rendah: "Rendah" };

/* Icon for a finding type. Cosmetic: chosen by keywords in `aturan_id`, with the severity icon as fallback. */
function ikonTemuan(aturanId, keparahan) {
  var a = aturanId || "";
  if (/privilege|uid0|root/.test(a)) return "key-round";
  if (/telnet|vty/.test(a)) return "terminal";
  if (/ssh/.test(a)) return "lock-open";
  if (/snmp/.test(a)) return "radio";
  if (/ntp|timeout|exec/.test(a)) return "clock";
  if (/aux/.test(a)) return "terminal";
  if (/secret|hash|sandi|password/.test(a)) return "lock-open";
  if (/banner/.test(a)) return "file-text";
  if (/x11/.test(a)) return "eye";
  if (/firewall/.test(a)) return "shield-x";
  if (/http|web/.test(a)) return "globe";
  if (/pembaruan|update|patch/.test(a)) return "download";
  return SEV_IKON[keparahan] || "shield";
}

/* Remediation queue centered on findings, not devices. The same finding on many devices is merged into one card, keyed by `aturan_id`, which is stable across devices because it comes from one catalog. */
function gambarKepatuhan(d) {
  var wadahUtama = document.getElementById("antrian-temuan");
  if (!wadahUtama) return;

  var ket = document.getElementById("ket-kepatuhan");
  if (ket) ket.textContent = d.catatan || "";

  var perangkat = (d.perangkat || []).filter(function (p) { return p.dinilai; });
  var belum = (d.perangkat || []).filter(function (p) { return !p.dinilai; });

  // --- postur: total per keparahan + total aturan terpenuhi ---
  var total = { tinggi: 0, sedang: 0, rendah: 0 }, patuh = 0;
  perangkat.forEach(function (p) {
    var c = p.cacah || {};
    total.tinggi += c.tinggi || 0;
    total.sedang += c.sedang || 0;
    total.rendah += c.rendah || 0;
    patuh += (p.patuh || []).length;
  });
  gambarPosturKepatuhan(total, patuh, perangkat.length);

  // Merge findings across devices: map of aturan_id to {example finding, list of {device, finding}}. Findings are kept per device so each device's evidence line can still be shown.
  var gabung = {};
  var urutMuncul = [];
  perangkat.forEach(function (p) {
    (p.temuan || []).forEach(function (t) {
      var g = gabung[t.aturan_id];
      if (!g) {
        g = gabung[t.aturan_id] = { t: t, items: [] };
        urutMuncul.push(t.aturan_id);
      }
      g.items.push({ p: p, t: t });
    });
  });

  urutMuncul.sort(function (a, b) {
    var ta = gabung[a].t, tb = gabung[b].t;
    var sa = SEV_URUT[ta.keparahan], sb = SEV_URUT[tb.keparahan];
    if (sa !== sb) return sa - sb;
    return gabung[b].items.length - gabung[a].items.length;
  });

  // --- gambar antrian, dikelompokkan per keparahan ---
  kosongkan(wadahUtama);
  if (!urutMuncul.length) {
    wadahUtama.appendChild(el("div", "aman-kotak",
      "Tidak ada temuan pada " + perangkat.length + " perangkat yang dinilai. "
      + "Semua aturan yang berlaku terpenuhi."));
  }

  ["tinggi", "sedang", "rendah"].forEach(function (sev) {
    var ids = urutMuncul.filter(function (id) {
      return gabung[id].t.keparahan === sev;
    });
    if (!ids.length) return;

    var grup = el("div", "grup-sev " + SEV_KELAS[sev]);
    grup.dataset.sev = sev;
    var kepala = el("div", "kepala-grup");
    kepala.appendChild(ikonEl(SEV_IKON[sev]));
    var jmlTemuan = ids.reduce(function (a, id) { return a + gabung[id].items.length; }, 0);
    kepala.appendChild(document.createTextNode(
      SEV_KATA[sev] + (sev === "rendah" ? " — " + jmlTemuan + " temuan, diringkas" : "")));
    grup.appendChild(kepala);

    ids.forEach(function (id) {
      grup.appendChild(kartuTemuan(gabung[id].t, gabung[id].items));
    });
    wadahUtama.appendChild(grup);
  });

  if (belum.length) {
    var b = el("div", "ket");
    b.style.marginTop = "var(--sp-2)";
    b.textContent = belum.length + " perangkat belum dinilai "
      + "(potretnya belum diperiksa): "
      + belum.map(function (p) { return p.device; }).join(", ") + ".";
    wadahUtama.appendChild(b);
  }

  gambarSaringSev(total);
  gambarRelPerangkat(d.perangkat || []);
  gambarKatalogAkordion(d.katalog || []);
}

/* Four posture tiles: three severities plus satisfied rules. The satisfied number is a count of device-rule pairs that passed, not a percentage. */
function gambarPosturKepatuhan(total, patuh, jmlDinilai) {
  var wadah = document.getElementById("postur-kepatuhan");
  if (!wadah) return;
  kosongkan(wadah);

  function ubin(kelas, ikon, angka, kata) {
    var t = el("div", "pt-tile " + kelas);
    var ib = el("span", "ib");
    ib.appendChild(ikonEl(ikon));
    t.appendChild(ib);
    var teks = el("div");
    teks.appendChild(el("div", "n", String(angka)));
    teks.appendChild(el("div", "k", kata));
    t.appendChild(teks);
    return t;
  }
  wadah.appendChild(ubin("t", "shield-alert", total.tinggi, "temuan tinggi"));
  wadah.appendChild(ubin("s", "shield", total.sedang, "temuan sedang"));
  wadah.appendChild(ubin("r", "shield-check", total.rendah, "temuan rendah"));
  wadah.appendChild(ubin("baik", "check", patuh, "aturan terpenuhi"));
}

/* One merged finding card. `rep` is the representative finding (title, reason, fix are the same on all devices); `items` is a list of {p: device, t: finding}. */
function kartuTemuan(rep, items) {
  var sev = rep.keparahan;
  var k = SEV_KELAS[sev];
  var kartu = el("div", "fix " + k);

  var atas = el("div", "fix-atas");
  var ib = el("span", "fix-ikon");
  ib.appendChild(ikonEl(ikonTemuan(rep.aturan_id, sev)));
  atas.appendChild(ib);
  atas.appendChild(el("span", "fix-judul", rep.judul));
  var hit = el("span", "fix-hitung");
  hit.appendChild(ikonEl(ikonJenis(items[0].p)));
  hit.appendChild(document.createTextNode(items.length + " perangkat"));
  atas.appendChild(hit);
  kartu.appendChild(atas);

  // Low severity is collapsed by CSS (why/dev/fix hidden) but still built.
  if (rep.kenapa) kartu.appendChild(el("p", "fix-why", rep.kenapa));

  var dev = el("div", "fix-dev");
  items.forEach(function (it) {
    var c = el("span", "dev-chip");
    c.appendChild(ikonEl(ikonJenis(it.p)));
    c.appendChild(document.createTextNode(it.p.device));
    // Evidence line as a hover hint, if any. "Must exist" rules have no line to point to.
    if (it.t.baris_bukti) {
      c.setAttribute("data-petunjuk", "baris " + (it.t.nomor_baris || "?")
        + ":  " + it.t.baris_bukti);
    }
    dev.appendChild(c);
  });
  kartu.appendChild(dev);

  if (rep.perbaikan) {
    var det = el("details", "fix-perbaikan");
    var sum = el("summary");
    sum.appendChild(ikonEl("wrench"));
    sum.appendChild(document.createTextNode(" Cara memperbaiki"));
    det.appendChild(sum);
    det.appendChild(el("pre", null, rep.perbaikan));
    // Warning that must stay: these commands are for humans, NSM never runs them, and per-change permission rules still apply.
    var awas = el("div", "ket");
    awas.style.marginTop = "6px";
    awas.textContent = "NSM tidak menjalankan perintah ini. Ditampilkan untuk "
      + "dijalankan manusia, dan tetap tunduk pada aturan izin per perubahan.";
    det.appendChild(awas);
    kartu.appendChild(det);
  }
  return kartu;
}

/* Severity filter. Clicking a pill hides the other groups. */
function gambarSaringSev(total) {
  var wadah = document.getElementById("saring-sev");
  if (!wadah) return;
  kosongkan(wadah);

  var semuaJml = total.tinggi + total.sedang + total.rendah;
  var pils = [
    { sev: "", teks: "Semua", jml: semuaJml, ikon: null, kelas: "" },
    { sev: "tinggi", teks: "Tinggi", jml: total.tinggi, ikon: "shield-alert", kelas: "t" },
    { sev: "sedang", teks: "Sedang", jml: total.sedang, ikon: "shield", kelas: "s" },
    { sev: "rendah", teks: "Rendah", jml: total.rendah, ikon: "shield-check", kelas: "r" }
  ];

  pils.forEach(function (p) {
    var pil = el("span", "pil" + (p.sev === "" ? " aktif" : ""));
    pil.dataset.sev = p.sev;
    if (p.ikon) pil.appendChild(ikonEl(p.ikon));
    pil.appendChild(document.createTextNode(
      p.teks + (p.jml ? " " + p.jml : "")));
    pil.addEventListener("click", function () {
      var semua = wadah.querySelectorAll(".pil");
      Array.prototype.forEach.call(semua, function (q) { q.classList.remove("aktif"); });
      pil.classList.add("aktif");
      var grup = document.querySelectorAll("#antrian-temuan .grup-sev");
      Array.prototype.forEach.call(grup, function (g) {
        g.classList.toggle("disaring", p.sev !== "" && g.dataset.sev !== p.sev);
      });
    });
    wadah.appendChild(pil);
  });
}

/* Device rail on the right: context, one row per device with type icon, name, snapshot, and high/medium counts as dots. */
function gambarRelPerangkat(perangkat) {
  var wadah = document.getElementById("rel-perangkat");
  if (!wadah) return;
  kosongkan(wadah);

  var kotak = el("div", "rel-p");
  var h = el("h4");
  h.appendChild(ikonEl("layers"));
  h.appendChild(document.createTextNode("Per perangkat"));
  kotak.appendChild(h);

  perangkat.forEach(function (p) {
    var baris = el("div", "rel-baris");
    var id = el("span", "id");
    id.appendChild(ikonEl(ikonJenis(p)));
    baris.appendChild(id);

    var nm = el("span", "nm");
    nm.appendChild(document.createTextNode(p.device));
    nm.appendChild(el("br"));
    var s = el("small", null, "potret #" + p.snapshot_id);
    nm.appendChild(s);
    baris.appendChild(nm);

    var mini = el("span", "mini");
    if (!p.dinilai) {
      mini.appendChild(el("span", "dotk belum", "?"));
    } else {
      var c = p.cacah || {};
      mini.appendChild(el("span", "dotk " + (c.tinggi ? "t" : "nol"), String(c.tinggi || 0)));
      mini.appendChild(el("span", "dotk " + (c.sedang ? "s" : "nol"), String(c.sedang || 0)));
    }
    baris.appendChild(mini);
    kotak.appendChild(baris);
  });
  wadah.appendChild(kotak);
}

/* Catalog as an accordion per platform instead of a 23-row table. */
function gambarKatalogAkordion(katalog) {
  var wadah = document.getElementById("katalog-aturan");
  if (!wadah) return;
  kosongkan(wadah);

  // Group by platform, sorted by severity within each group.
  var perPlatform = {};
  katalog.forEach(function (a) {
    (perPlatform[a.platform] = perPlatform[a.platform] || []).push(a);
  });

  var LABEL = { cisco_ios: "Cisco IOS", linux: "Linux" };
  var IKON = { cisco_ios: "router", linux: "server" };

  Object.keys(perPlatform).forEach(function (plat, idx) {
    var aturan = perPlatform[plat].slice().sort(function (a, b) {
      return SEV_URUT[a.keparahan] - SEV_URUT[b.keparahan];
    });
    var tinggi = aturan.filter(function (a) { return a.keparahan === "tinggi"; }).length;

    var det = el("details", "kat-grp");
    if (idx === 0) det.open = false;
    var sum = el("summary");
    sum.appendChild(ikonEl(IKON[plat] || "cpu"));
    sum.appendChild(document.createTextNode(LABEL[plat] || plat));
    sum.appendChild(el("span", "cacah",
      aturan.length + " aturan" + (tinggi ? " · " + tinggi + " tinggi" : "")));
    det.appendChild(sum);

    var list = el("div", "kat-list");
    aturan.forEach(function (a) {
      var it = el("div", "kat-item");
      it.setAttribute("data-petunjuk", a.kenapa || a.judul);
      it.appendChild(el("span", "dt " + a.keparahan));
      it.appendChild(document.createTextNode(a.judul));
      list.appendChild(it);
    });
    det.appendChild(list);
    wadah.appendChild(det);
  });
  // Hover hints need no re-attachment: petunjuk.js delegates `pointerover` at document level.
}

/* Human-readable word and color for each verdict. `belum_diketahui` is deliberately not red: an empty marker means NSM has never asked, while a conflicting marker means it asked and got a different answer. */
var VONIS = {
  sama: { teks: "Terbukti sama", kelas: "v-sama" },
  kemungkinan_sama: { teks: "Kemungkinan sama", kelas: "v-mungkin" },
  bertentangan: { teks: "BERTENTANGAN", kelas: "v-bentrok" },
  belum_diketahui: { teks: "Belum dikenali", kelas: "v-belum" }
};

function gambarIdentitas(d) {
  var kotak = document.getElementById("identitas");
  if (!kotak) return;
  kosongkan(kotak);

  var perangkat = d.perangkat || [];
  var bentrok = perangkat.filter(function (p) { return p.vonis === "bertentangan"; });
  var ket = document.getElementById("ket-identitas");
  if (ket) {
    ket.textContent = bentrok.length
      ? (bentrok.length + " perangkat menjawab dengan identitas yang BERBEDA "
         + "dari yang tersimpan. Jalur menulis ke perangkat itu diblokir.")
      : "";
    ket.className = bentrok.length ? "ket peringatan" : "ket";
  }

  // Summary in the title so the panel can be collapsed: the title holds the answer, the panel holds the evidence.
  if (window.NSMLipat && NSMLipat.ringkas) {
    NSMLipat.ringkas("identitas", bentrok.length
      ? bentrok.length + " perangkat identitasnya BERTENTANGAN"
      : perangkat.length + " perangkat, identitas semuanya cocok");
  }

  // Card grid rather than a five-column table. Conflicting devices sort first since that is the only state needing action.
  var urut = perangkat.slice().sort(function (a, b) {
    var ua = a.vonis === "bertentangan" ? 0 : a.vonis === "belum_diketahui" ? 1 : 2;
    var ub = b.vonis === "bertentangan" ? 0 : b.vonis === "belum_diketahui" ? 1 : 2;
    return ua - ub;
  });

  var grid = el("div", "grid-identitas");
  urut.forEach(function (p) {
    var v = VONIS[p.vonis] || VONIS.belum_diketahui;
    var kartu = el("div", "kartu-id " + v.kelas);

    var atas = el("div", "id-atas");
    var ib = el("span", "id-ikon");
    ib.appendChild(ikonEl(p.vonis === "bertentangan" ? "shield-alert" : "server"));
    atas.appendChild(ib);
    var idn = el("div", null); idn.style.minWidth = "0";
    idn.appendChild(el("div", "id-nama", p.device));
    idn.appendChild(el("div", "id-alamat", p.ip_address));
    atas.appendChild(idn);
    atas.appendChild(el("span", "lencana-vonis " + v.kelas, v.teks));
    kartu.appendChild(atas);

    // Markers are built with textContent via `el()`, not innerHTML: hostnames come from devices.
    var wadahP = el("div", "id-penanda");
    var penanda = p.penanda || [];
    if (!penanda.length) {
      wadahP.appendChild(el("span", "redup kecil", "belum ada penanda tersimpan"));
    } else {
      penanda.forEach(function (x) {
        var b = el("span", "penanda");
        b.appendChild(el("span", "penanda-jenis", x.jenis));
        b.appendChild(el("span", "penanda-nilai", x.nilai));
        wadahP.appendChild(b);
      });
    }
    kartu.appendChild(wadahP);

    var kaki = el("div", "id-kaki");
    var ikonTulis = ikonEl(p.boleh_ditulisi ? "lock-open" : "lock");
    var tulis = el("span", p.boleh_ditulisi ? "ya-tulis" : "redup");
    tulis.appendChild(ikonTulis);
    tulis.appendChild(document.createTextNode(
      " " + (p.boleh_ditulisi ? "boleh ditulisi" : "jalur tulis diblokir")));
    // The reason is a hover hint, not printed in full on each card.
    if (p.alasan) tulis.setAttribute("data-petunjuk", p.alasan);
    kaki.appendChild(tulis);
    kartu.appendChild(kaki);

    grid.appendChild(kartu);
  });
  kotak.appendChild(grid);
}

/* Per-device firewall. Three states all yield an empty rule list with opposite meanings: firewall on with no rules (default policy applies, perhaps `deny incoming`), firewall off (host is open), never read (NSM knows nothing). So each device shows a state sentence before its table. */
/* History of firewall changes made via NSM. Rejected attempts are shown and colored too, so an attempt to block NSM's own address leaves a trace. */
function gambarRiwayatFirewall(baris) {
  var tb = document.getElementById("baris-fw-ubah");
  if (!tb) return;
  kosongkan(tb);

  if (!baris.length) {
    var tr = el("tr");
    var td = el("td", "redup",
      "Belum ada perubahan firewall lewat NSM. Perubahan yang dilakukan "
      + "langsung di server tetap terlihat di kartu di atas.");
    td.colSpan = 8;
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }

  baris.forEach(function (r) {
    var tr = el("tr");
    tr.appendChild(el("td", "nowrap", waktuLengkap(r.waktu)));
    tr.appendChild(el("td", null, r.device));
    tr.appendChild(el("td", null, r.aksi));
    tr.appendChild(el("td", "path", r.ip_sasaran || "-"));
    tr.appendChild(el("td", "angka", r.menit ? r.menit + " mnt" : "-"));
    tr.appendChild(el("td", null, r.alasan || "-"));
    tr.appendChild(el("td", null, r.oleh));
    var td = el("td", "hasil-fw" + (r.berhasil ? "" : " gagal"), r.hasil);
    // Raw evidence is a hover hint rather than a column.
    if (r.bukti) td.setAttribute("data-petunjuk", r.bukti);
    tr.appendChild(td);
    tb.appendChild(tr);
  });
}

/* Router ACL denials: who TRIED to cross and was denied. Only the router ACL can answer this, since only it ends with `deny ip any any log`. Placed above the rule cards because someone suspicious wants events first. Counts are stated as they are: IOS merges similar denials in one time window, so "1 packet" means at least one. */
/* NSM's own address: attempts from it are service checks denied by the ACL, not attacks. Written directly rather than fetched from /api/devices because the list is purely cosmetic (icon and card color). */

/* How severe a source address is, from its attempt pattern. Cosmetic: only picks a card color. */
/* Card edge color = category (computed by Python in `report_service.penolakan_acl`): pengecekan (gray, NSM itself/ICMP/service replies), diblokir (orange, real attacks the firewall denied), tembus (red, attacker with a live connection to a service). The frontend only maps category to color. */
function kelasPenyerang(a) { return a.kategori || "diblokir"; }

function ikonPenyerang(a) {
  if (a.kategori === "tembus") return "siren";
  if (a.kategori === "diblokir") return "shield-ban";
  if (a.lokal) return "shield-check";           // NSM membuktikan firewall menutup
  if (a.jenis_jinak === "icmp") return "radio";
  return "activity";                            // balasan layanan / lainnya
}

/* Description of each icon and edge color; single source for the legend. [icon, category, text] */
var filterPenolakan = "semua"; // active category on the denial filter button
var LEGENDA_PENYERANG = [
  ["shield-check", "pengecekan",
   "Pemeriksaan NSM — mengetuk port yang seharusnya tertutup untuk MEMBUKTIKAN " +
   "firewall menutupnya"],
  ["radio", "pengecekan",
   "Lalu lintas ICMP (ping) untuk pengecekan, atau balasan layanan yang ditolak " +
   "di jalur pulang"],
  ["shield-ban", "diblokir",
   "Serangan sungguhan yang DIBLOKIR firewall — percobaan masuk ke port layanan"],
  ["siren", "tembus",
   "Serangan yang TEMBUS — penyerang punya koneksi hidup ke sebuah layanan, " +
   "perlu segera diperiksa"]
];

function gambarPenolakan(p) {
  var kotak = document.getElementById("penolakan-acl");
  if (!kotak) return;
  kosongkan(kotak);

  if (!p || !p.ada_data) {
    // "No denials yet" and "unreadable" are distinguished: both give an empty list.
    kotak.appendChild(el("div", "redup",
      (p && p.catatan && p.catatan.indexOf("belum dibuat") >= 0)
        ? p.catatan
        : "Belum ada satu pun percobaan yang ditolak ACL router sejak "
          + "penyimpanan log dinyalakan. Itu kabar baik, bukan kegagalan "
          + "membaca."));
    return;
  }

  // Category filter buttons. Counts are computed first so pills can show them, and empty pills stay (dimmed) so "0 tembus" reads as good news.
  var semua = p.per_asal || [];
  var cacah = { pengecekan: 0, diblokir: 0, tembus: 0 };
  semua.forEach(function (a) { cacah[a.kategori] = (cacah[a.kategori] || 0) + 1; });

  var filterBar = el("div", "filter-penyerang");
  [["semua", "Semua", semua.length],
   ["tembus", "Tembus", cacah.tembus],
   ["diblokir", "Diblokir", cacah.diblokir],
   ["pengecekan", "Pengecekan", cacah.pengecekan]].forEach(function (f) {
    var pil = el("button", "pil-filter" + (filterPenolakan === f[0] ? " aktif" : "")
      + (f[0] !== "semua" ? " " + f[0] : ""));
    pil.type = "button";
    pil.appendChild(document.createTextNode(f[1] + " "));
    pil.appendChild(el("span", "pil-cacah", String(f[2])));
    pil.addEventListener("click", function () {
      filterPenolakan = f[0];
      gambarPenolakan(p);
    });
    filterBar.appendChild(pil);
  });
  kotak.appendChild(filterBar);

  // One card per source address, newest first. Edge color from the category.
  var perAsal = semua.slice()
    .filter(function (a) {
      return filterPenolakan === "semua" || a.kategori === filterPenolakan;
    })
    .sort(function (a, b) { return (b.terakhir || "").localeCompare(a.terakhir || ""); });

  if (!perAsal.length) {
    kotak.appendChild(el("div", "redup kecil",
      "Tidak ada asal pada kategori ini."
      + (filterPenolakan === "tembus"
         ? " Tidak ada satu pun serangan yang tembus firewall — itu kabar baik."
         : "")));
    return;
  }

  var grid = el("div", "kotak-penyerang");
  perAsal.forEach(function (a) {
    var kartu = el("div", "kartu-penyerang " + kelasPenyerang(a));

    var atas = el("div", "pnyr-atas");
    var ib = el("span", "pnyr-ikon");
    ib.appendChild(ikonEl(ikonPenyerang(a)));
    atas.appendChild(ib);

    var idn = el("div");
    idn.appendChild(el("div", "pnyr-asal", a.asal));
    var subLabel;
    if (a.lokal) {
      subLabel = "pemeriksaan NSM — membuktikan firewall menutup port yang "
        + "seharusnya tertutup";
    } else if (a.kategori === "pengecekan") {
      subLabel = (a.jenis_jinak === "icmp")
        ? "lalu lintas ICMP untuk pengecekan"
        : "lalu lintas balasan layanan"
            + (a.port_layanan ? " (port asal " + a.port_layanan + ")" : "");
    } else if (a.kategori === "tembus") {
      subLabel = "SERANGAN TEMBUS — ada koneksi hidup ke layanan, perlu diperiksa";
    } else {   // diblokir
      subLabel = "serangan diblokir firewall — "
        + (a.tujuan_jumlah >= 5 ? "menyasar " + a.tujuan_jumlah + " tujuan berbeda"
                                : "satu tujuan");
    }
    idn.appendChild(el("div", "pnyr-lokal", subLabel));
    atas.appendChild(idn);

    var ang = el("div", "pnyr-angka");
    ang.appendChild(el("div", "n", String(a.percobaan)));
    ang.appendChild(el("div", "k", "percobaan"));
    atas.appendChild(ang);
    kartu.appendChild(atas);

    var tuj = el("div", "pnyr-tujuan");
    (a.tujuan || []).forEach(function (t) {
      tuj.appendChild(el("span", "tujuan-chip", t));
    });
    if (a.tujuan_jumlah > (a.tujuan || []).length) {
      tuj.appendChild(el("span", "tujuan-chip",
        "+" + (a.tujuan_jumlah - a.tujuan.length) + " lagi"));
    }
    kartu.appendChild(tuj);

    var kaki = el("div", "pnyr-kaki");
    kaki.textContent = "≥ " + a.paket + " paket · terakhir " + waktuLengkap(a.terakhir);
    kartu.appendChild(kaki);

    // Per-source detail dropdown: the latest attempts line by line (`a.rincian` from Python, at most 15 per source).
    if (a.rincian && a.rincian.length) {
      var det = el("details", "pnyr-detail");
      var sum = el("summary");
      sum.appendChild(ikonEl("list-checks"));
      sum.appendChild(document.createTextNode(
        " Rincian " + a.rincian.length + " percobaan terakhir"));
      det.appendChild(sum);

      var tbl = el("table", "tabel-rincian");
      var thead = el("thead");
      var trh = el("tr");
      ["Waktu", "Proto", "Dari → Tujuan", "×", "Sumber"].forEach(function (h) {
        trh.appendChild(el("th", null, h));
      });
      thead.appendChild(trh);
      tbl.appendChild(thead);

      var tb = el("tbody");
      a.rincian.forEach(function (r) {
        var tr = el("tr", r.jenis ? "baris-balasan" : null);
        tr.appendChild(el("td", "waktu", waktuLengkap(r.waktu)));
        tr.appendChild(el("td", null, r.proto || "-"));
        var alur = (a.asal || "?") + (r.port_dari ? ":" + r.port_dari : "")
          + " → " + (r.ke || "?") + (r.port_ke ? ":" + r.port_ke : "");
        var tdAlur = el("td", "mono", alur);
        if (r.jenis === "balasan") tdAlur.title = "Port asal " + r.port_dari
          + " (layanan) → port acak tinggi: pola BALASAN, bukan percobaan masuk";
        else if (r.jenis === "icmp") tdAlur.title =
          "Paket ICMP (ping/diagnostik), bukan percobaan ke port layanan";
        tr.appendChild(tdAlur);
        tr.appendChild(el("td", "angka", "×" + (r.jumlah || 1)));
        // `acl` = "ufw" means from the Linux server log; otherwise from the router ACL.
        tr.appendChild(el("td", "redup",
          (r.acl === "ufw") ? "ufw" : "ACL router"));
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      det.appendChild(bungkusTabel(tbl));
      kartu.appendChild(det);
    }

    grid.appendChild(kartu);
  });

  kotak.appendChild(grid);
  // 5 cards per page, newest first; attached after the grid is in the DOM because the controls are inserted as a sibling of the grid.
  if (window.halamanTabel) halamanTabel.pasang(grid, { perHal: 5 });

  // Legend below the cards, built from LEGENDA_PENYERANG.
  var legenda = el("div", "legenda-penyerang");
  LEGENDA_PENYERANG.forEach(function (item) {
    var b = el("div", "leg-item " + item[1]);
    var ik = el("span", "leg-ikon");
    ik.appendChild(ikonEl(item[0]));
    b.appendChild(ik);
    b.appendChild(el("span", "leg-teks", item[2]));
    legenda.appendChild(b);
  });
  legenda.appendChild(el("div", "leg-warna",
    "Warna tepi kartu = kategori: merah tembus, oranye diblokir, abu pengecekan."));
  kotak.appendChild(legenda);

  if (p.catatan) kotak.appendChild(el("div", "kecil redup", p.catatan));

  var det = el("details", "pnyr-mentah");
  var sum = el("summary");
  sum.appendChild(ikonEl("terminal"));
  sum.appendChild(document.createTextNode(" Baris terakhir apa adanya, router dan ufw"));
  det.appendChild(sum);
  var pre = el("pre");
  (p.daftar || []).slice(0, 12).forEach(function (r) {
    var baris = (r.aksi || "") + " " + (r.proto || "") + " "
      + (r.dari || "") + (r.port_dari ? ":" + r.port_dari : "")
      + " -> " + (r.ke || "") + (r.port_ke ? ":" + r.port_ke : "")
      + "  x" + (r.jumlah || 1) + "   " + (r.router || "")
      + (r.cap_router ? "   jam router: " + r.cap_router : "");
    pre.appendChild(document.createTextNode(baris + "\n"));
  });
  det.appendChild(pre);
  kotak.appendChild(det);
}

/* Firewall rule quality. All assessment comes from Python; JavaScript knows no quality rules. The display deliberately matches the config compliance findings (per-device cards, severity bars, collapsed findings). */
/* Rule quality as a queue, like config compliance: similar findings on many devices merge into one card, keyed by `t.judul` since firewall rule quality has no fixed catalog with `aturan_id`. Same logic as `gambarKepatuhan()`. */
function gambarMutuAturan(daftar) {
  var kotak = document.getElementById("mutu-aturan");
  if (!kotak) return;
  kosongkan(kotak);

  daftar = daftar || [];
  if (!daftar.length) {
    kotak.appendChild(el("div", "redup",
      "Belum ada perangkat yang aturannya bisa diperiksa."));
    return;
  }

  var total = { tinggi: 0, sedang: 0, rendah: 0 };
  var gabung = {}, urut = [];
  daftar.forEach(function (p) {
    var c = p.cacah || {};
    total.tinggi += c.tinggi || 0; total.sedang += c.sedang || 0; total.rendah += c.rendah || 0;
    (p.temuan || []).forEach(function (t) {
      var g = gabung[t.judul];
      if (!g) { g = gabung[t.judul] = { t: t, items: [] }; urut.push(t.judul); }
      g.items.push({ p: p, t: t });
    });
  });

  if (!urut.length) {
    kotak.appendChild(el("div", "aman-kotak",
      "Tidak ada temuan pada aturan " + daftar.length + " perangkat yang diperiksa."));
  } else {
    urut.sort(function (a, b) {
      var sa = SEV_URUT[gabung[a].t.keparahan], sb = SEV_URUT[gabung[b].t.keparahan];
      if (sa !== sb) return sa - sb;
      return gabung[b].items.length - gabung[a].items.length;
    });
    ["tinggi", "sedang", "rendah"].forEach(function (sev) {
      var ids = urut.filter(function (j) { return gabung[j].t.keparahan === sev; });
      if (!ids.length) return;
      var grup = el("div", "grup-sev " + SEV_KELAS[sev]);
      var kepala = el("div", "kepala-grup");
      kepala.appendChild(ikonEl(SEV_IKON[sev]));
      kepala.appendChild(document.createTextNode(SEV_KATA[sev]));
      grup.appendChild(kepala);
      ids.forEach(function (j) {
        var rep = gabung[j].t;
        if (!rep.aturan_id) rep = Object.assign({}, rep, { aturan_id: "fw_" + j });
        grup.appendChild(kartuTemuan(rep, gabung[j].items));
      });
      kotak.appendChild(grup);
    });
  }

  // Scope of the check, stated once for the whole section (ufw has no per-rule traffic counters).
  var takPeriksa = daftar.filter(function (p) { return p.tak_terperiksa; });
  if (takPeriksa.length) {
    var batas = el("div", "kecil redup");
    batas.style.marginTop = "var(--sp-2)";
    batas.appendChild(el("span", "judul-bantu", "Satu jenis temuan tidak bisa diperiksa"));
    batas.setAttribute("data-petunjuk", takPeriksa[0].tak_terperiksa);
    batas.setAttribute("tabindex", "0");
    kotak.appendChild(batas);
  }
}

/* Firewall posture strip: four numbers from three sources (device state, router denials, rule quality), so it is computed in `gambarFirewall()`, the only function holding all three. */
function gambarPosturFirewall(d) {
  var wadah = document.getElementById("postur-firewall");
  if (!wadah) return;
  kosongkan(wadah);

  var daftar = d.device || [];
  var mati = daftar.filter(function (f) { return f.keadaan === "mati"; }).length;
  var totalDitolak = ((d.penolakan && d.penolakan.per_asal) || [])
    .reduce(function (a, x) { return a + x.percobaan; }, 0);
  var totalMutu = { tinggi: 0, sedang: 0 };
  (d.temuan || []).forEach(function (p) {
    var c = p.cacah || {};
    totalMutu.tinggi += c.tinggi || 0;
    totalMutu.sedang += c.sedang || 0;
  });

  function ubin(kelas, ikon, angka, kata) {
    var t = el("div", "pt-tile " + kelas);
    var ib = el("span", "ib");
    ib.appendChild(ikonEl(ikon));
    t.appendChild(ib);
    var teks = el("div");
    teks.appendChild(el("div", "n", String(angka)));
    teks.appendChild(el("div", "k", kata));
    t.appendChild(teks);
    return t;
  }
  wadah.appendChild(ubin(mati ? "t" : "baik", mati ? "shield-x" : "shield-check",
    daftar.length, "perangkat" + (mati ? ", " + mati + " mati firewall-nya" : ", semua menyala")));
  wadah.appendChild(ubin(totalDitolak ? "s" : "baik", "shield-alert",
    totalDitolak, "percobaan ditolak"));
  wadah.appendChild(ubin(totalMutu.tinggi ? "t" : "baik", "shield-alert",
    totalMutu.tinggi, "aturan tinggi"));
  wadah.appendChild(ubin(totalMutu.sedang ? "s" : "baik", "shield",
    totalMutu.sedang, "aturan sedang"));
}

var LENCANA_FW = {
  aktif: "MENYALA", tanpa_aturan: "MENYALA, TANPA ATURAN",
  mati: "MATI", belum_terbaca: "BELUM TERBACA"
};

var IKON_LAPIS = { ufw: "server", acl_router: "router", winfw: "hard-drive" };

/* One summary card per firewall LAYER, not per device: which firewalls NSM uses, where, what they protect, rule count, and whether they log denials. */
function gambarPetaLapis(daftar) {
  var wadah = document.getElementById("peta-lapis");
  if (!wadah) return;
  kosongkan(wadah);

  (daftar || []).forEach(function (l) {
    var kartu = el("div", "kartu-lapis " + l.lapis);

    var atas = el("div", "kl-atas");
    var ib = el("span", "kl-ikon");
    ib.appendChild(ikonEl(IKON_LAPIS[l.lapis] || "shield"));
    atas.appendChild(ib);
    atas.appendChild(el("span", "kl-nama", l.nama));
    kartu.appendChild(atas);

    kartu.appendChild(el("div", "kl-angka", String(l.jumlah_aturan)));
    kartu.appendChild(el("div", "kl-angka-lab", "baris aturan"));

    function baris(label, nilai) {
      var b = el("div", "kl-baris");
      b.appendChild(el("span", "lab", label));
      b.appendChild(el("span", "val", nilai));
      kartu.appendChild(b);
    }
    baris("Letak", l.letak);
    baris("Melindungi", l.melindungi);

    // Windows Firewall does not necessarily log denials (LogBlocked is off by default). The badge has three states: not enabled, active, and previously logging but stopped, so frozen denial counts are not shown as healthy monitoring.
    var lenc;
    if (l.pembacaan_macet) {
      lenc = el("span", "kl-lencana bahaya");
      lenc.appendChild(ikonEl("shield-alert"));
      lenc.appendChild(document.createTextNode(
        " pembacaan BERHENTI — angka di bawah beku sejak "
        + waktuLengkap(l.terbaca_terakhir)));
      lenc.setAttribute("data-petunjuk",
        "Aturannya masih terbaca, tetapi log penolakannya tidak. "
        + l.penolakan_tercatat + " penolakan yang tercatat berasal dari "
        + "sebelum pembacaan berhenti, BUKAN keadaan sekarang. Selama lencana "
        + "ini menyala, lapis ini tidak sedang diawasi.");
    } else if (!l.mencatat_penolakan) {
      lenc = el("span", "kl-lencana warn");
      lenc.appendChild(ikonEl("alert-triangle"));
      lenc.appendChild(document.createTextNode(" belum mencatat penolakan"));
    } else {
      lenc = el("span", "kl-lencana ok");
      lenc.appendChild(ikonEl("shield-check"));
      lenc.appendChild(document.createTextNode(
        " " + l.penolakan_tercatat + " penolakan tercatat"));
    }
    kartu.appendChild(lenc);

    // Recovery box: if NSM knows the exact cause (lost read permission) and has the fix command, show it on the card so it can be copied.
    if (l.pembacaan_macet && l.sebab && l.pemulihan) {
      var box = el("div", "kl-pemulihan");
      box.appendChild(el("div", "klp-sebab", l.sebab));
      box.appendChild(el("div", "klp-judul",
        "Perbaikan (jalankan di PowerShell/CMD sebagai Administrator):"));
      var kode = el("div", "klp-kode");
      kode.appendChild(el("code", null, l.pemulihan));
      var salin = el("button", "klp-salin");
      salin.type = "button";
      salin.textContent = "Salin";
      salin.addEventListener("click", function () {
        var teks = l.pemulihan;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(teks).then(function () {
            salin.textContent = "Tersalin";
            setTimeout(function () { salin.textContent = "Salin"; }, 1500);
          });
        }
      });
      kode.appendChild(salin);
      box.appendChild(kode);
      box.appendChild(el("div", "klp-catatan",
        "Grant di FOLDER dengan pewarisan (OI)(CI) supaya izin tidak hilang "
        + "lagi tiap kali log penuh dan berputar. Sesudah dijalankan, kartu "
        + "pulih sendiri dalam ≤5 menit."));
      kartu.appendChild(box);
    }

    // ACL drift: the only layer that can change without going through NSM, so it is the second, most prominent badge.
    if (l.drift && l.drift.length) {
      var d2 = el("span", "kl-lencana bahaya");
      d2.appendChild(ikonEl("shield-alert"));
      d2.appendChild(document.createTextNode(
        " ACL berubah di luar NSM, " + waktuLengkap(l.drift[l.drift.length - 1])));
      d2.setAttribute("data-petunjuk",
        "Baris ACL berubah langsung lewat CLI router, bukan lewat NSM. "
        + "Periksa 'Aturan tiap perangkat, per lapis' di bawah untuk "
        + "bandingkan dengan potret sebelumnya di halaman Potret Konfigurasi.");
      kartu.appendChild(d2);
    }

    wadah.appendChild(kartu);
  });
}

/* Router ACL summary, not per-rule detail like ufw/Windows: the Cisco router has no structured `firewall_aturan` table, its line count comes from the snapshot text (`report_service._hitung_baris_acl`). Shows the summary plus a link to where the detail lives. */
function gambarAclRouterRingkas(petaLapis, drift) {
  var wadah = document.getElementById("firewall-acl");
  if (!wadah) return;
  kosongkan(wadah);

  var lapis = (petaLapis || []).filter(function (l) { return l.lapis === "acl_router"; })[0];
  if (!lapis) {
    wadah.appendChild(el("div", "redup", "Belum ada router yang dipantau."));
    return;
  }

  var kartu = el("div", "kartu-fw2 aktif");
  var atas = el("div", "fw2-atas");
  var ib = el("span", "fw2-ikon");
  ib.appendChild(ikonEl("router"));
  atas.appendChild(ib);
  var idn = el("div", null);
  idn.style.minWidth = "0";
  idn.appendChild(el("div", "fw2-nama", lapis.nama));
  idn.appendChild(el("div", "fw2-ip", lapis.letak));
  atas.appendChild(idn);
  atas.appendChild(el("span", "fw2-status aktif", lapis.jumlah_aturan + " baris"));
  kartu.appendChild(atas);

  kartu.appendChild(el("div", "ringkas-fw",
    lapis.penolakan_tercatat + " percobaan ditolak tercatat. Daftar baris "
    + "lengkapnya (dan riwayat perubahannya) ada di halaman Potret "
    + "Konfigurasi, bukan di sini — router tidak menyimpan aturan per "
    + "baris terstruktur seperti ufw."));

  if (lapis.drift && lapis.drift.length) {
    var d3 = el("div", "kl-lencana bahaya");
    d3.style.marginTop = "var(--sp-2)";
    d3.appendChild(ikonEl("shield-alert"));
    d3.appendChild(document.createTextNode(
      " ACL berubah di luar NSM, " + waktuLengkap(lapis.drift[lapis.drift.length - 1])));
    kartu.appendChild(d3);
  }

  wadah.appendChild(kartu);
}

/* Firewall rules as a paginated 6-column table for devices with many rules (laptop Windows Firewall). The `Ke` column (for example "TCP/5353") is split into protocol and port. */
function tabelAturanFw(aturan) {
  var bungkus = el("div", "fw2-tabel-bungkus");
  var tbl = el("table", "tabel-aturan-fw");
  var thead = el("thead");
  var trh = el("tr");
  ["#", "Protokol", "Port", "Aksi", "Alamat", "Aturan"].forEach(function (h) {
    trh.appendChild(el("th", null, h));
  });
  thead.appendChild(trh);
  tbl.appendChild(thead);

  var tb = el("tbody");
  aturan.forEach(function (a) {
    // "TCP/5353" -> proto TCP, port 5353 ; "TCP" -> TCP, Any ; "Any" -> Any, Any
    var bagian = String(a.ke || "Any").split("/");
    var proto = bagian[0] || "Any";
    var port = bagian.length > 1 ? bagian[1] : "Any";

    var tr = el("tr");
    tr.appendChild(el("td", "angka redup", "#" + a.nomor));
    tr.appendChild(el("td", "mono", proto));
    tr.appendChild(el("td", "mono", port));
    var tdAksi = el("td", (String(a.aksi).toLowerCase() === "block"
      || String(a.aksi).toLowerCase() === "deny") ? "aksi-blok" : "aksi-izin");
    tdAksi.textContent = a.aksi;
    tr.appendChild(tdAksi);
    var tdAlamat = el("td", "mono");
    tdAlamat.appendChild(document.createTextNode(a.dari));
    if (a.terbuka_luas) {
      tdAlamat.appendChild(document.createTextNode(" "));
      tdAlamat.appendChild(el("span", "luas", "(siapa saja)"));
    }
    tr.appendChild(tdAlamat);
    // Long Windows rule names are ellipsized; the full text shows on hover.
    var tdNama = el("td", "nama-aturan-fw");
    tdNama.textContent = a.komentar || "-";
    if (a.komentar) tdNama.title = a.komentar;
    tr.appendChild(tdNama);
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  bungkus.appendChild(tbl);
  // 10 rows per page; page controls are inserted as a sibling of the table inside the wrapper.
  if (window.halamanTabel) halamanTabel.pasang(tbl, { perHal: 10 });
  return bungkus;
}

/* Breach detection: live connections from unregistered hosts to sensitive services. Assessment is in Python; this only draws. */
/* Automatic guard (stage 1): shows the auto-ban decision logic (immune allowlist, auto-ban candidates vs review). Decisions come from Python. Execution is not active, so block commands are shown as copyable references. */
var POLA_JAGA = {
  tembus:   { ikon: "siren",       teks: "Tembus" },
  memindai: { ikon: "scan-line",   teks: "Memindai" },
  gigih:    { ikon: "radar",       teks: "Gedoran berulang" },
  kecil:    { ikon: "shield-alert", teks: "Percobaan kecil" }
};

/* Send a block/unblock action to the server, then refresh. Used by the 1-click buttons; all go through `kirimJson`, which adds the CSRF token. */
function aksiBan(url, badan, tombol, selesai) {
  var teksAsli = tombol.textContent;
  tombol.disabled = true;
  tombol.textContent = "…";
  kirimJson(url, badan).then(function (r) {
    if (r && r.ditolak) {
      // The allowlist guard refused: show the reason instead of failing silently.
      alert("Ditolak pengaman:\n" + (r.pesan || "IP dilindungi."));
      tombol.disabled = false; tombol.textContent = teksAsli;
    } else if (r && r.ok === false) {
      alert("Tidak diblokir: " + (r.error || "tidak diketahui")
        + (r.detail ? "\n\n" + r.detail : ""));
      tombol.disabled = false; tombol.textContent = teksAsli;
    } else {
      if (selesai) selesai();
      if (typeof muat === "function") muat();   // segarkan halaman
    }
  }).catch(function (e) {
    alert("Gagal menghubungi server: " + e);
    tombol.disabled = false; tombol.textContent = teksAsli;
  });
}

/* Block ALL auto candidates at once. Sequential, not parallel: each real block opens a new SSH session to the same server to confirm it is still reachable (`ubah_firewall._masih_terjangkau`), and concurrent sessions only add risk. One failure must not stop the rest; each request is caught individually and the summary (succeeded/rejected/failed) is shown after all are tried. */
function blokirSemuaOtomatis(auto, tombol) {
  if (!auto.length) return;
  var daftar = auto.map(function (k) { return k.asal; }).join(", ");
  if (!confirm("Blokir SEMUA " + auto.length + " kandidat otomatis sekaligus?\n\n"
      + daftar + "\n\nTiap alamat tetap diperiksa allowlist di server sebelum "
      + "benar-benar diblokir.")) return;

  var teksAsli = tombol.textContent;
  tombol.disabled = true;
  tombol.textContent = "Memblokir " + auto.length + "…";

  var berhasil = [], ditolak = [], gagal = [];

  function satu(k) {
    return kirimJson("/api/firewall/blokir", {
      ip: k.asal, device_id: (k.target_ids && k.target_ids[0]) || null,
      alasan: k.alasan, pola: k.pola
    }).then(function (r) {
      if (r && r.ditolak) ditolak.push(k.asal + ": " + (r.pesan || "IP dilindungi."));
      else if (r && r.ok === false) gagal.push(k.asal + ": " + (r.error || "tidak diketahui"));
      else berhasil.push(k.asal);
    }).catch(function (e) {
      gagal.push(k.asal + ": " + e);
    });
  }

  var rantai = Promise.resolve();
  auto.forEach(function (k) {
    rantai = rantai.then(function () { return satu(k); });
  });

  rantai.then(function () {
    var ringkas = berhasil.length + " dari " + auto.length + " berhasil diblokir";
    if (ditolak.length) ringkas += ", " + ditolak.length + " ditolak allowlist";
    if (gagal.length) ringkas += ", " + gagal.length + " gagal";
    var detail = [];
    if (ditolak.length) detail.push("Ditolak pengaman:\n" + ditolak.join("\n"));
    if (gagal.length) detail.push("Gagal:\n" + gagal.join("\n"));
    alert(ringkas + (detail.length ? "\n\n" + detail.join("\n\n") : ""));
    tombol.disabled = false;
    tombol.textContent = teksAsli;
    if (typeof muat === "function") muat();
  });
}

function gambarPenjagaan(pj, banAktif) {
  var kotak = document.getElementById("penjagaan");
  if (!kotak) return;
  kosongkan(kotak);
  if (!pj) return;

  var auto = (pj.kandidat || []).filter(function (k) { return k.aksi_saran === "blokir-otomatis"; });
  var tinjau = (pj.kandidat || []).filter(function (k) { return k.aksi_saran === "tinjau"; });

  // Spoofing warning at the top (most severe): a registered IP now points to a different MAC, so someone is impersonating a trusted host.
  (pj.spoofing || []).forEach(function (s) {
    var kartu = el("div", "kartu-spoof");
    var atas = el("div", "ks-atas");
    var ib = el("span", "ks-ikon");
    ib.appendChild(ikonEl("fingerprint"));
    atas.appendChild(ib);
    var idn = el("div", "kj-idn");
    idn.appendChild(el("div", "ks-judul",
      "Penyamaran: " + s.nama + " (" + s.ip + ")"));
    var m = el("div", "ks-mac");
    m.appendChild(el("span", "ks-mac-lab", "MAC terlihat"));
    m.appendChild(el("span", "ks-mac-bad", s.mac_terlihat));
    m.appendChild(el("span", "ks-mac-lab", "· terdaftar"));
    m.appendChild(el("span", "ks-mac-ok", (s.mac_terdaftar || []).join(", ")));
    idn.appendChild(m);
    atas.appendChild(idn);
    kartu.appendChild(atas);
    kartu.appendChild(el("div", "kj-alasan", s.alasan));
    kotak.appendChild(kartu);
  });

  var strip = el("div", "jaga-strip");
  function ubin(kelas, ikon, angka, kata) {
    var t = el("div", "jaga-ubin " + kelas);
    var ib = el("span", "ju-ikon");
    ib.appendChild(ikonEl(ikon));
    t.appendChild(ib);
    var tk = el("div");
    tk.appendChild(el("div", "ju-n", String(angka)));
    tk.appendChild(el("div", "ju-k", kata));
    t.appendChild(tk);
    return t;
  }
  strip.appendChild(ubin(auto.length ? "bahaya" : "baik", "shield-ban",
    auto.length, "akan diblokir otomatis"));
  strip.appendChild(ubin(tinjau.length ? "hati" : "baik", "eye",
    tinjau.length, "perlu ditinjau"));
  strip.appendChild(ubin("baik", "shield-check",
    (pj.dilindungi || []).length, "host dilindungi (kebal)"));
  kotak.appendChild(strip);

  function kartuKandidat(k, otomatis) {
    var kartu = el("div", "kartu-jaga " + (otomatis ? "auto" : "tinjau"));
    var atas = el("div", "kj-atas");
    var pola = POLA_JAGA[k.pola] || POLA_JAGA.kecil;
    var ib = el("span", "kj-ikon");
    ib.appendChild(ikonEl(pola.ikon));
    atas.appendChild(ib);

    var idn = el("div", "kj-idn");
    idn.appendChild(el("div", "kj-asal", k.asal));
    idn.appendChild(el("div", "kj-alasan", k.alasan));
    atas.appendChild(idn);

    var tag = el("span", "kj-tag " + (otomatis ? "auto" : "tinjau"));
    tag.appendChild(ikonEl(pola.ikon));
    tag.appendChild(document.createTextNode(" " + pola.teks));
    atas.appendChild(tag);
    kartu.appendChild(atas);

    if (k.target && k.target.length) {
      var tg = el("div", "kj-target");
      tg.appendChild(el("span", "kj-target-lab", "menyasar:"));
      k.target.forEach(function (nm) { tg.appendChild(el("span", "kj-chip", nm)); });
      kartu.appendChild(tg);
    }
    if (k.mac) {
      var mc = el("div", "kj-target");
      mc.appendChild(el("span", "kj-target-lab", "MAC:"));
      mc.appendChild(el("span", "kj-chip", k.mac));
      kartu.appendChild(mc);
    }

    var aksi = el("div", "kj-aksi");
    var lab = el("span", "kj-aksi-lab " + (otomatis ? "auto" : "tinjau"));
    lab.appendChild(ikonEl(otomatis ? "shield-ban" : "eye"));
    lab.appendChild(document.createTextNode(
      otomatis ? " Kandidat auto (auto-ban OFF)" : " Menunggu keputusan analis"));
    aksi.appendChild(lab);

    var kode = el("code", "kj-perintah", k.perintah);
    aksi.appendChild(kode);

    // Real 1-click Block button. The allowlist safeguard is on the server; if rejected or failed, `aksiBan` shows the reason.
    var btn = el("button", "kj-blokir");
    btn.type = "button";
    btn.textContent = "Blokir";
    btn.addEventListener("click", function () {
      if (!confirm("Blokir " + k.asal + " di firewall "
          + (k.target && k.target.length ? k.target.join(", ") : "device target")
          + "?\n\nAturan: sudo ufw insert 1 deny from " + k.asal)) return;
      aksiBan("/api/firewall/blokir", {
        ip: k.asal, device_id: (k.target_ids && k.target_ids[0]) || null,
        alasan: k.alasan, pola: k.pola
      }, btn);
    });
    aksi.appendChild(btn);

    // Second button, shown only if the attack targets a location guarded by the router ACL (for example Location B, whose entry point is the ACL on R2). Deliberately separate from the ufw button; both can be active at once.
    if (k.acl_router_id) {
      var btnAcl = el("button", "kj-blokir-acl");
      btnAcl.type = "button";
      btnAcl.textContent = "Blokir ACL router";
      btnAcl.title = "Sisipkan aturan deny di ACL router — menutup jalur "
        + "masuk lokasi ini, termasuk celah yang tidak tertutup blokir ufw "
        + "di device tujuan.";
      btnAcl.addEventListener("click", function () {
        if (!confirm("Blokir " + k.asal + " di ACL ROUTER (lapis kedua, "
            + "Lokasi B)?\n\nIni menyisipkan baris 'deny' di ACL router, "
            + "TERPISAH dari blokir ufw di atas. Router membuka sendiri "
            + "setelah waktunya habis.")) return;
        aksiBan("/api/firewall/blokir-acl", {
          ip: k.asal, device_id: k.acl_router_id,
          alasan: k.alasan, pola: k.pola
        }, btnAcl);
      });
      aksi.appendChild(btnAcl);
    }

    kartu.appendChild(aksi);
    return kartu;
  }

  if (auto.length) {
    var jh = el("div", "jaga-judul auto");
    jh.appendChild(ikonEl("shield-ban"));
    jh.appendChild(document.createTextNode(" Kandidat blokir otomatis — pola bermusuhan jelas"));
    // The "block all" button only makes sense with more than one candidate.
    if (auto.length > 1) {
      var btnSemua = el("button", "jaga-judul-semua");
      btnSemua.type = "button";
      btnSemua.textContent = "Blokir semua (" + auto.length + ")";
      btnSemua.addEventListener("click", function () {
        blokirSemuaOtomatis(auto, btnSemua);
      });
      jh.appendChild(btnSemua);
    }
    kotak.appendChild(jh);
    auto.forEach(function (k) { kotak.appendChild(kartuKandidat(k, true)); });
  }
  if (tinjau.length) {
    var th = el("div", "jaga-judul tinjau");
    th.appendChild(ikonEl("eye"));
    th.appendChild(document.createTextNode(" Perlu ditinjau — ragu, keputusan di analis"));
    kotak.appendChild(th);
    tinjau.forEach(function (k) { kotak.appendChild(kartuKandidat(k, false)); });
  }
  if (!auto.length && !tinjau.length) {
    var kosong = el("div", "jaga-kosong");
    kosong.appendChild(ikonEl("shield-check"));
    kosong.appendChild(el("span", null,
      "Tidak ada kandidat blokir. Semua lalu lintas yang tercatat berasal dari "
      + "host yang dilindungi atau tidak berpola bermusuhan."));
    kotak.appendChild(kosong);
  }

  if (banAktif && banAktif.length) {
    var bh = el("div", "jaga-judul", null);
    bh.appendChild(ikonEl("shield-ban"));
    bh.appendChild(document.createTextNode(" " + banAktif.length + " ban sedang berlaku"));
    kotak.appendChild(bh);
    banAktif.forEach(function (b) {
      var kartu = el("div", "kartu-ban");
      var idn = el("div", "kj-idn");
      var judul = el("div", "kj-asal");
      judul.appendChild(document.createTextNode(b.ip + " "));
      // Kind marker: one IP can have both a ufw ban and an ACL ban, each on its own card; the marker tells which "unblock" button is which.
      judul.appendChild(el("span", "kj-tag " + (b.jenis === "acl" ? "tinjau" : "auto"),
        b.jenis === "acl" ? "ACL router" : "ufw"));
      idn.appendChild(judul);
      var meta = [];
      if (b.device) meta.push("di " + b.device);
      if (b.oleh) meta.push("oleh " + b.oleh);
      if (b.kedaluwarsa) meta.push("kedaluwarsa " + waktuLengkap(b.kedaluwarsa));
      else meta.push("permanen");
      idn.appendChild(el("div", "kj-alasan",
        (b.alasan || b.pola || "") + " · " + meta.join(" · ")));
      kartu.appendChild(idn);
      var buka = el("button", "kj-buka");
      buka.type = "button";
      buka.textContent = "Buka blokir";
      buka.addEventListener("click", function () {
        if (!confirm("Buka blokir " + b.ip
            + (b.jenis === "acl" ? " (ACL router)" : " (ufw)") + "?")) return;
        // `device_id` is included so only this card's ban is closed (the same IP may have both ufw and ACL bans).
        aksiBan("/api/firewall/buka-blokir",
          { ip: b.ip, device_id: b.device_id }, buka);
      });
      kartu.appendChild(buka);
      kotak.appendChild(kartu);
    });
  }

  var det = el("details", "jaga-lindungi");
  var sum = el("summary");
  sum.appendChild(ikonEl("shield-check"));
  sum.appendChild(document.createTextNode(
    " " + (pj.dilindungi || []).length + " host dilindungi — tak pernah diban otomatis"));
  det.appendChild(sum);
  var kisi = el("div", "jl-kisi");
  (pj.dilindungi || []).forEach(function (h) {
    var c = el("div", "jl-host");
    var baris1 = el("div", "jl-baris1");
    baris1.appendChild(el("span", "jl-ip", h.ip));
    baris1.appendChild(el("span", "jl-nama", h.nama));
    c.appendChild(baris1);
    // Registered MAC: the binding that makes an IP alone insufficient for impersonation.
    if (h.mac && h.mac.length) {
      c.appendChild(el("div", "jl-mac", h.mac.join(" · ")));
    }
    kisi.appendChild(c);
  });
  det.appendChild(kisi);
  kotak.appendChild(det);

  if (pj.catatan) kotak.appendChild(el("div", "kecil redup", pj.catatan));
}

function gambarPembobolan(p) {
  var kotak = document.getElementById("pembobolan");
  if (!kotak) return;
  kosongkan(kotak);
  if (!p) return;

  if (!p.ada_pembobolan) {
    var aman = el("div", "bobol-aman");
    aman.appendChild(ikonEl("shield-check"));
    var t = el("div");
    t.appendChild(el("div", "ba-judul", "Tidak ada tanda pembobolan"));
    t.appendChild(el("div", "ba-ket",
      "Tidak ada koneksi hidup ke layanan sensitif dari alamat yang tidak "
      + "terdaftar. " + (p.catatan || "")));
    aman.appendChild(t);
    kotak.appendChild(aman);
    return;
  }

  var kepala = el("div", "bobol-kepala");
  kepala.appendChild(ikonEl("siren"));
  kepala.appendChild(el("span", null,
    p.jumlah + (p.jumlah > 1 ? " tanda pembobolan terdeteksi" : " tanda pembobolan terdeteksi")));
  kotak.appendChild(kepala);

  (p.temuan || []).forEach(function (t) {
    var kartu = el("div", "kartu-bobol");

    var atas = el("div", "kb-atas");
    var ib = el("span", "kb-ikon");
    ib.appendChild(ikonEl("shield-x"));
    atas.appendChild(ib);
    var idn = el("div");
    idn.appendChild(el("div", "kb-judul", t.judul));
    var meta = el("div", "kb-meta");
    meta.appendChild(el("span", "kb-asal", t.asal));
    meta.appendChild(el("span", null, "→ " + t.layanan + " :" + t.port));
    if (t.proses) meta.appendChild(el("span", "redup", "proses: " + t.proses));
    meta.appendChild(el("span", "redup",
      (t.potret || 1) + "× terlihat · terakhir " + waktuLengkap(t.terakhir)));
    idn.appendChild(meta);
    atas.appendChild(idn);
    kartu.appendChild(atas);

    kartu.appendChild(el("div", "kb-kenapa", t.kenapa));

    if (t.saran && t.saran.length) {
      var box = el("div", "kb-saran");
      box.appendChild(el("div", "kb-saran-judul", "Segera lakukan:"));
      var ol = el("ol");
      t.saran.forEach(function (s) {
        // Commands in backticks are marked as inline code.
        var li = el("li");
        var bagian = String(s).split("`");
        bagian.forEach(function (seg, i) {
          if (i % 2 === 1) li.appendChild(el("code", null, seg));
          else li.appendChild(document.createTextNode(seg));
        });
        ol.appendChild(li);
      });
      box.appendChild(ol);
      kartu.appendChild(box);
    }
    kotak.appendChild(kartu);
  });

  if (p.catatan) kotak.appendChild(el("div", "kecil redup", p.catatan));
}

function gambarFirewall(d) {
  gambarPetaLapis(d && d.peta_lapis);
  gambarPosturFirewall(d || {});
  gambarPembobolan(d && d.pembobolan);
  gambarPenjagaan(d && d.penjagaan, d && d.ban_aktif);
  gambarPenolakan(d && d.penolakan);
  gambarMutuAturan(d && d.temuan);

  // Two containers instead of one, so per-device cards follow the 3-layer map above. `d.device` holds both "linux" and "lokal" platforms (`report_service.firewall_semua()`), separated here by the `platform` field.
  var kotakUfw = document.getElementById("firewall-ufw");
  var kotakWinfw = document.getElementById("firewall-winfw");
  if (kotakUfw) kosongkan(kotakUfw);
  if (kotakWinfw) kosongkan(kotakWinfw);

  var daftar = (d && d.device) || [];
  var daftarUfw = daftar.filter(function (f) { return f.platform !== "lokal"; });
  var daftarWinfw = daftar.filter(function (f) { return f.platform === "lokal"; });

  if (kotakUfw && !daftarUfw.length) {
    kotakUfw.appendChild(el("div", "redup", "Tidak ada perangkat Linux yang dipantau."));
  }
  if (kotakWinfw && !daftarWinfw.length) {
    kotakWinfw.appendChild(el("div", "redup", "Laptop belum pernah terbaca."));
  }

  daftar.forEach(function (f) {
    var kotak = f.platform === "lokal" ? kotakWinfw : kotakUfw;
    if (!kotak) return;
    var kartu = el("div", "kartu-fw2 " + (f.keadaan || ""));

    var atas = el("div", "fw2-atas");
    var ib = el("span", "fw2-ikon");
    ib.appendChild(ikonEl(f.keadaan === "mati" ? "shield-x"
      : f.platform === "lokal" ? "hard-drive" : "server"));
    atas.appendChild(ib);

    var idn = el("div", null);
    idn.style.minWidth = "0";
    idn.appendChild(el("div", "fw2-nama", f.device));
    idn.appendChild(el("div", "fw2-ip", f.ip));
    atas.appendChild(idn);

    atas.appendChild(el("span", "fw2-status " + (f.keadaan || ""),
      LENCANA_FW[f.keadaan] || "?"));
    kartu.appendChild(atas);

    if (f.aktif) {
      var pol = el("div", "fw2-pol");
      var m = el("span"); m.appendChild(document.createTextNode("masuk: "));
      m.appendChild(el("b", null, f.kebijakan_masuk || "?")); pol.appendChild(m);
      var k = el("span"); k.appendChild(document.createTextNode("keluar: "));
      k.appendChild(el("b", null, f.kebijakan_keluar || "?")); pol.appendChild(k);
      if (f.logging) pol.appendChild(el("span", null, "logging: " + f.logging));
      kartu.appendChild(pol);
    }

    if (f.ringkas) kartu.appendChild(el("div", "ringkas-fw", f.ringkas));

    if ((f.aturan || []).length) {
      // MANY rules (laptop Windows Firewall has about 198) become a paginated 10-row table; FEW rules (ufw about 4) stay a compact list.
      if (f.aturan.length > 10) {
        kartu.appendChild(bungkusTabel(tabelAturanFw(f.aturan)));
      } else {
        var wadahAturan = el("div", "fw2-aturan");
        f.aturan.forEach(function (a) {
          var baris = el("div", "baris-aturan");
          baris.appendChild(el("span", "no", "#" + a.nomor));
          baris.appendChild(el("span", "ke", a.ke));
          baris.appendChild(el("span", null, a.aksi));
          var dari = el("span", "dari");
          dari.appendChild(document.createTextNode(a.dari));
          // Flagged, not colored as danger: SSH open to the whole lab network may be intended.
          if (a.terbuka_luas) {
            dari.appendChild(document.createTextNode(" "));
            dari.appendChild(el("span", "luas", "(siapa saja)"));
          }
          if (a.komentar) dari.setAttribute("data-petunjuk", a.komentar);
          baris.appendChild(dari);
          wadahAturan.appendChild(baris);
        });
        kartu.appendChild(wadahAturan);
      }
    }

    var kaki = el("div", "fw2-kaki");
    kaki.appendChild(el("span", null,
      f.waktu ? "dibaca " + waktuLengkap(f.waktu) : ""));
    // How many times the rule has changed since monitoring began.
    kaki.appendChild(el("span", null, f.riwayat
      ? f.riwayat + "x berubah sejak dipantau"
      : "belum pernah berubah sejak dipantau"));
    kartu.appendChild(kaki);

    kotak.appendChild(kartu);
  });

  gambarAclRouterRingkas(d && d.peta_lapis, d && d.acl_drift);
  gambarRiwayatFirewall((d && d.riwayat) || []);

  var mati = daftar.filter(function (f) { return f.keadaan === "mati"; }).length;
  if (window.NSMLipat && NSMLipat.ringkas) {
    NSMLipat.ringkas("firewall", mati
      ? mati + " dari " + daftar.length + " perangkat firewallnya MATI"
      : daftar.length + " perangkat, semua firewall menyala");
  }
}

/* Whether the open page contains one of these elements. Used to decide which endpoints to call; calling all of them on every page would trigger needless SSH reads in Python. */
function adaSalahSatu() {
  for (var i = 0; i < arguments.length; i++) {
    if (document.getElementById(arguments[i])) return true;
  }
  return false;
}

/* Devices whose command catalog exists. Shared by the home card and the commands page selector so the home page never promises a device the page rejects. */
function bisaDisusun(d) { return d && d.platform === "cisco_ios"; }

function muat() {
  // `peta-lapis` is the Firewall page container (formerly `firewall`); `kartu-firewall` is the summary card on the home page. The guard names both so one file serves both pages.
  if (adaSalahSatu("peta-lapis", "kartu-firewall")) {
    ambilJson("/api/firewall")
      .then(function (d) { gambarFirewall(d); ringkasFirewall(d); })
      .catch(function (e) {
        gagalKartu("kartu-firewall", "jawab-firewall", "rinci-firewall", e);
        var kotak = document.getElementById("peta-lapis");
        if (!kotak) return;
        kosongkan(kotak);
        kotak.appendChild(el("div", "redup", "Gagal memuat firewall: " + e));
      });
  }

  if (adaSalahSatu("identitas", "kartu-identitas")) {
    ambilJson("/api/identitas")
      .then(function (d) { gambarIdentitas(d); ringkasIdentitas(d); })
      .catch(function (e) {
        gagalKartu("kartu-identitas", "jawab-identitas", "rinci-identitas", e);
        var kotak = document.getElementById("identitas");
        if (!kotak) return;
        kosongkan(kotak);
        // Like compliance: a failure does not take down the rest of the page.
        kotak.appendChild(el("div", "redup", "Gagal memuat identitas: " + e));
      });
  }

  // `antrian-temuan` is the Compliance page container (formerly `kepatuhan`); `kartu-kepatuhan` is on the home page. The guard names both.
  if (adaSalahSatu("antrian-temuan", "kartu-kepatuhan")) {
    ambilJson("/api/konfig/kepatuhan")
      .then(function (d) { gambarKepatuhan(d); ringkasKepatuhan(d); })
      .catch(function (e) {
        gagalKartu("kartu-kepatuhan", "jawab-kepatuhan", "rinci-kepatuhan", e);
        var kotak = document.getElementById("antrian-temuan");
        if (!kotak) return;
        kosongkan(kotak);
        // A failure does not take down other pages' cards.
        kotak.appendChild(el("div", "redup",
          "Gagal memuat penilaian kepatuhan: " + e));
      });
  }

  // Home card "Sumber Kebenaran" (source of truth). The content pages have their own JS (sot.js); this card needs only one summary call.
  if (document.getElementById("kartu-sot")) {
    ambilJson("/api/sot")
      .then(function (daftar) {
        var total = (daftar || []).length;
        var lengkap = (daftar || []).filter(function (d) { return d.lengkap; }).length;
        if (!total) {
          nadaKartu("kartu-sot", "jawab-sot", "belum ada perangkat yang didukung", "netral");
          return;
        }
        var nada = lengkap === total ? "baik" : lengkap === 0 ? "hati" : "netral";
        nadaKartu("kartu-sot", "jawab-sot",
          lengkap + " dari " + total + " perangkat sudah lengkap intent-nya", nada);
      })
      .catch(function (e) {
        gagalKartu("kartu-sot", "jawab-sot", "rinci-sot", e);
      });
  }

  // Home card "Penyimpangan" (drift). The content page has its own JS (drift.js); one summary call is enough.
  if (document.getElementById("kartu-drift")) {
    ambilJson("/api/drift")
      .then(function (daftar) {
        var didukung = (daftar || []).filter(function (d) { return d.didukung; });
        if (!didukung.length) {
          nadaKartu("kartu-drift", "jawab-drift", "belum ada perangkat yang didukung", "netral");
          return;
        }
        // Three states, not two: devices with no declared intent are not drifted, so the card must not turn red because of them.
        var punyaIntent = didukung.filter(function (d) { return d.punya_intent; });
        var belumDiisi = didukung.length - punyaIntent.length;

        if (!punyaIntent.length) {
          nadaKartu("kartu-drift", "jawab-drift",
            "belum ada intent untuk dibandingkan (" + didukung.length
            + " perangkat siap diisi)", "netral");
          return;
        }

        var selaras = punyaIntent.filter(function (d) { return d.selaras; }).length;
        var menyimpang = punyaIntent.length - selaras;
        var teks = selaras + " dari " + punyaIntent.length + " perangkat berintent selaras";
        if (belumDiisi) teks += ", " + belumDiisi + " belum diisi";

        // Color is judged only from devices that have intent.
        var nada = menyimpang === 0 ? "baik" : "hati";
        nadaKartu("kartu-drift", "jawab-drift", teks, nada);
      })
      .catch(function (e) {
        gagalKartu("kartu-drift", "jawab-drift", "rinci-drift", e);
      });
  }

  // Home card "Pagar Otomasi" (automation guard). Reports whether any key is allowlisted, honestly showing "none yet" when empty (kill-switch default, like AUTO_BAN_AKTIF).
  if (document.getElementById("kartu-pagar")) {
    ambilJson("/api/pagar/status")
      .then(function (s) {
        var n = (s.daftar_putih || []).length;
        if (!n) {
          nadaKartu("kartu-pagar", "jawab-pagar",
            "belum ada kunci di daftar putih (mati)", "netral");
          return;
        }
        nadaKartu("kartu-pagar", "jawab-pagar",
          n + " kunci di daftar putih, jam kerja " + s.jam_mulai + "-" + s.jam_selesai, "baik");
      })
      .catch(function (e) {
        gagalKartu("kartu-pagar", "jawab-pagar", "rinci-pagar", e);
      });
  }

  // Home card "Penemuan Perangkat" (device discovery). Reports how many are WAITING FOR A DECISION, the only number needing action. Zero is neutral, not good: it can mean all decided or no scan ever done.
  if (document.getElementById("kartu-penemuan")) {
    ambilJson("/api/penemuan?status=baru")
      .then(function (d) {
        var n = (d && d.jumlah) || 0;
        if (!n) {
          nadaKartu("kartu-penemuan", "jawab-penemuan",
            "tidak ada yang menunggu keputusan", "netral");
          return;
        }
        nadaKartu("kartu-penemuan", "jawab-penemuan",
          n + (n === 1 ? " alamat" : " alamat") + " menunggu keputusan", "hati");
      })
      .catch(function (e) {
        gagalKartu("kartu-penemuan", "jawab-penemuan", "rinci-penemuan", e);
      });
  }

  // Home card "Susun perintah" has no state to report, so it only counts supported devices. On its own page `isiPilihanDevice()` uses the same list.
  if (document.getElementById("jawab-perintah")) {
    ambilJson("/api/devices")
      .then(ringkasPerintah)
      .catch(function () {
        var j = document.getElementById("jawab-perintah");
        if (j) { j.className = "jawab belum"; j.textContent = "Gagal memuat daftar perangkat"; }
      });
  }

  if (!adaSalahSatu("baris-potret", "kartu-potret")) return;

  ambilJson("/api/konfig").then(function (d) {
    gambar(d);
    ringkasPotret(d);
    var meta = document.getElementById("meta");
    if (meta) {
      meta.textContent = "Diperbarui " + new Date().toLocaleTimeString("id-ID");
    }
  }).catch(function (e) {
    var meta = document.getElementById("meta");
    if (meta) meta.textContent = "Gagal memuat";
    gagalKartu("kartu-potret", "jawab-potret", "rinci-potret", e);
    var tb = document.getElementById("baris-potret");
    if (!tb) return;
    kosongkan(tb);
    var tr = el("tr");
    var td = el("td", "redup", "Gagal memuat riwayat konfigurasi: " + e);
    td.colSpan = 6;
    tr.appendChild(td);
    tb.appendChild(tr);
  });
}

muat();
// Refreshes much less often than other pages: snapshots are added every 15 minutes.
setInterval(muat, 30000);


/* Command builder. Sends nothing to devices: it composes command text via Python and shows it. Validation is also done by Python; browser checks are only convenience, and this page shows the errors Python returns. */

/* CSRF POST helper, kept here rather than in halaman.js, which holds only helpers used by more than one page. The CSRF token is read from the Thymeleaf <meta>; without it Spring Security answers 403. */
function metaNilai(nama) {
  var m = document.querySelector('meta[name="' + nama + '"]');
  return m ? m.getAttribute("content") : "";
}

function kirimJson(url, badan) {
  var header = { "Content-Type": "application/json" };
  var namaHeader = metaNilai("_csrf_header");
  if (namaHeader) header[namaHeader] = metaNilai("_csrf");
  return ambilJson(url, {
    method: "POST", headers: header, body: JSON.stringify(badan)
  });
}

var katalogSekarang = null;

function isiPilihanDevice() {
  var sel = document.getElementById("pilih-device");
  if (!sel) return;
  ambilJson("/api/devices").then(function (devices) {
    kosongkan(sel);
    // Only devices whose platform has a catalog. Shares the filter with the home card: see `bisaDisusun()`.
    var bisa = (devices || []).filter(bisaDisusun);
    if (!bisa.length) {
      sel.appendChild(el("option", null, "tidak ada perangkat yang didukung"));
      sel.disabled = true;
      return;
    }
    bisa.forEach(function (d) {
      var o = el("option", null, d.name);
      o.value = d.id;
      sel.appendChild(o);
    });
    muatKatalog();
  }).catch(function () {
    kosongkan(sel);
    sel.appendChild(el("option", null, "gagal memuat daftar perangkat"));
  });
}

function muatKatalog() {
  var selD = document.getElementById("pilih-device");
  var selP = document.getElementById("pilih-perintah");
  if (!selD || !selD.value) return;

  ambilJson("/api/konfig/perintah/" + selD.value).then(function (d) {
    katalogSekarang = d;
    kosongkan(selP);
    (d.perintah || []).forEach(function (p) {
      var o = el("option", null, p.nama + (p.memutus ? "  (bisa memutus akses)" : ""));
      o.value = p.id;
      selP.appendChild(o);
    });
    gambarIsian();
  }).catch(function (e) {
    kosongkan(selP);
    selP.appendChild(el("option", null, "gagal memuat katalog"));
  });
}

/* Input fields are built from the parameter definitions sent by Python, so adding a command to the catalog needs no change here. */
function gambarIsian() {
  var selP = document.getElementById("pilih-perintah");
  var kotak = document.getElementById("isian-perintah");
  var ket = document.getElementById("penjelasan-perintah");
  kosongkan(kotak);
  kosongkan(ket);
  if (!katalogSekarang || !selP.value) return;

  var p = null;
  (katalogSekarang.perintah || []).forEach(function (x) {
    if (x.id === selP.value) p = x;
  });
  if (!p) return;

  ket.textContent = p.penjelasan;

  p.parameter.forEach(function (q) {
    var lab = el("label", null, q.label);
    var masuk;
    // Interface is a choice list, not free text, when NSM already knows the device's interfaces.
    if (q.jenis === "interface" && (katalogSekarang.interface || []).length) {
      masuk = el("select");
      katalogSekarang.interface.forEach(function (nama) {
        var o = el("option", null, nama);
        o.value = nama;
        masuk.appendChild(o);
      });
    } else {
      masuk = el("input");
      masuk.type = "text";
      masuk.placeholder = q.label;
    }
    masuk.dataset.param = q.nama;
    lab.appendChild(masuk);
    kotak.appendChild(lab);
  });
}

/* Current field values and the selected command id. Shared by preview AND submit so submit always sends exactly what the preview showed. */
function nilaiIsian() {
  var nilai = {};
  var isian = document.querySelectorAll("#isian-perintah [data-param]");
  Array.prototype.forEach.call(isian, function (x) {
    nilai[x.dataset.param] = x.value;
  });
  return nilai;
}

function perintahTerpilih() {
  var selP = document.getElementById("pilih-perintah");
  return selP ? selP.value : null;
}

function mintaPratinjau() {
  var selD = document.getElementById("pilih-device");
  var selP = document.getElementById("pilih-perintah");
  var hasil = document.getElementById("hasil-pratinjau");
  if (!selD.value || !selP.value) return;

  // Old errors are cleared before a new request.
  var lama = document.querySelectorAll(".galat-isian");
  Array.prototype.forEach.call(lama, function (x) { x.remove(); });

  var nilai = nilaiIsian();

  kirimJson("/api/konfig/perintah/" + selD.value + "/pratinjau",
            { perintah_id: selP.value, nilai: nilai })
    .then(function (d) { gambarPratinjau(d, nilai); })
    .catch(function (e) {
      kosongkan(hasil);
      hasil.appendChild(el("div", "peringatan-perintah", "Gagal memuat pratinjau: " + e));
    });
}

function gambarPratinjau(d, nilai) {
  var hasil = document.getElementById("hasil-pratinjau");
  kosongkan(hasil);

  if (!d.ok) {
    // Errors are attached below their own field.
    var umum = [];
    Object.keys(d.galat || {}).forEach(function (k) {
      var kolom = document.querySelector('#isian-perintah [data-param="' + k + '"]');
      if (kolom && kolom.parentNode) {
        kolom.parentNode.appendChild(el("div", "galat-isian", d.galat[k]));
      } else {
        umum.push(d.galat[k]);
      }
    });
    if (umum.length) {
      hasil.appendChild(el("div", "peringatan-perintah", umum.join(" | ")));
    }
    return;
  }

  var kotak = el("div", "kotak-pratinjau");
  kotak.appendChild(el("div", "kepala",
    "Yang akan dikirim ke " + (d.device || "-")));
  kotak.appendChild(el("pre", null, (d.baris || []).join("\n")));

  (d.peringatan || []).forEach(function (t) {
    kotak.appendChild(el("div", "peringatan-perintah", t));
  });

  // The submit button appears only here, after the preview: the only way to reach it is to see exactly which lines will be sent (a deliberate sequence instead of an "are you sure?" dialog).
  var kaki = el("div", "aksi-kirim");
  var tKirim = el("button", "tombol-bahaya", "Kirim ke perangkat");
  tKirim.type = "button";
  kaki.appendChild(tKirim);
  kaki.appendChild(el("span", "catatan-kirim",
    d.memutus
      ? "Perintah ini BISA MEMUTUS AKSES. NSM memasang reload penyelamat "
        + "lebih dulu, dan perangkat pulih sendiri kalau sambungannya hilang."
      : "NSM memasang reload penyelamat lebih dulu, lalu melepasnya setelah "
        + "perangkat terbukti masih menjawab."));
  kotak.appendChild(kaki);

  tKirim.addEventListener("click", function () {
    tKirim.disabled = true;
    tKirim.textContent = "Mengirim…";
    kirimSungguhan(d, kotak, tKirim);
  });

  hasil.appendChild(kotak);
}

/* Submit, then show the result and the two follow-up decisions. */
function kirimSungguhan(d, kotak, tKirim) {
  var selD = document.getElementById("pilih-device");
  kirimJson("/api/konfig/perintah/" + selD.value + "/kirim",
            { perintah_id: d.perintah_id || perintahTerpilih(),
              nilai: nilaiIsian(), sungguhan: true })
    .then(function (h) {
      gambarHasilKirim(h, kotak, selD.value);
    })
    .catch(function (e) {
      tKirim.disabled = false;
      tKirim.textContent = "Kirim ke perangkat";
      // Server rejected before trying anything (Ditolak from Python, 409): show the reason, as the `h.ditolak` path in gambarHasilKirim does.
      var pesan = (e && e.badan && e.badan.ditolak)
        ? "DITOLAK: " + e.badan.ditolak
        : "Gagal mengirim: " + e;
      kotak.appendChild(el("div", "hasil-gagal", pesan));
    });
}

function gambarHasilKirim(h, kotak, deviceId) {
  var lamaKaki = kotak.querySelector(".aksi-kirim");
  if (lamaKaki) lamaKaki.remove();

  // RESULT is visually distinct from WARNING, so "not sent" is not drowned among the pre-send warnings.
  if (h && h.ditolak) {
    kotak.appendChild(el("div", "hasil-gagal", "DITOLAK: " + h.ditolak));
    return;
  }

  kotak.appendChild(el("div", h.terkirim ? "hasil-baik" : "hasil-gagal",
    h.terkirim
      ? "Terkirim. Perangkat masih menjawab, dan jaring pengamannya sudah "
        + "dilepas."
      : "Tidak terkirim. " + (h.kenapa || "")));
  if (!h.terkirim) {
    // The submit button is removed above, so this row explains that retrying means building a new preview.
    kotak.appendChild(el("div", "tak-terkirim",
      "Untuk mencoba lagi, tekan Lihat Pratinjau."));
    return;
  }

  if (h.keluaran) kotak.appendChild(el("pre", "keluaran", String(h.keluaran)));

  // Two decisions with no deadline: the safety net is released once the device is proven to answer, so no timer ticks while the operator thinks (a late `reload cancel` once discarded a legitimate change).
  var pilih = el("div", "aksi-kirim");
  pilih.appendChild(el("div", "catatan-kirim",
    "Perubahannya BELUM permanen. Menyalakan ulang perangkat masih "
    + "mengembalikannya — tidak ada batas waktu untuk memutuskan."));

  var tSimpan = el("button", "tombol-bahaya", "Simpan permanen");
  tSimpan.type = "button";
  var tBatal = el("button", null, "Batalkan (reload perangkat)");
  tBatal.type = "button";
  pilih.appendChild(tSimpan);
  pilih.appendChild(tBatal);
  kotak.appendChild(pilih);

  tSimpan.addEventListener("click", function () {
    tSimpan.disabled = true; tBatal.disabled = true;
    tSimpan.textContent = "Menyimpan…";
    kirimJson("/api/konfig/perintah/" + deviceId + "/simpan", { sungguhan: true })
      .then(function (r) {
        pilih.remove();
        kotak.appendChild(el("div", r && r.ditolak ? "peringatan-perintah" : "hasil-baik",
          r && r.ditolak
            ? "DITOLAK: " + r.ditolak
            : "Tersimpan permanen. Menyalakan ulang perangkat tidak lagi "
              + "mengembalikan keadaan sebelumnya."));
        muat();
      })
      .catch(function (e) {
        tSimpan.disabled = false; tBatal.disabled = false;
        tSimpan.textContent = "Simpan permanen";
        var pesan = (e && e.badan && e.badan.ditolak)
          ? "DITOLAK: " + e.badan.ditolak
          : "Gagal menyimpan: " + e;
        kotak.appendChild(el("div", "peringatan-perintah", pesan));
      });
  });

  tBatal.addEventListener("click", function () {
    tSimpan.disabled = true; tBatal.disabled = true;
    tBatal.textContent = "Membatalkan…";
    kirimJson("/api/konfig/perintah/" + deviceId + "/putuskan",
              { tindakan: "batalkan", sungguhan: true })
      .then(function (r) {
        pilih.remove();
        kotak.appendChild(el("div", r && r.ditolak ? "peringatan-perintah" : "hasil-baik",
          r && r.ditolak
            ? "DITOLAK: " + r.ditolak
            : "Perangkat dinyalakan ulang. Ia akan kembali ke konfigurasi "
              + "yang tersimpan, dan butuh beberapa menit sebelum menjawab lagi."));
      })
      .catch(function (e) {
        tSimpan.disabled = false; tBatal.disabled = false;
        tBatal.textContent = "Batalkan (reload perangkat)";
        // Can be rejected too, for example `batalkan_sekarang` on a GNS3 node whose API recovery failed (gns3_pemulihan.GagalPulih -> Ditolak).
        var pesan = (e && e.badan && e.badan.ditolak)
          ? "DITOLAK: " + e.badan.ditolak
          : "Gagal membatalkan: " + e;
        kotak.appendChild(el("div", "peringatan-perintah", pesan));
      });
  });
}

(function pasangPenyusun() {
  var selD = document.getElementById("pilih-device");
  var selP = document.getElementById("pilih-perintah");
  var tombol = document.getElementById("tombol-pratinjau");
  if (!selD || !selP || !tombol) return;
  selD.addEventListener("change", muatKatalog);
  selP.addEventListener("change", gambarIsian);
  tombol.addEventListener("click", mintaPratinjau);
  isiPilihanDevice();
})();
