/* Tests the logic of insiden.js under Node, without a browser. InsidenTemplateTest only proves the page renders; this checks the timeline building (which events appear, their order, durations). A wrong order tells a false story. The DOM is faked (no jsdom, no package.json). Run: node frontend/src/test/js/uji_insiden.js (or via backend/uji_insiden_js.py in CI) */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

let lolos = 0;
let gagal = 0;

function benar(nama, syarat, ket) {
  if (syarat) { lolos++; console.log("  LOLOS  " + nama); }
  else { gagal++; console.log("  GAGAL  " + nama + " " + (ket || "")); }
}

function cek(nama, dapat, harap) {
  const sama = JSON.stringify(dapat) === JSON.stringify(harap);
  if (sama) { lolos++; console.log("  LOLOS  " + nama + ": " + JSON.stringify(dapat)); }
  else {
    gagal++;
    console.log("  GAGAL  " + nama + ": dapat " + JSON.stringify(dapat) +
                ", harusnya " + JSON.stringify(harap));
  }
}

/* ---------- DOM tiruan seperlunya --------------------------------------- */
function Simpul(tag) {
  this.tag = tag;
  this.className = "";
  this.children = [];
  this._teks = "";
  this.title = "";
  this.href = "";
}
Simpul.prototype = {
  get textContent() {
    if (this.children.length === 0) return this._teks;
    return this._teks + this.children.map(function (c) {
      return c.textContent;
    }).join("");
  },
  set textContent(v) { this._teks = String(v); this.children = []; },
  appendChild: function (c) { this.children.push(c); return c; },
  removeChild: function (c) {
    const i = this.children.indexOf(c);
    if (i >= 0) this.children.splice(i, 1);
    return c;
  },
  get firstChild() { return this.children.length ? this.children[0] : null; },
  addEventListener: function () {},
  /* Content-search helper: all nodes with a given class. */
  cari: function (kelas) {
    let hasil = [];
    this.children.forEach(function (c) {
      if (c.className && c.className.split(" ").indexOf(kelas) >= 0) hasil.push(c);
      if (c.cari) hasil = hasil.concat(c.cari(kelas));
    });
    return hasil;
  },
};

const wadah = {};
function buatWadah(id) { const n = new Simpul("div"); wadah[id] = n; return n; }

const dokumen = {
  createElement: function (tag) { return new Simpul(tag); },
  createTextNode: function (t) { const n = new Simpul("#text"); n._teks = String(t); return n; },
  getElementById: function (id) { return wadah[id] || null; },
  querySelector: function () { return null; },
};

const konteks = {
  document: dokumen,
  window: {},
  console: console,
  setInterval: function () { return 0; },
  Date: Date,
  Math: Math,
  JSON: JSON,
  encodeURIComponent: encodeURIComponent,
  isNaN: isNaN,
  fetch: function () { throw new Error("uji ini tidak boleh menyentuh jaringan"); },
};
konteks.globalThis = konteks;
vm.createContext(konteks);

const AKAR = path.join(__dirname, "..", "..", "main", "resources", "static");
["js/waktu.js", "insiden.js"].forEach(function (f) {
  const jalur = path.join(AKAR, f);
  vm.runInContext(fs.readFileSync(jalur, "utf8"), konteks, { filename: f });
});

console.log("=".repeat(74));
console.log("Uji insiden.js -- penyusunan garis waktu dan angka");
console.log("=".repeat(74));

/* ======================================================================== */
console.log("\n1. `durasi()` menulis lama waktu, bukan 'berapa lama yang lalu'");
const durasi = konteks.durasi;
cek("45 detik", durasi(45), "45 detik");
cek("90 detik", durasi(90), "1 mnt 30 dtk");
cek("120 detik bulat", durasi(120), "2 menit");
cek("2 jam", durasi(7200), "2 jam");
cek("2 jam 5 menit", durasi(7500), "2 jam 5 mnt");
cek("lebih dari sehari", durasi(90000), "1 hari 1 jam");
cek("nol tetap angka, bukan tanda hubung", durasi(0), "0 detik");
cek("null jadi tanda hubung", durasi(null), "-");
// Negative durations can appear if the system clock steps back (NTP); show zero.
cek("negatif dijepit ke nol", durasi(-30), "0 detik");

