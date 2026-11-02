/* Mengambil ulang sebagian halaman NSM dalam bentuk terpotong.
 *
 * Tiga halaman NSM sangat panjang ke bawah. Dipasang selebar 14 cm di dalam
 * laporan, ketiganya masing-masing memakan hampir satu halaman penuh, dan
 * bagian bawahnya berisi pengulangan baris yang tidak menambah keterangan
 * apa pun. Memotongnya menghemat halaman sekaligus memperbesar skala tampilan
 * bagian yang benar-benar dirujuk teks.
 *
 * Pemotongan dilakukan lewat parameter `clip` pada Page.captureScreenshot,
 * bukan dengan memangkas berkas PNG sesudahnya, supaya tidak perlu memasang
 * pustaka pengolah gambar.
 *
 * Cara pakai:  node potret_potong.js riski <sandi>
 */
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const ASAL = "http://192.168.56.156:8080";
const KELUAR = path.join(__dirname, "gambar");
const PENGGUNA = process.argv[2];
const SANDI = process.argv[3];
const LEBAR = 1440;
const SKALA = 1.25;

// nama berkas, jalur halaman, jeda muat, tinggi potongan dalam piksel CSS
const HALAMAN = [
  ["konfig-pagar", "/admin/konfig/pagar", 4000, 900],
  ["konfig-kepatuhan", "/admin/konfig/kepatuhan", 4000, 920],
  ["insiden-detail", "/insiden/10", 3500, 900],
];

const tidur = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  if (!PENGGUNA || !SANDI) {
    console.error("pakai: node potret_potong.js <pengguna> <sandi>");
    process.exit(2);
  }
  const profil = path.join(os.tmpdir(), "nsm-potret-profil");
  const anak = spawn(CHROME, [
    "--headless=new", "--remote-debugging-port=9335", "--no-first-run",
    "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
    "--user-data-dir=" + profil, "about:blank",
  ], { stdio: "ignore" });

  let sasaran = null;
  for (let i = 0; i < 40; i++) {
    await tidur(500);
    try {
      const r = await fetch("http://127.0.0.1:9335/json/list");
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
  const nilai = async (e) => {
    const r = await kirim("Runtime.evaluate", { expression: e, returnByValue: true });
    return r.result ? r.result.value : null;
  };

  await kirim("Page.enable");
  await kirim("Runtime.enable");
  await kirim("Network.enable");

  // Kuki sesi lama di profil Chrome membuat pengiriman formulir login ditolak,
  // dan penolakannya terbaca persis seperti sandi salah. Membersihkannya lebih
  // dulu membuat setiap kali jalan berangkat dari keadaan yang sama.
  await kirim("Network.clearBrowserCookies");

  await kirim("Page.navigate", { url: ASAL + "/" });
  await tidur(3000);

  let dimana = await nilai("location.pathname");
  if (String(dimana).indexOf("/login") >= 0) {
    const skrip = [
      "(function(){",
      "  var u=document.querySelector('input[name=username]');",
      "  var p=document.querySelector('input[name=password]');",
      "  if(!u||!p){return 'form tidak ada';}",
      "  u.value=" + JSON.stringify(PENGGUNA) + ";",
      "  p.value=" + JSON.stringify(SANDI) + ";",
      "  document.querySelector('form').submit(); return 'terkirim';",
      "})()",
    ].join("\n");
    console.log("login:", await nilai(skrip));
    await tidur(8000);
    dimana = await nilai("location.pathname");
    if (String(dimana).indexOf("/login") >= 0) {
      console.error("GAGAL LOGIN"); ws.close(); anak.kill(); process.exit(3);
    }
  } else {
    console.log("memakai sesi yang sudah ada");
  }

  for (const [nama, jalur, jeda, tinggi] of HALAMAN) {
    try {
      await kirim("Emulation.setDeviceMetricsOverride",
                  { width: LEBAR, height: tinggi, deviceScaleFactor: SKALA, mobile: false });
      await kirim("Page.navigate", { url: ASAL + jalur });
      await tidur(jeda);
      const g = await kirim("Page.captureScreenshot", {
        format: "png",
        clip: { x: 0, y: 0, width: LEBAR, height: tinggi, scale: SKALA },
      });
      const berkas = path.join(KELUAR, nama + ".png");
      fs.writeFileSync(berkas, Buffer.from(g.data, "base64"));
      const cm = (14.0 * tinggi / LEBAR).toFixed(1);
      console.log("  " + nama.padEnd(20) + LEBAR + "x" + tinggi +
                  "  -> " + cm + " cm bila dipasang selebar 14 cm   " +
                  (fs.statSync(berkas).size / 1024).toFixed(0) + " KB");
    } catch (e) {
      console.log("  " + nama.padEnd(20) + "GAGAL: " + e.message);
    }
  }
  ws.close(); anak.kill();
  console.log("selesai");
}
main().catch((e) => { console.error(e); process.exit(1); });
