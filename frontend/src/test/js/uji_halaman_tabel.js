/* Tests `static/js/halaman-tabel.js` (client-side table pagination). Regression: the Traffic page has four sibling tables under one `div.tab-panel`, and `pasang()` found the first pager control of the parent, so one control served all four tables. No dependencies (no jsdom); the small DOM shim really parses `innerHTML`. Run: node frontend/src/test/js/uji_halaman_tabel.js */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

let lolos = 0, gagal = 0;

function benar(nama, syarat, ket) {
  if (syarat) { lolos++; console.log("  LOLOS  " + nama); }
  else { gagal++; console.log("  GAGAL  " + nama + (ket ? "  " + ket : "")); }
}
function sama(nama, dapat, harap) {
  benar(nama, dapat === harap, "-> dapat " + JSON.stringify(dapat)
        + ", harusnya " + JSON.stringify(harap));
}

/* ------------------------------------------------------------------ */
/* Minimal DOM shim, only what halaman-tabel.js uses. */
/* ------------------------------------------------------------------ */

class Elemen {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this._kelas = new Set();
    this._attr = {};
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.onclick = null;
    this.id = "";
    const self = this;
    this.classList = {
      add: (c) => self._kelas.add(c),
      remove: (c) => self._kelas.delete(c),
      contains: (c) => self._kelas.has(c),
    };
  }
  get className() { return Array.from(this._kelas).join(" "); }
  set className(v) {
    this._kelas = new Set(String(v).split(/\s+/).filter(Boolean));
  }
  setAttribute(k, v) { this._attr[k] = String(v); }
  getAttribute(k) { return k in this._attr ? this._attr[k] : null; }
  hasAttribute(k) { return k in this._attr; }

  appendChild(anak) {
    anak.parentNode = this;
    this.children.push(anak);
    return anak;
  }
  insertBefore(baru, acuan) {
    baru.parentNode = this;
    const i = acuan ? this.children.indexOf(acuan) : -1;
    if (i < 0) this.children.push(baru);
    else this.children.splice(i, 0, baru);
    return baru;
  }
  remove() {
    if (!this.parentNode) return;
    const i = this.parentNode.children.indexOf(this);
    if (i >= 0) this.parentNode.children.splice(i, 1);
    this.parentNode = null;
  }
  get nextElementSibling() {
    if (!this.parentNode) return null;
    const s = this.parentNode.children;
    const i = s.indexOf(this);
    return (i >= 0 && i + 1 < s.length) ? s[i + 1] : null;
  }
  get nextSibling() { return this.nextElementSibling; }

  // Table: `tBodies[0].rows`, used by ambilItem().
  get tBodies() { return this.children.filter((c) => c.tagName === "TBODY"); }
  get rows() { return this.children.filter((c) => c.tagName === "TR"); }

  _semuaKeturunan(keluar) {
    for (const a of this.children) { keluar.push(a); a._semuaKeturunan(keluar); }
    return keluar;
  }
  _cocok(sel) {
    if (sel.startsWith(".")) return this._kelas.has(sel.slice(1));
    const m = /^([a-z]+)\[([a-z-]+)\]$/i.exec(sel);
    if (m) return this.tagName === m[1].toUpperCase() && this.hasAttribute(m[2]);
    return this.tagName === sel.toUpperCase();
  }
  querySelector(sel) {
    const scope = /^:scope\s*>\s*(.+)$/.exec(sel);
    if (scope) return this.children.find((a) => a._cocok(scope[1])) || null;
    return this._semuaKeturunan([]).find((a) => a._cocok(sel)) || null;
  }
  querySelectorAll(sel) {
    return this._semuaKeturunan([]).filter((a) => a._cocok(sel));
  }

  // A small but real `innerHTML` parser (nested tags, quoted attributes, text), not shape matching, so a broken `buatKontrol()` cannot slip through.
  set innerHTML(html) {
    this.children = [];
    const tumpukan = [this];
    const pola = /<\/?([a-z]+)((?:\s+[a-z-]+="[^"]*")*)\s*>|([^<]+)/gi;
    let m;
    while ((m = pola.exec(html)) !== null) {
      const [utuh, tag, attr, teks] = m;
      const induk = tumpukan[tumpukan.length - 1];
      if (teks !== undefined) {
        if (teks.trim()) induk.textContent += teks;
        continue;
      }
      if (utuh.startsWith("</")) { tumpukan.pop(); continue; }
      const e = new Elemen(tag);
      const pa = /([a-z-]+)="([^"]*)"/gi;
      let a;
      while ((a = pa.exec(attr || "")) !== null) {
        if (a[1] === "class") e.className = a[2];
        else e.setAttribute(a[1], a[2]);
      }
      induk.appendChild(e);
      tumpukan.push(e);
    }
  }
}