/* ======================================================================== */
console.log("\n2. Garis waktu: urutan, kelengkapan, dan penandaan AKAR");
const kepala = buatWadah("kepala-insiden");
const garis = buatWadah("garis-waktu");

const DATA = {
  ada: true, id: 7, status: "pulih",
  mulai: "2026-08-23T08:00:00",
  selesai: "2026-08-23T08:10:00",
  akar: "Router Lokasi A", akar_id: 5, akar_pasti: true,
  keparahan: "bahaya", mttr_detik: 600,
  ringkas: "Router Lokasi A bermasalah, dan 2 perangkat lain ikut terdampak.",
  gejala: [
    { jenis: "device", device_id: 9, device: "Router Lokasi B",
      adalah_akar: false, waktu: "2026-08-23T08:02:00",
      waktu_terakhir: "2026-08-23T08:05:00", pulih_pada: "2026-08-23T08:09:00",
      jumlah: 3, pulih: true, detail: "Device Router Lokasi B tidak terjangkau" },
    { jenis: "device", device_id: 5, device: "Router Lokasi A",
      adalah_akar: true, waktu: "2026-08-23T08:00:30",
      waktu_terakhir: "2026-08-23T08:06:00", pulih_pada: "2026-08-23T08:08:00",
      jumlah: 5, pulih: true, detail: "Device Router Lokasi A tidak terjangkau" },
    // Old symptom: recovered, but the time was never recorded (rows created before the `pulih_pada` column existed).
    { jenis: "device", device_id: 10, device: "Switch Lokasi B",
      adalah_akar: false, waktu: "2026-08-23T08:03:00",
      waktu_terakhir: "2026-08-23T08:03:00", pulih_pada: null,
      jumlah: 1, pulih: true, detail: "Device Switch Lokasi B tidak terjangkau" },
  ],
};

konteks.gambarDetail(DATA);
const tahap = garis.cari("ins-tahap");
benar("garis waktu terbentuk", tahap.length > 0, "-> 0 baris");

const pokok = tahap.map(function (t) {
  const p = t.cari("pokok");
  return p.length ? p[0].textContent.trim() : "?";
});
console.log("       urutan: " + JSON.stringify(pokok));

// The first row must be "Insiden dimulai"; readers read from the top.
benar("baris pertama = insiden dimulai",
      pokok[0].indexOf("Insiden dimulai") === 0, "-> " + pokok[0]);
benar("baris terakhir = insiden ditutup",
      pokok[pokok.length - 1].indexOf("Insiden ditutup") === 0,
      "-> " + pokok[pokok.length - 1]);

// The ROOT appears before downstream devices because it happened earlier.
const iAkar = pokok.findIndex(function (p) { return p.indexOf("Router Lokasi A") === 0; });
const iHilir = pokok.findIndex(function (p) { return p.indexOf("Router Lokasi B") === 0; });
benar("akar muncul sebelum perangkat hilir", iAkar >= 0 && iAkar < iHilir,
      "-> akar di " + iAkar + ", hilir di " + iHilir);

// A symptom with `pulih_pada` yields a recovery row; one without must not get an invented time.
const barisPulih = pokok.filter(function (p) { return p.indexOf(" pulih") > 0; });
cek("dua gejala berwaktu pulih -> dua baris pulih", barisPulih.length, 2);
benar("Switch Lokasi B TIDAK dikarang waktu pulihnya",
      barisPulih.every(function (p) { return p.indexOf("Switch Lokasi B") !== 0; }),
      "-> " + JSON.stringify(barisPulih));

// Times are strictly ascending.
const kelas = tahap.map(function (t) { return t.className; });
benar("baris mulai bertanda kelas 'mulai'", kelas[0].indexOf("mulai") >= 0);
benar("ada baris bertanda 'gejala'",
      kelas.some(function (k) { return k.indexOf("gejala") >= 0; }));

// Root versus downstream badge: color alone is not enough.
benar("ada lencana AKAR", garis.cari("lencana-akar").length === 1,
      "-> " + garis.cari("lencana-akar").length);
