/*
 * Source of truth pages (docs/design/CLOSED-LOOP-AUTOMATION.md): the list (`konfig_sot.html`, `#tabel-sot`) and per-device detail (`konfig_sot_device.html`, `#form-nilai`) share this file; each renderer first checks its page elements exist.
 * Touches no devices: only `/api/sot/**`, which reads and writes NSM's own database.
 * Validation is done by Python (`sot/katalog.py`); the form is built from the same catalog so the fields cannot drift from what the server accepts.
 * All elements are built with the DOM API, not innerHTML.
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
    method: "POST", headers: header, body: JSON.stringify(badan)
  });
}

/* Message rejected by Python (409, `{"ok": false, "ditolak": "..."}`) or a generic message. `ambilJson` puts the JSON error body in `e.badan`. */
function pesanGalat(e) {
  if (e && e.badan && e.badan.ditolak) return e.badan.ditolak;
  return e && e.message ? e.message : String(e);
}

function tampilPesan(idWadah, teks, jenis) {
  var w = document.getElementById(idWadah);
  if (!w) return;
  kosongkan(w);
  if (!teks) return;
  w.appendChild(el("div", jenis === "galat" ? "pesan-galat" : "pesan-sukses", teks));
}


/* ===========================================================================
 * HALAMAN DAFTAR (`konfig_sot.html`)
 * =========================================================================== */

function gambarDaftarSot(daftar) {
  var tb = document.getElementById("baris-sot");
  if (!tb) return;
  kosongkan(tb);
  if (!daftar || !daftar.length) {
    var trKosong = el("tr");
    var tdKosong = el("td", "redup",
      "Belum ada perangkat yang platformnya punya katalog Sumber Kebenaran.");
    tdKosong.colSpan = 4;
    trKosong.appendChild(tdKosong);
    tb.appendChild(trKosong);
    return;
  }
  daftar.forEach(function (d) {
    var tr = el("tr");
    tr.appendChild(el("td", null, d.device));
    tr.appendChild(el("td", "mono", d.platform));

    var tdLengkap = el("td");
    var lencana = el("span",
      "lencana " + (d.lengkap ? "lencana-up" : "lencana-menunggu"),
      d.lengkap ? "Lengkap" : (d.kunci_terisi + " / " + d.kunci_total + " kunci"));
    tdLengkap.appendChild(lencana);
    tr.appendChild(tdLengkap);

    var tdTaut = el("td");
    var a = el("a", null, d.lengkap ? "Lihat / render" : "Lengkapi");
    a.href = "/admin/konfig/sot/" + d.device_id;
    tdTaut.appendChild(a);
    tr.appendChild(tdTaut);

    tb.appendChild(tr);
  });
}


/* ===========================================================================
 * HALAMAN DETAIL (`konfig_sot_device.html`)
 * =========================================================================== */

var DEVICE_ID = null;
var KATALOG_KUNCI = [];

/* One form field, built from the catalog SPEC rather than hand-written per key; new keys in `sot/katalog.py` appear automatically. */
function medanNilai(spec, nilaiSekarang) {
  var wadah = el("div", "medan-intent");
  var label = el("label", null, spec.judul + (spec.wajib ? " *" : ""));
  label.htmlFor = "nilai-" + spec.kunci;
  wadah.appendChild(label);

  var input;
  if (spec.bentuk === "pilihan") {
    input = document.createElement("select");
    input.appendChild(el("option", null, "belum dinyatakan")).value = "";
    (spec.pilihan || []).forEach(function (p) {
      var o = el("option", null, p);
      o.value = p;
      if (nilaiSekarang === p) o.selected = true;
      input.appendChild(o);
    });
  } else if (spec.bentuk === "bool") {
    input = document.createElement("select");
    [["", "belum dinyatakan"], ["ya", "Ya"], ["tidak", "Tidak"]].forEach(function (pair) {
      var o = el("option", null, pair[1]);
      o.value = pair[0];
      if ((nilaiSekarang === true && pair[0] === "ya")
          || (nilaiSekarang === false && pair[0] === "tidak")) o.selected = true;
      input.appendChild(o);
    });
  } else {
    input = document.createElement("input");
    input.type = spec.bentuk === "angka" ? "number" : "text";
    if (spec.bentuk === "angka") {
      if (spec.min !== undefined) input.min = spec.min;
      if (spec.maks_nilai !== undefined) input.max = spec.maks_nilai;
    }
    if (spec.bentuk === "daftar_ip" || spec.bentuk === "daftar_teks") {
      input.placeholder = "pisahkan dengan koma, contoh: " + (spec.contoh || "");
      input.value = Array.isArray(nilaiSekarang) ? nilaiSekarang.join(", ") : "";
    } else {
      input.placeholder = spec.contoh || "";
      input.value = nilaiSekarang !== undefined && nilaiSekarang !== null
        ? String(nilaiSekarang) : "";
    }
  }
  input.id = "nilai-" + spec.kunci;
  input.name = spec.kunci;
  input.setAttribute("data-bentuk", spec.bentuk);
  wadah.appendChild(input);

  if (spec.kenapa) {
    wadah.appendChild(el("div", "medan-kenapa", spec.kenapa));
  }
  return wadah;
}