function buatDokumen() {
  const doc = new Elemen("document");
  doc.readyState = "complete";
  doc.createElement = (t) => new Elemen(t);
  doc.addEventListener = () => {};
  return doc;
}

/* Builds a `div.tab-panel` with several sibling tables, the same shape as the real Traffic page where the bug appeared. `jumlahBaris` sets the rows per table. */
function buatPanel(doc, spek) {
  const panel = doc.createElement("div");
  panel.className = "tab-panel";
  doc.appendChild(panel);
  const tabel = {};
  for (const s of spek) {
    const t = doc.createElement("table");
    t.setAttribute("data-hal", String(s.perHal));
    const tb = doc.createElement("tbody");
    for (let i = 0; i < s.baris; i++) {
      const tr = doc.createElement("tr");
      tr.id = s.nama + "-" + i;
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    panel.appendChild(t);
    tabel[s.nama] = t;
  }
  return { panel, tabel };
}

function muatModul(doc) {
  const jalur = path.join(__dirname, "..", "..", "main", "resources",
                          "static", "js", "halaman-tabel.js");
  const kode = fs.readFileSync(jalur, "utf8");
  const win = {};
  const konteks = vm.createContext({
    window: win, document: doc, location: { hash: "" }, console,
  });
  vm.runInContext(kode, konteks);
  return win.halamanTabel;
}

function kontrolMilik(tabel) {
  const n = tabel.nextElementSibling;
  return (n && n.classList.contains("hal-tabel")) ? n : null;
}
function terlihat(tabel) {
  return tabel.tBodies[0].rows.filter((r) => !r.hidden).length;
}

/* ------------------------------------------------------------------ */
console.log("=".repeat(74));
console.log("UJI PAGINASI TABEL (halaman-tabel.js)");
console.log("=".repeat(74));

console.log("\n0. Shim DOM-nya sendiri benar (kalau ini gagal, sisa uji tak berarti)");
{
  const doc = buatDokumen();
  const d = doc.createElement("div");
  d.innerHTML = '<span class="a"></span><span class="b">'
              + '<button type="button" class="c">Halo</button></span>';
  sama("dua anak langsung ter-parse", d.children.length, 2);
  benar("anak bersarang ter-parse", d.querySelector(".c") !== null);
  sama("teks di dalam tag ter-parse", d.querySelector(".c").textContent, "Halo");
  sama("atribut non-class ter-parse",
       d.querySelector(".c").getAttribute("type"), "button");
}

console.log("\n1. EMPAT TABEL BERSAUDARA -> EMPAT KONTROL TERPISAH");
console.log("   (bentuk persis halaman Lalu Lintas: Per Pengguna, Per Berkas,");
console.log("    Aktivitas Berkas, Riwayat Perintah dalam satu div yang sama)");
{
  const doc = buatDokumen();
  const { tabel } = buatPanel(doc, [
    { nama: "orang",    perHal: 5, baris: 6 },
    { nama: "berkas",   perHal: 5, baris: 15 },
    { nama: "aktivitas", perHal: 8, baris: 26 },
    { nama: "perintah", perHal: 9, baris: 30 },
  ]);
  muatModul(doc).terapkan(doc);

  benar("Per Pengguna punya kontrolnya SENDIRI", kontrolMilik(tabel.orang) !== null);
  benar("Per Berkas punya kontrolnya SENDIRI", kontrolMilik(tabel.berkas) !== null);
  benar("Aktivitas Berkas punya kontrolnya SENDIRI",
        kontrolMilik(tabel.aktivitas) !== null);
  benar("Riwayat Perintah punya kontrolnya SENDIRI",
        kontrolMilik(tabel.perintah) !== null);

  const semua = doc.querySelectorAll(".hal-tabel");
  sama("TEPAT empat kontrol di seluruh panel (dulu cuma satu)", semua.length, 4);
}

console.log("\n2. TIAP KONTROL MENYEBUT ANGKA TABELNYA SENDIRI");
console.log("   (dulu semua kontrol menampilkan angka tabel yang diproses");
console.log("    TERAKHIR -- '1-9 dari 30' muncul di bawah Per Berkas yang");
console.log("    isinya cuma 15 baris)");
{
  const doc = buatDokumen();
  const { tabel } = buatPanel(doc, [
    { nama: "berkas",   perHal: 5, baris: 15 },
    { nama: "aktivitas", perHal: 8, baris: 26 },
    { nama: "perintah", perHal: 9, baris: 30 },
  ]);
  muatModul(doc).terapkan(doc);

  const info = (t) => kontrolMilik(t).querySelector(".hal-info").textContent;
  sama("Per Berkas: 1-5 dari 15", info(tabel.berkas), "1–5 dari 15");
  sama("Aktivitas Berkas: 1-8 dari 26", info(tabel.aktivitas), "1–8 dari 26");
  sama("Riwayat Perintah: 1-9 dari 30", info(tabel.perintah), "1–9 dari 30");
}

console.log("\n3. 'Berikutnya' MENGGERAKKAN TABELNYA SENDIRI, BUKAN TETANGGANYA");
console.log("   (inti keluhan pengguna: satu tombol mewakili semua section)");
{
  const doc = buatDokumen();
  const { tabel } = buatPanel(doc, [
    { nama: "berkas",   perHal: 5, baris: 15 },
    { nama: "aktivitas", perHal: 8, baris: 26 },
  ]);
  muatModul(doc).terapkan(doc);

  const majuAktivitas = kontrolMilik(tabel.aktivitas).querySelector(".hal-maju");
  majuAktivitas.onclick();

  const infoAkt = kontrolMilik(tabel.aktivitas).querySelector(".hal-info");
  const infoBrk = kontrolMilik(tabel.berkas).querySelector(".hal-info");
  sama("Aktivitas Berkas maju ke halaman 2", infoAkt.textContent, "9–16 dari 26");
  sama("Per Berkas TIDAK ikut berpindah", infoBrk.textContent, "1–5 dari 15");

  // The row itself, not just its text.
  const terlihatAkt = tabel.aktivitas.tBodies[0].rows
    .map((r, i) => (!r.hidden ? i : -1)).filter((i) => i >= 0);
  sama("baris 9-16 yang terlihat (indeks 8..15)", terlihatAkt.join(","),
       "8,9,10,11,12,13,14,15");
}

console.log("\n4. SELURUH BARIS BISA DICAPAI (tidak ada yang terkubur)");
console.log("   (26 baris ada di DOM tapi cuma 8 pernah terlihat -- itu");
console.log("    persis 'mana riwayat semua aktivitas berkas tersebut')");
{
  const doc = buatDokumen();
  const { tabel } = buatPanel(doc, [
    { nama: "berkas",   perHal: 5, baris: 15 },
    { nama: "aktivitas", perHal: 8, baris: 26 },
  ]);
  muatModul(doc).terapkan(doc);

  const kontrol = kontrolMilik(tabel.aktivitas);
  const maju = kontrol.querySelector(".hal-maju");
  const pernah = new Set();
  for (let putaran = 0; putaran < 20; putaran++) {
    tabel.aktivitas.tBodies[0].rows.forEach((r, i) => {
      if (!r.hidden) pernah.add(i);
    });
    if (maju.disabled) break;
    maju.onclick();
  }
  sama("SEMUA 26 baris pernah terlihat lewat tombol Berikutnya",
       pernah.size, 26);
  benar("tombol Berikutnya mati di halaman terakhir", maju.disabled === true);
}

console.log("\n5. TABEL YANG MENGECIL TIDAK MENGHAPUS KONTROL TABEL LAIN");
console.log("   (cabang `lama.remove()`: dulu tabel pendek menghapus kontrol");
console.log("    milik tetangganya yang masih membutuhkannya)");
{
  const doc = buatDokumen();
  const { tabel } = buatPanel(doc, [
    { nama: "pendek", perHal: 5, baris: 2 }, // below the threshold, no control needed
    { nama: "panjang", perHal: 5, baris: 20 },
  ]);
  const modul = muatModul(doc);
  modul.terapkan(doc);

  benar("tabel pendek TIDAK dapat kontrol", kontrolMilik(tabel.pendek) === null);
  benar("tabel panjang TETAP punya kontrol",
        kontrolMilik(tabel.panjang) !== null);

  // Called again: the page calls terapkan() repeatedly as data arrives from several endpoints.
  modul.terapkan(doc);
  modul.terapkan(doc);
  benar("dipanggil berulang: kontrol tabel panjang tetap ada",
        kontrolMilik(tabel.panjang) !== null);
  sama("dan tidak digandakan", doc.querySelectorAll(".hal-tabel").length, 1);
}

console.log("\n6. BARIS SEMUANYA TERLIHAT LAGI KALAU TABEL TURUN DI BAWAH AMBANG");
{
  const doc = buatDokumen();
  const { tabel } = buatPanel(doc, [{ nama: "t", perHal: 5, baris: 12 }]);
  const modul = muatModul(doc);
  modul.terapkan(doc);
  sama("mula-mula 5 yang terlihat", terlihat(tabel.t), 5);

  // The table shrinks to few rows, as when the period changes from 30 days to 1 hour.
  tabel.t.tBodies[0].children = tabel.t.tBodies[0].children.slice(0, 3);
  modul.terapkan(doc);
  sama("sesudah menyusut, ketiganya terlihat", terlihat(tabel.t), 3);
  benar("kontrolnya ikut dibuang", kontrolMilik(tabel.t) === null);
}

console.log();
console.log("=".repeat(74));
console.log("HASIL: " + lolos + " lolos, " + gagal + " gagal");
console.log("=".repeat(74));
process.exit(gagal ? 1 : 0);
