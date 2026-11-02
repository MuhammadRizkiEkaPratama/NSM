/* Tests the logic of wawasan.js under Node, without a browser. WawasanTemplateTest only proves the page renders; this page consists of judgments (severity color, verdict badge, card titles), and a wrong judgment produces a screen that looks fine but says something untrue. The DOM is faked (no jsdom, no package.json). Run: node frontend/src/test/js/uji_wawasan.js (or via backend/uji_wawasan_js.py in CI) */
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
  this.style = {};
  const diri = this;
  this.classList = {
    add: function (k) {
      const ada = diri.className ? diri.className.split(" ") : [];
      if (ada.indexOf(k) < 0) ada.push(k);
      diri.className = ada.join(" ").trim();
    },
    contains: function (k) {
      return diri.className.split(" ").indexOf(k) >= 0;
    },
  };
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
  setAttribute: function (k, v) { this["attr_" + k] = String(v); },
  getAttribute: function (k) {
    return Object.prototype.hasOwnProperty.call(this, "attr_" + k)
      ? this["attr_" + k] : null;
  },
  cari: function (kelas) {
    let hasil = [];
    this.children.forEach(function (c) {
      if (c.className && c.className.split(" ").indexOf(kelas) >= 0) hasil.push(c);
      if (c.cari) hasil = hasil.concat(c.cari(kelas));
    });
    return hasil;
  },
  /* Only the `.class` selector form used by this page is supported, on purpose; a fake that understood all of CSS would hide selectors that do not work in a browser. */
  querySelectorAll: function (pemilih) {
    if (pemilih.charAt(0) !== ".") {
      throw new Error("tiruan ini hanya mengerti pemilih kelas, dapat: " + pemilih);
    }
    return this.cari(pemilih.slice(1));
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
["js/waktu.js", "wawasan.js"].forEach(function (f) {
  const jalur = path.join(AKAR, f);
  vm.runInContext(fs.readFileSync(jalur, "utf8"), konteks, { filename: f });
});

console.log("=".repeat(74));
console.log("Uji wawasan.js -- penilaian, warna, dan judul");
console.log("=".repeat(74));

/* ======================================================================== */
console.log("\n1. `bps()` menulis satuan yang benar di tiap tingkat");
const bps = konteks.bps;
cek("bit/s", bps(512), "512 bit/s");
cek("kbit/s", bps(3000), "3.0 kbit/s");
cek("Mbit/s", bps(3.0e6), "3.00 Mbit/s");
cek("Gbit/s", bps(2.5e9), "2.50 Gbit/s");
cek("null jadi tanda hubung", bps(null), "-");
// Zero is a measurement, not a missing one; treating it as null would conflate "quiet link" with "unreadable link".
cek("nol tetap angka, bukan tanda hubung", bps(0), "0 bit/s");

/* ======================================================================== */
console.log("\n2. Warna simpangan memakai ambang yang SAMA dengan Python");
const kelasSigma = konteks.kelasSigma;
cek("di bawah 3 sigma aman", kelasSigma(2.9), "aman");
cek("tepat 3 sigma sudah waspada", kelasSigma(3), "waspada");
cek("tepat 6 sigma sudah parah", kelasSigma(6), "parah");
cek("null netral, bukan aman", kelasSigma(null), "netral");
// `0` deviations means exactly as usual, the safest state; it must not fall to "neutral" through a falsy check.
cek("nol simpangan tetap aman", kelasSigma(0), "aman");

/* ======================================================================== */
console.log("\n3. CACAT 11: lencana tidak boleh membantah kalimatnya");
// A row saying "trend cannot be measured yet" must not get a yellow "uncertain" badge; the color mapping must separate doubt from empty.
const lencanaVonis = konteks.lencanaVonis;
const KV = konteks.KELAS_VONIS;
cek("tidak_cukup_data itu NETRAL, bukan waspada", KV["tidak_cukup_data"], "netral");
cek("tidak_yakin memang waspada", KV["tidak_yakin"], "waspada");
cek("habis itu parah", KV["habis"], "parah");
cek("cukup itu aman", KV["cukup"], "aman");
const lc = lencanaVonis("tidak_cukup_data");
benar("garis bawah diganti spasi supaya terbaca manusia",
      lc.textContent === "tidak cukup data", "-> " + lc.textContent);
benar("dan kelasnya lencana-netral",
      lc.className.indexOf("lencana-netral") >= 0, "-> " + lc.className);
// An unknown verdict must not silently become green.
benar("vonis tak dikenal jatuh ke netral, bukan aman",
      lencanaVonis("entah_apa").className.indexOf("lencana-netral") >= 0,
      "-> " + lencanaVonis("entah_apa").className);

/* ======================================================================== */
console.log("\n4. Templat log digambar TANPA innerHTML");
// Template text comes from unauthenticated UDP syslog and may contain markup; switching to innerHTML would make the page an XSS entry point.
const gambarTemplat = konteks.gambarTemplat;
const t1 = gambarTemplat("Interface <*> changed state to <*>");
cek("teksnya utuh", t1.textContent, "Interface <*> changed state to <*>");
cek("dua penanda ganti disorot", t1.cari("ganti").length, 2);
const jahat = gambarTemplat("<img src=x onerror=alert(1)>");
cek("markup jahat jadi TEKS, bukan simpul", jahat.textContent,
    "<img src=x onerror=alert(1)>");
benar("dan tidak melahirkan elemen img",
      jahat.children.every(function (c) { return c.tag !== "img"; }));
// Looks for actual USE of innerHTML, not the word: comments that explain it is unused must not turn the test red.
const sumberJs = fs.readFileSync(path.join(AKAR, "wawasan.js"), "utf8");
const tanpaKomentar = sumberJs
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");
benar("tidak ada satu pun penugasan innerHTML di luar komentar",
      !/\.innerHTML\s*=/.test(tanpaKomentar),
      "-> " + (tanpaKomentar.match(/.*\.innerHTML\s*=.*/) || [""])[0]);
// Counterpart: the comment stripper above must really work, or the check above passes for the wrong reason.
benar("pembersih komentarnya memang membuang komentar",
      tanpaKomentar.indexOf("TIDAK PERNAH innerHTML") < 0 &&
      sumberJs.indexOf("TIDAK PERNAH innerHTML") >= 0);

/* ======================================================================== */
console.log("\n5. CACAT 10: 'POLA BARU' yang tidak berarti harus mengatakannya");
const wPolaRingkas = buatWadah("pola-ringkas");
const wPolaBaru = buatWadah("pola-baru");
const wPolaSering = buatWadah("pola-sering");

konteks.gambarPolaLog({
  tersedia: true, jam: 24,
  riwayat_muda: true, riwayat_jam: 8.3,
  catatan: "NSM baru mendengar syslog selama 8.3 jam, lebih pendek dari " +
           "jendela 24 jam di sini.",
  ringkas: {templat: 10, pesan: 918},
  baru: [{jumlah: 1, templat: "a <*>", severity_min: 3},
         {jumlah: 918, templat: "b <*>", severity_min: 6}],
  sering: [{jumlah: 918, templat: "b <*>"}],
});
const peringatan = wPolaBaru.cari("wsn-peringatan");
cek("peringatan umur riwayat muncul", peringatan.length, 1);
benar("dan menyebut umur riwayatnya",
      peringatan.length > 0 && peringatan[0].textContent.indexOf("8.3") >= 0,
      "-> " + (peringatan[0] || {}).textContent);
benar("peringatannya di ATAS daftarnya, bukan di bawah",
      wPolaBaru.children[0] === peringatan[0]);

// Counterpart: a long enough history is NOT warned about; a warning that always appears stops being read.
konteks.gambarPolaLog({
  tersedia: true, jam: 24,
  riwayat_muda: false, riwayat_jam: 240.0, catatan: null,
  ringkas: {templat: 2, pesan: 30},
  baru: [{jumlah: 1, templat: "a <*>"}],
  sering: [{jumlah: 29, templat: "b <*>"}],
});
cek("riwayat panjang -> TIDAK ada peringatan",
    wPolaBaru.cari("wsn-peringatan").length, 0);

/* ======================================================================== */
console.log("\n6. CACAT 14: kartu tidak boleh membantah penghitung di atasnya");
// A "tindakan" row with empty `tindakan` proposes nothing; titling it "Usulan tindakan" would contradict the "Tindakan diusulkan: 0" counter.
const barisUsulan = konteks.barisUsulan;

const tanpaTindakan = barisUsulan({
  jenis: "tindakan", tindakan: null, mode: "usul",
  vonis_pagar: "tidak_diminta", waktu: "2026-08-23T16:44:00",
  alasan_pagar: "semua gejala di Router Lokasi A sudah pulih",
  isi: {},
});
benar("tanpa tindakan -> judulnya 'Tidak ada tindakan diusulkan'",
      tanpaTindakan.textContent.indexOf("Tidak ada tindakan diusulkan") >= 0,
      "-> " + tanpaTindakan.textContent.slice(0, 90));
benar("dan TIDAK berjudul 'Usulan tindakan'",
      tanpaTindakan.textContent.indexOf("Usulan tindakan") < 0,
      "-> " + tanpaTindakan.textContent.slice(0, 90));

const denganTindakan = barisUsulan({
  jenis: "tindakan", tindakan: "gns3_restart", mode: "usul",
  vonis_pagar: "izin", waktu: "2026-08-23T16:44:00",
  alasan_pagar: "semua gerbang mengizinkan", isi: {},
});
benar("ada tindakan -> tetap berjudul 'Usulan tindakan'",
      denganTindakan.textContent.indexOf("Usulan tindakan") >= 0,
      "-> " + denganTindakan.textContent.slice(0, 90));
benar("dan nama runbooknya ikut tampil",
      denganTindakan.textContent.indexOf("gns3_restart") >= 0);

// Other kinds (`narasi`, `bukti`) must not be caught by that rule; they never have `tindakan`.
const narasi = barisUsulan({
  jenis: "narasi", tindakan: null, mode: "usul",
  vonis_pagar: "tidak_diminta", waktu: "2026-08-23T16:44:00",
  isi: {teks: "Router Lokasi A bermasalah sejak 08.53.", sumber: "templat"},
});
benar("baris narasi tetap berjudul 'Narasi'",
      narasi.textContent.indexOf("Narasi") >= 0,
      "-> " + narasi.textContent.slice(0, 90));
benar("dan tidak ikut berjudul 'Tidak ada tindakan diusulkan'",
      narasi.textContent.indexOf("Tidak ada tindakan diusulkan") < 0);

/* ======================================================================== */
console.log("\n7. Usulan yang DITOLAK pagar tampil lengkap dengan alasannya");
// Refused proposals must be shown, so people learn something could be done but is not allowed.
const ditolak = barisUsulan({
  jenis: "tindakan", tindakan: "gns3_restart", mode: "usul",
  vonis_pagar: "tolak", waktu: "2026-08-23T16:44:00",
  alasan_pagar: "jatah tindakan per jam sudah habis", isi: {},
});
benar("alasan penolakan ikut tampil",
      ditolak.textContent.indexOf("jatah tindakan per jam sudah habis") >= 0,
      "-> " + ditolak.textContent.slice(0, 120));
benar("dan barisnya diberi kelas waspada",
      ditolak.className.indexOf("waspada") >= 0, "-> " + ditolak.className);
benar("lencananya berbunyi MENOLAK, bukan sekadar 'tolak'",
      ditolak.textContent.indexOf("pagar MENOLAK") >= 0);

console.log();
console.log("=".repeat(74));
console.log(lolos + " lolos, " + gagal + " gagal");
console.log("=".repeat(74));
process.exit(gagal ? 1 : 0);