function gambarFormNilai(katalog, nilai) {
  var wadah = document.getElementById("medan-nilai");
  if (!wadah) return;
  kosongkan(wadah);
  KATALOG_KUNCI = katalog || [];
  KATALOG_KUNCI.forEach(function (spec) {
    wadah.appendChild(medanNilai(spec, nilai ? nilai[spec.kunci] : undefined));
  });
}

/* Collect the form into {key: value}. Empty fields are not sent: "not declared" means absent, not an empty value the validator would reject. */
function kumpulkanNilai() {
  var hasil = {};
  KATALOG_KUNCI.forEach(function (spec) {
    var input = document.getElementById("nilai-" + spec.kunci);
    if (!input) return;
    var v = input.value;
    if (v === "" || v === null) return;
    hasil[spec.kunci] = v;
  });
  return hasil;
}

function gambarStatusLengkap(a) {
  var w = document.getElementById("status-lengkap");
  if (!w) return;
  if (a.lengkap) {
    w.style.display = "none";
    return;
  }
  w.style.display = "";
  kosongkan(w);
  w.appendChild(document.createTextNode(
    "Belum lengkap untuk dirender -- " + a.kurang.length + " kunci wajib masih kosong: "
    + a.kurang.map(function (k) { return k.judul; }).join(", ") + "."));
}

/* interface / vlan / route: dynamic rows, "reconcile the whole list" */

function barisInterface(data) {
  data = data || {};
  var tr = el("tr");
  var kolom = [
    ["nama", "text", data.nama || ""],
    ["deskripsi", "text", data.deskripsi || ""],
    ["ip", "text", data.ip || ""],
    ["mask", "text", data.mask || ""],
    ["vlan", "number", data.vlan != null ? data.vlan : ""],
  ];
  kolom.forEach(function (k) {
    var td = el("td");
    var inp = document.createElement("input");
    inp.type = k[1];
    inp.value = k[2];
    inp.setAttribute("data-kol", k[0]);
    inp.style.width = "100%";
    td.appendChild(inp);
    tr.appendChild(td);
  });
  var tdShutdown = el("td");
  var cek = document.createElement("input");
  cek.type = "checkbox";
  cek.setAttribute("data-kol", "shutdown");
  cek.checked = !!data.shutdown;
  tdShutdown.appendChild(cek);
  tr.appendChild(tdShutdown);
  tr.appendChild(tombolHapusBaris());
  return tr;
}

function barisVlan(data) {
  data = data || {};
  var tr = el("tr");
  var tdId = el("td");
  var inpId = document.createElement("input");
  inpId.type = "number"; inpId.min = 1; inpId.max = 4094;
  inpId.value = data.vlan_id != null ? data.vlan_id : "";
  inpId.setAttribute("data-kol", "vlan_id");
  inpId.style.width = "100%";
  tdId.appendChild(inpId);
  tr.appendChild(tdId);

  var tdNama = el("td");
  var inpNama = document.createElement("input");
  inpNama.type = "text";
  inpNama.value = data.nama || "";
  inpNama.setAttribute("data-kol", "nama");
  inpNama.style.width = "100%";
  tdNama.appendChild(inpNama);
  tr.appendChild(tdNama);

  tr.appendChild(tombolHapusBaris());
  return tr;
}

function barisRute(data) {
  data = data || {};
  var tr = el("tr");
  [["tujuan", data.tujuan], ["mask", data.mask], ["next_hop", data.next_hop],
   ["catatan", data.catatan]].forEach(function (pair) {
    var td = el("td");
    var inp = document.createElement("input");
    inp.type = "text";
    inp.value = pair[1] || "";
    inp.setAttribute("data-kol", pair[0]);
    inp.style.width = "100%";
    td.appendChild(inp);
    tr.appendChild(td);
  });
  tr.appendChild(tombolHapusBaris());
  return tr;
}

