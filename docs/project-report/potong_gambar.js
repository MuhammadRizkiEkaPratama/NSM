/* Memotong bagian atas beberapa tangkapan layar yang terlalu panjang ke bawah.
 *
 * Tiga halaman NSM sangat tinggi. Dipasang selebar 14 cm di dalam laporan,
 * masing-masing memakan hampir satu halaman penuh, sementara bagian bawahnya
 * hanya mengulang baris yang tidak menambah keterangan.
 *
 * Pemotongan dikerjakan terhadap berkas PNG yang sudah ada, bukan dengan
 * mengambil ulang dari NSM. Alasannya dua: tidak perlu masuk ke aplikasi, dan
 * hasilnya sama setiap kali dijalankan karena sumbernya berkas yang tetap.
 * Caranya menampilkan gambar pada halaman kosong lalu memotret bagian atasnya
 * lewat parameter `clip`, sehingga tidak perlu memasang pustaka pengolah gambar.
 *
 * Versi penuh setiap gambar tetap disimpan dengan awalan `lampiran-` untuk
 * dipakai di dokumen lampiran.
 *
 * Cara pakai:  node potong_gambar.js
 */
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const GAMBAR = path.join(__dirname, "gambar");

// nama berkas, tinggi potongan dalam piksel sumber
const POTONG = [
  ["konfig-pagar.png", 950],
  ["konfig-kepatuhan.png", 950],
  ["insiden-detail.png", 950],
  ["dashboard.png", 850],
  ["backup.png", 850],
  ["wawasan.png", 850],
  ["report.png", 800],
  ["insiden.png", 800],
  ["kesehatan.png", 800],
  ["konfig-firewall.png", 800],
];

const tidur = (ms) => new Promise((r) => setTimeout(r, ms));

function ukuranPng(jalur) {
  const b = fs.readFileSync(jalur).subarray(0, 24);
  return { lebar: b.readUInt32BE(16), tinggi: b.readUInt32BE(20) };
}

async function main() {
  const kerja = path.join(os.tmpdir(), "nsm-potong");
  fs.mkdirSync(kerja, { recursive: true });

  const anak = spawn(CHROME, [
    "--headless=new", "--remote-debugging-port=9337", "--no-first-run",
    "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
    "--user-data-dir=" + path.join(kerja, "profil"), "about:blank",
  ], { stdio: "ignore" });

  let sasaran = null;
  for (let i = 0; i < 40; i++) {
    await tidur(500);
    try {
      const r = await fetch("http://127.0.0.1:9337/json/list");
      sasaran = (await r.json()).find((t) => t.type === "page");
      if (sasaran) break;
    } catch (e) { /* Chrome belum siap */ }
  }
  if (!sasaran) { console.error("Chrome tidak menjawab"); anak.kill(); process.exit(1); }

  const ws = new WebSocket(sasaran.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let no = 0;
  const menunggu = new Map();
  ws.onmessage = (ev) => {
    const p = JSON.parse(ev.data);
    if (p.id && menunggu.has(p.id)) {
      const { res, rej } = menunggu.get(p.id);
      menunggu.delete(p.id);
      if (p.error) rej(new Error(p.error.message)); else res(p.result);
    }
  };
  const kirim = (m, p) => new Promise((res, rej) => {
    const id = ++no; menunggu.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method: m, params: p || {} }));
  });

  await kirim("Page.enable");
  await kirim("Runtime.enable");

  for (const [nama, tinggiPotong] of POTONG) {
    const asal = path.join(GAMBAR, nama);
    if (!fs.existsSync(asal)) { console.log("  " + nama + " tidak ada, dilewati"); continue; }

    // Versi penuh disimpan lebih dulu supaya lampiran tetap punya gambar utuh.
    const penuh = path.join(GAMBAR, "lampiran-" + nama);
    if (!fs.existsSync(penuh)) fs.copyFileSync(asal, penuh);

    const { lebar, tinggi } = ukuranPng(asal);
    if (tinggi <= tinggiPotong) {
      console.log("  " + nama.padEnd(26) + "sudah pendek, dilewati");
      continue;
    }

    const sementara = path.join(kerja, nama.replace(".png", "") + ".html");
    fs.writeFileSync(sementara,
      '<style>html,body{margin:0;padding:0;background:#fff}img{display:block}</style>' +
      '<img src="file:///' + asal.replace(/\\/g, "/") + '">');

    await kirim("Emulation.setDeviceMetricsOverride",
                { width: lebar, height: tinggiPotong, deviceScaleFactor: 1, mobile: false });
    await kirim("Page.navigate", { url: "file:///" + sementara.replace(/\\/g, "/") });
    await tidur(1500);

    const g = await kirim("Page.captureScreenshot", {
      format: "png",
      clip: { x: 0, y: 0, width: lebar, height: tinggiPotong, scale: 1 },
    });
    fs.writeFileSync(asal, Buffer.from(g.data, "base64"));

    const cmLama = (14.0 * tinggi / lebar).toFixed(1);
    const cmBaru = (14.0 * tinggiPotong / lebar).toFixed(1);
    console.log("  " + nama.padEnd(26) + tinggi + " -> " + tinggiPotong + " piksel   " +
                cmLama + " cm -> " + cmBaru + " cm");
  }

  ws.close();
  anak.kill();
  console.log("selesai");
}
main().catch((e) => { console.error(e); process.exit(1); });
