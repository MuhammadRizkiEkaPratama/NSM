/* Mengubah berkas diagram HTML di folder `diagram/` menjadi berkas PNG di
 * folder `gambar/`, memakai Chrome tanpa jendela lewat protokol DevTools.
 *
 * Dipisahkan dari `potret.js` karena tidak menyentuh NSM sama sekali: tidak
 * ada login, tidak ada jaringan, dan hasilnya tidak berubah selama berkas
 * HTML-nya tidak diubah.
 *
 * Cara pakai:  node potret_diagram.js
 */
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const MASUK = path.join(__dirname, "diagram");
const KELUAR = path.join(__dirname, "gambar");

const tidur = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  fs.mkdirSync(KELUAR, { recursive: true });
  const berkas = fs.readdirSync(MASUK).filter((n) => n.endsWith(".html"));
  if (berkas.length === 0) {
    console.error("tidak ada berkas .html di " + MASUK);
    process.exit(2);
  }

  const profil = path.join(os.tmpdir(), "nsm-diagram-profil");
  const anak = spawn(CHROME, [
    "--headless=new",
    "--remote-debugging-port=9334",
    "--no-first-run",
    "--disable-gpu",
    "--hide-scrollbars",
    "--user-data-dir=" + profil,
    "about:blank",
  ], { stdio: "ignore" });

  let sasaran = null;
  for (let i = 0; i < 40; i++) {
    await tidur(500);
    try {
      const r = await fetch("http://127.0.0.1:9334/json/list");
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
  const kirim = (method, params) =>
    new Promise((res, rej) => {
      const id = ++no;
      menunggu.set(id, { res, rej });
      ws.send(JSON.stringify({ id, method, params: params || {} }));
    });
  const nilai = async (e) => {
    const r = await kirim("Runtime.evaluate", { expression: e, returnByValue: true });
    return r.result ? r.result.value : null;
  };

  await kirim("Page.enable");
  await kirim("Runtime.enable");

  for (const nama of berkas) {
    const url = "file:///" + path.join(MASUK, nama).replace(/\\/g, "/");
    await kirim("Page.navigate", { url });
    await tidur(1200);

    // Ukuran diambil dari atribut svg, bukan dari ukuran jendela, supaya
    // gambar tidak punya bidang kosong di kanan atau di bawah.
    const ukur = await nilai(
      "(function(){var s=document.querySelector('svg');" +
      "return [Math.ceil(s.getAttribute('width')), Math.ceil(s.getAttribute('height'))];})()"
    );
    const lebar = (ukur && ukur[0]) || 1000;
    const tinggi = (ukur && ukur[1]) || 600;

    // deviceScaleFactor 3 supaya gambar tetap tajam saat dicetak.
    await kirim("Emulation.setDeviceMetricsOverride", {
      width: lebar, height: tinggi, deviceScaleFactor: 3, mobile: false,
    });
    await tidur(700);

    const g = await kirim("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    const keluar = path.join(KELUAR, nama.replace(/\.html$/, ".png"));
    fs.writeFileSync(keluar, Buffer.from(g.data, "base64"));
    const kb = (fs.statSync(keluar).size / 1024).toFixed(0);
    console.log("  " + nama.padEnd(32) + lebar + "x" + tinggi + " @3x  " + kb + " KB");
  }

  ws.close();
  anak.kill();
  console.log("selesai");
}
main().catch((e) => { console.error(e); process.exit(1); });