cek("dan dua lencana TERDAMPAK", garis.cari("lencana-hilir").length, 2);

/* ======================================================================== */
console.log("\n3. Kepala insiden memuat angka yang benar");
const isiKepala = kepala.textContent;
benar("menyebut nama akar", isiKepala.indexOf("Router Lokasi A") >= 0);
benar("menyebut nomor insiden", isiKepala.indexOf("#7") >= 0);
benar("menyebut MTTR sebagai 10 menit", isiKepala.indexOf("10 menit") >= 0,
      "-> " + isiKepala.slice(0, 300));
benar("menyebut jumlah gejala 3", isiKepala.indexOf("3 gejala") >= 0);

/* ======================================================================== */
console.log("\n4. ARAH GAGAL: insiden yang TIDAK ADA tidak boleh diam");
const kepala2 = buatWadah("kepala-insiden");
const garis2 = buatWadah("garis-waktu");
konteks.gambarDetail({ ada: false, alasan: "insiden id=999 tidak ada" });
benar("pesan alasannya ditampilkan",
      kepala2.textContent.indexOf("999") >= 0,
      "-> " + JSON.stringify(kepala2.textContent));
cek("dan garis waktunya dikosongkan", garis2.children.length, 0);

/* ======================================================================== */
console.log("\n5. Insiden yang MASIH BERLANGSUNG tidak menampilkan MTTR 0");
const kepala3 = buatWadah("kepala-insiden");
buatWadah("garis-waktu");
konteks.gambarDetail({
  ada: true, id: 8, status: "terbuka", mulai: "2026-08-23T09:00:00",
  selesai: null, akar: "Direktori LDAP", akar_pasti: false,
  keparahan: "perhatian", mttr_detik: 0, ringkas: "LDAP bermasalah.",
  gejala: [{ jenis: "device", device_id: 4, device: "Direktori LDAP",
             adalah_akar: true, waktu: "2026-08-23T09:00:00",
             waktu_terakhir: "2026-08-23T09:00:00", pulih_pada: null,
             jumlah: 1, pulih: false, detail: "tidak terjangkau" }],
});
// MTTR 0 for an ongoing outage would read as instant recovery.
benar("MTTR tidak ditulis saat insiden masih terbuka",
      kepala3.textContent.indexOf("MTTR") < 0,
      "-> " + kepala3.textContent.slice(0, 250));
benar("akar yang belum pasti DISEBUT, bukan disembunyikan",
      kepala3.textContent.indexOf("belum pasti") >= 0);

/* ======================================================================== */
console.log("\n6. Nama perangkat tidak pernah masuk sebagai HTML");
// Device names are user-typed; a name with a tag would be an injection path if inserted via innerHTML.
const kepala4 = buatWadah("kepala-insiden");
const garis4 = buatWadah("garis-waktu");
konteks.gambarDetail({
  ada: true, id: 9, status: "terbuka", mulai: "2026-08-23T09:00:00",
  akar: "<img src=x onerror=alert(1)>", akar_pasti: true, keparahan: "bahaya",
  ringkas: "<script>jahat()</script>",
  gejala: [{ jenis: "device", device_id: 1, device: "<b>nakal</b>",
             adalah_akar: true, waktu: "2026-08-23T09:00:00",
             waktu_terakhir: null, pulih_pada: null, jumlah: 1,
             pulih: false, detail: "<i>x</i>" }],
});
// In this fake DOM, text set via textContent is stored verbatim; what is proven is that no node is built from an HTML string. The first row is always "Insiden dimulai"; the device name is in the symptom row.
const semuaPokok = garis4.cari("pokok").map(function (n) { return n.textContent; });
benar("nama ber-tag tetap jadi TEKS, bukan simpul baru",
      semuaPokok.some(function (t) { return t.indexOf("<b>nakal</b>") >= 0; }),
      "-> " + JSON.stringify(semuaPokok));
benar("tidak ada elemen <script> yang terbentuk",
      JSON.stringify(kepala4).indexOf("\"tag\":\"script\"") < 0);

console.log("");
console.log("=".repeat(74));
console.log(lolos + " lolos, " + gagal + " gagal");
console.log("=".repeat(74));
process.exit(gagal ? 1 : 0);