function tombolHapusBaris() {
  var td = el("td");
  var b = document.createElement("button");
  b.type = "button";
  b.className = "tombol";
  b.textContent = "×";
  b.title = "Hapus baris ini";
  b.addEventListener("click", function () { td.closest("tr").remove(); });
  td.appendChild(b);
  return td;
}

/* Read all table rows into an array of objects. Rows with every field empty are skipped. */
function bacaBaris(idTbody) {
  var tb = document.getElementById(idTbody);
  if (!tb) return [];
  var hasil = [];
  Array.prototype.forEach.call(tb.querySelectorAll("tr"), function (tr) {
    var obj = {};
    var adaIsi = false;
    Array.prototype.forEach.call(tr.querySelectorAll("[data-kol]"), function (inp) {
      var kol = inp.getAttribute("data-kol");
      if (inp.type === "checkbox") {
        obj[kol] = inp.checked;
        if (inp.checked) adaIsi = true;
      } else {
        obj[kol] = inp.value;
        if (inp.value !== "") adaIsi = true;
      }
    });
    if (adaIsi) hasil.push(obj);
  });
  return hasil;
}


/* ===========================================================================
 * RENDER (pratinjau konfigurasi intended)
 * =========================================================================== */

function gambarHasilRender(hasil) {
  var w = document.getElementById("hasil-render");
  if (!w) return;
  kosongkan(w);
  var kotak = el("div", "kotak-pratinjau");
  var meta = el("div", "kecil redup",
    hasil.baris + " baris · sidik " + hasil.sidik.slice(0, 16) + "…");
  kotak.appendChild(meta);
  var pre = document.createElement("pre");
  pre.textContent = hasil.teks;
  kotak.appendChild(pre);
  w.appendChild(kotak);
}


/* ===========================================================================
 * RIWAYAT
 * =========================================================================== */

function gambarRiwayat(daftar) {
  var tb = document.getElementById("baris-riwayat");
  if (!tb) return;
  kosongkan(tb);
  if (!daftar || !daftar.length) {
    var tr0 = el("tr");
    var td0 = el("td", "redup", "Belum ada perubahan tercatat.");
    td0.colSpan = 6;
    tr0.appendChild(td0);
    tb.appendChild(tr0);
    return;
  }
  daftar.forEach(function (r) {
    var tr = el("tr");
    tr.appendChild(el("td", null, r.waktu ? waktuLengkap(r.waktu) : "-"));
    tr.appendChild(el("td", null, r.kategori));
    tr.appendChild(el("td", "mono", r.kunci || "-"));
    tr.appendChild(el("td", null, r.aksi));
    var perubahan = (r.lama !== null && r.lama !== undefined
        ? JSON.stringify(r.lama) : "—")
      + " → "
      + (r.baru !== null && r.baru !== undefined ? JSON.stringify(r.baru) : "—");
    tr.appendChild(el("td", "mono kecil", perubahan));
    tr.appendChild(el("td", null, r.oleh || "-"));
    tb.appendChild(tr);
  });
}


/* ===========================================================================
 * MUAT
 * =========================================================================== */

function muatDaftarSot() {
  ambilJson("/api/sot")
    .then(gambarDaftarSot)
    .catch(function (e) {
      var tb = document.getElementById("baris-sot");
      if (!tb) return;
      kosongkan(tb);
      var tr = el("tr");
      var td = el("td", "redup", "Gagal memuat: " + pesanGalat(e));
      td.colSpan = 4;
      tr.appendChild(td);
      tb.appendChild(tr);
    });
}

