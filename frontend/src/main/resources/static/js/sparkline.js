/* Tiny chart inside a table row. Answers what one number cannot: whether 99.56% is one long outage or twenty short ones. Drawn as bars (each bar a time slice, height the percent of successful checks) because the data is sliced. Slices with no data are drawn as a faint line at the base, not skipped, so a monitoring gap does not look like uninterrupted uptime. */
function gambarSparkline(canvas, deret, opsi) {
  opsi = opsi || {};
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var lebar = canvas.clientWidth || 90;
  var tinggi = canvas.clientHeight || 22;

  if (canvas.width !== Math.round(lebar * dpr) || canvas.height !== Math.round(tinggi * dpr)) {
    canvas.width = Math.round(lebar * dpr);
    canvas.height = Math.round(tinggi * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, lebar, tinggi);

  if (!deret || !deret.length) return;

  var gaya = getComputedStyle(document.documentElement);
  var warnaUp = (gaya.getPropertyValue("--up") || "#4ade80").trim();
  var warnaHatiHati = (gaya.getPropertyValue("--hati-hati") || "#facc15").trim();
  var warnaDown = (gaya.getPropertyValue("--down") || "#f87171").trim();
  var warnaKosong = "#3a3a3a";

  var n = deret.length;
  var jarak = n > 60 ? 0 : 1;
  var lebarBatang = Math.max(1, (lebar - (n - 1) * jarak) / n);
  var tinggiMin = 2;

  for (var i = 0; i < n; i++) {
    var v = deret[i];
    var x = i * (lebarBatang + jarak);

    if (v === null || v === undefined) {
      ctx.fillStyle = warnaKosong;
      ctx.fillRect(x, tinggi - 1.5, lebarBatang, 1.5);
      continue;
    }

    // Same thresholds as the rest of the app, so colors match the availability number beside it.
    ctx.fillStyle = v >= 0.999 ? warnaUp : v >= 0.99 ? warnaHatiHati : warnaDown;

    var t = Math.max(tinggiMin, v * tinggi);
    ctx.fillRect(x, tinggi - t, lebarBatang, t);
  }

  // The worst slice is marked so the worst point is found at a glance.
  if (opsi.tandaiTerburuk !== false) {
    var terburuk = -1, nilaiTerburuk = 1.1;
    for (var j = 0; j < n; j++) {
      if (deret[j] !== null && deret[j] !== undefined && deret[j] < nilaiTerburuk) {
        nilaiTerburuk = deret[j];
        terburuk = j;
      }
    }
    if (terburuk >= 0 && nilaiTerburuk < 0.99) {
      ctx.fillStyle = "#ffffff";
      ctx.globalAlpha = 0.55;
      ctx.fillRect(terburuk * (lebarBatang + jarak), 0, Math.max(1, lebarBatang), 2);
      ctx.globalAlpha = 1;
    }
  }
}

function ringkasSparkline(deret, lebarDetik) {
  if (!deret || !deret.length) return "Belum ada data pemantauan";
  var adaData = 0, penuh = 0, terburuk = 1.1, kosong = 0;
  for (var i = 0; i < deret.length; i++) {
    var v = deret[i];
    if (v === null || v === undefined) { kosong++; continue; }
    adaData++;
    if (v >= 0.999) penuh++;
    if (v < terburuk) terburuk = v;
  }
  if (!adaData) return "Belum ada data pemantauan pada periode ini";

  var satuanPetak = lebarDetik >= 3600
    ? Math.round(lebarDetik / 3600) + " jam"
    : Math.round(lebarDetik / 60) + " menit";

  var kalimat = "Tiap batang mewakili " + satuanPetak + ". "
    + penuh + " dari " + adaData + " petak berjalan tanpa gangguan";
  if (terburuk < 0.999) {
    kalimat += ", dan petak terburuk hanya " + Math.round(terburuk * 100) + " persen berhasil";
  }
  kalimat += ".";
  if (kosong) {
    kalimat += " " + kosong + " petak tidak punya data, biasanya karena device "
      + "belum dipantau saat itu atau pemantauan sedang dijeda.";
  }
  return kalimat;
}
