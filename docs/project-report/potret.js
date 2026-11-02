/* Pengambil tangkapan layar halaman NSM untuk lampiran laporan magang.
 *
 * Dijalankan dari laptop, menembak NSM yang hidup di 192.168.56.156:8080.
 * Memakai Chrome tanpa jendela lewat protokol DevTools, bukan pustaka luar,
 * supaya tidak ada yang perlu dipasang lebih dulu.
 *
 * Tema dibiarkan gelap, yaitu bawaan NSM. Tema terang sempat dicoba lebih dulu
 * dengan alasan laporan akan dicetak, tetapi hasilnya justru setengah jadi:
 * kartu perangkat pada peta topologi tetap digambar gelap, sehingga halaman
 * terbaca sebagai campuran dua tema. Gelap seluruhnya lebih mudah dibaca
 * daripada terang yang tidak konsisten.
 *
 * Sesi yang sudah ada di profil Chrome dipakai ulang. Mengirim formulir login
 * di atas sesi yang masih berlaku justru ditolak Spring Security, dan itu
 * terbaca persis seperti "sandi salah" padahal sandinya benar.
 *
 * Cara pakai:  node potret.js <pengguna> <sandi>
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

const HALAMAN = [
  ["dashboard", "/", 4000],
  ["report", "/report", 4000],
  ["report-device", "/report/device/5", 3500],
  ["report-cetak", "/report/cetak", 4000],
  ["insiden", "/insiden", 3000],
  ["insiden-detail", "/insiden/10", 3000],
  ["services", "/services", 3000],
  ["traffic", "/traffic", 3500],
  ["konfig", "/admin/konfig", 3500],
  ["konfig-kepatuhan", "/admin/konfig/kepatuhan", 3500],
  ["konfig-firewall", "/admin/konfig/firewall", 3500],
  ["konfig-potret", "/admin/konfig/potret", 3000],
  ["konfig-perintah", "/admin/konfig/perintah", 3000],
  ["konfig-pagar", "/admin/konfig/pagar", 3500],
  ["konfig-identitas", "/admin/konfig/identitas", 3000],
  ["konfig-drift", "/admin/konfig/drift", 3000],
  ["kesehatan", "/admin/kesehatan", 4000],
  ["backup", "/admin/backup", 3500],
  ["wawasan", "/wawasan", 4000],
  ["agen", "/agen", 3000],
  ["syslog", "/syslog", 3000],
  ["audit", "/admin/audit", 3000],
  ["admin-users", "/admin/users", 3000],
  ["ldap", "/admin/ldap", 3000],
  ["notifikasi", "/account/notifikasi", 3000],
];

const tidur = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  if (!PENGGUNA || !SANDI) {
    console.error("pakai: node potret.js <pengguna> <sandi>");
    process.exit(2);
  }
  fs.mkdirSync(KELUAR, { recursive: true });
  const profil = path.join(os.tmpdir(), "nsm-potret-profil");
  const anak = spawn(CHROME, [
    "--headless=new",
    "--remote-debugging-port=9333",
    "--no-first-run",
    "--disable-gpu",
    "--hide-scrollbars",
    "--force-device-scale-factor=1",
    "--user-data-dir=" + profil,
    "about:blank",
  ], { stdio: "ignore" });

  let sasaran = null;
  for (let i = 0; i < 40; i++) {
    await tidur(500);
    try {
      const r = await fetch("http://127.0.0.1:9333/json/list");
      const d = await r.json();
      sasaran = d.find((t) => t.type === "page");
      if (sasaran) break;
    } catch (e) { /* Chrome belum siap, bukan kegagalan */ }
  }
  if (!sasaran) {
    console.error("Chrome tidak menjawab di port 9333");
    anak.kill();
    process.exit(1);
  }

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

  const buka = async (url, jeda) => { await kirim("Page.navigate", { url }); await tidur(jeda); };
  const nilai = async (ekspresi) => {
    const r = await kirim("Runtime.evaluate", { expression: ekspresi, awaitPromise: true, returnByValue: true });
    return r.result ? r.result.value : null;
  };

  await kirim("Page.enable");
  await kirim("Runtime.enable");

  await buka(ASAL + "/login", 2500);
  await nilai("localStorage.removeItem('nsm-tema')");

  await buka(ASAL + "/", 3000);
  let dimana = await nilai("location.pathname");
  console.log("keadaan awal:", dimana);

  if (String(dimana).indexOf("/login") >= 0) {
    const skrip = [
      "(function(){",
      "  var u = document.querySelector('input[name=username]');",
      "  var p = document.querySelector('input[name=password]');",
      "  if (!u || !p) { return 'form login tidak ditemukan'; }",
      "  u.value = " + JSON.stringify(PENGGUNA) + ";",
      "  p.value = " + JSON.stringify(SANDI) + ";",
      "  document.querySelector('form').submit();",
      "  return 'terkirim';",
      "})()",
    ].join("\n");
    console.log("login:", await nilai(skrip));
    await tidur(8000);
    dimana = await nilai("location.pathname + ' | ' + document.title");
    console.log("setelah login:", dimana);
    if (String(dimana).indexOf("/login") >= 0) {
      const pesan = await nilai("(document.body.innerText || '').slice(0, 400)");
      console.error("GAGAL LOGIN. Isi halaman:\n" + pesan);
      ws.close(); anak.kill(); process.exit(3);
    }
  } else {
    console.log("sudah masuk, memakai sesi yang ada");
  }

  for (let i = 0; i < HALAMAN.length; i++) {
    const nama = HALAMAN[i][0], jalur = HALAMAN[i][1], jeda = HALAMAN[i][2];
    try {
      await kirim("Emulation.setDeviceMetricsOverride", { width: LEBAR, height: 1000, deviceScaleFactor: 1.25, mobile: false });
      await buka(ASAL + jalur, jeda);
      const judul = await nilai("document.title");
      const t = await nilai("Math.min(document.documentElement.scrollHeight, 6000)");
      const tinggi = Math.max(700, t | 0);
      await kirim("Emulation.setDeviceMetricsOverride", { width: LEBAR, height: tinggi, deviceScaleFactor: 1.25, mobile: false });
      await tidur(1500);
      const g = await kirim("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      const berkas = path.join(KELUAR, nama + ".png");
      fs.writeFileSync(berkas, Buffer.from(g.data, "base64"));
      const kb = (fs.statSync(berkas).size / 1024).toFixed(0);
      console.log("  " + nama.padEnd(20) + LEBAR + "x" + tinggi + "  " + kb + " KB   " + judul);
    } catch (e) {
      console.log("  " + nama.padEnd(20) + "GAGAL: " + e.message);
    }
  }
  ws.close();
  anak.kill();
  console.log("selesai");
}
main().catch((e) => { console.error(e); process.exit(1); });