function muatDetailSot() {
  ambilJson("/api/sot/" + DEVICE_ID)
    .then(function (a) {
      var judul = document.getElementById("judul-device");
      if (judul) judul.textContent = a.device + " (" + a.platform + ")";
      document.title = "Sumber Kebenaran: " + a.device + " - NSM";

      gambarStatusLengkap(a);
      gambarFormNilai(a.katalog, a.nilai);

      var tbIface = document.getElementById("baris-interface");
      if (tbIface) {
        kosongkan(tbIface);
        (a.interface || []).forEach(function (i) { tbIface.appendChild(barisInterface(i)); });
      }
      var tbVlan = document.getElementById("baris-vlan");
      if (tbVlan) {
        kosongkan(tbVlan);
        (a.vlan || []).forEach(function (v) { tbVlan.appendChild(barisVlan(v)); });
      }
      var tbRute = document.getElementById("baris-rute");
      if (tbRute) {
        kosongkan(tbRute);
        (a.rute || []).forEach(function (r) { tbRute.appendChild(barisRute(r)); });
      }
    })
    .catch(function (e) {
      var judul = document.getElementById("judul-device");
      if (judul) judul.textContent = "Gagal memuat: " + pesanGalat(e);
    });

  ambilJson("/api/sot/" + DEVICE_ID + "/riwayat")
    .then(gambarRiwayat)
    .catch(function () { gambarRiwayat([]); });
}

function pasangPengendaliDetail() {
  var formNilai = document.getElementById("form-nilai");
  if (formNilai) {
    formNilai.addEventListener("submit", function (ev) {
      ev.preventDefault();
      kirimJson("/api/sot/" + DEVICE_ID + "/nilai", { nilai: kumpulkanNilai() })
        .then(function (r) {
          tampilPesan("pesan-nilai", r.berubah + " kunci disimpan.", "sukses");
          muatDetailSot();
        })
        .catch(function (e) { tampilPesan("pesan-nilai", pesanGalat(e), "galat"); });
    });
  }

  var tambahIface = document.getElementById("tambah-interface");
  if (tambahIface) {
    tambahIface.addEventListener("click", function () {
      document.getElementById("baris-interface").appendChild(barisInterface());
    });
  }
  var simpanIface = document.getElementById("simpan-interface");
  if (simpanIface) {
    simpanIface.addEventListener("click", function () {
      kirimJson("/api/sot/" + DEVICE_ID + "/interface",
               { interface: bacaBaris("baris-interface") })
        .then(function (r) {
          tampilPesan("pesan-interface", r.berubah + " interface berubah.", "sukses");
          muatDetailSot();
        })
        .catch(function (e) { tampilPesan("pesan-interface", pesanGalat(e), "galat"); });
    });
  }

  var tambahVlan = document.getElementById("tambah-vlan");
  if (tambahVlan) {
    tambahVlan.addEventListener("click", function () {
      document.getElementById("baris-vlan").appendChild(barisVlan());
    });
  }
  var simpanVlan = document.getElementById("simpan-vlan");
  if (simpanVlan) {
    simpanVlan.addEventListener("click", function () {
      kirimJson("/api/sot/" + DEVICE_ID + "/vlan", { vlan: bacaBaris("baris-vlan") })
        .then(function (r) {
          tampilPesan("pesan-vlan", r.berubah + " VLAN berubah.", "sukses");
          muatDetailSot();
        })
        .catch(function (e) { tampilPesan("pesan-vlan", pesanGalat(e), "galat"); });
    });
  }

  var tambahRute = document.getElementById("tambah-rute");
  if (tambahRute) {
    tambahRute.addEventListener("click", function () {
      document.getElementById("baris-rute").appendChild(barisRute());
    });
  }
  var simpanRute = document.getElementById("simpan-rute");
  if (simpanRute) {
    simpanRute.addEventListener("click", function () {
      kirimJson("/api/sot/" + DEVICE_ID + "/rute", { rute: bacaBaris("baris-rute") })
        .then(function (r) {
          tampilPesan("pesan-rute", r.berubah + " rute berubah.", "sukses");
          muatDetailSot();
        })
        .catch(function (e) { tampilPesan("pesan-rute", pesanGalat(e), "galat"); });
    });
  }

  var tombolRender = document.getElementById("tombol-render");
  if (tombolRender) {
    tombolRender.addEventListener("click", function () {
      var w = document.getElementById("hasil-render");
      if (w) { kosongkan(w); w.appendChild(el("div", "redup", "Merender…")); }
      ambilJson("/api/sot/" + DEVICE_ID + "/render")
        .then(gambarHasilRender)
        .catch(function (e) {
          if (w) { kosongkan(w); w.appendChild(el("div", "pesan-galat", pesanGalat(e))); }
        });
    });
  }
}


if (document.getElementById("tabel-sot")) {
  muatDaftarSot();
}

if (document.getElementById("form-nilai")) {
  DEVICE_ID = metaNilai("_sot_device_id");
  pasangPengendaliDetail();
  muatDetailSot();
}
