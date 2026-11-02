/*
 * Simple line chart on a <canvas>, with no external library (keeps CSP at 'self').
 *
 * Usage:
 *     var g = new Grafik(canvas, {
 *         seri: [{nama: "Ping", warna: "#60a5fa"}],
 *         maksTitik: 60,
 *         format: function (v) { return v.toFixed(2) + " ms"; }
 *     });
 *     g.tambah([1.23]);      // one value per series
 *
 * When the point count reaches `maksTitik` the chart is cleared and filling restarts from the left, so the browser never holds more than `maksTitik` points.
 */

function Grafik(canvas, opsi) {
  this.canvas = canvas;
  this.ctx = canvas.getContext("2d");
  this.seri = opsi.seri || [];
  this.maksTitik = opsi.maksTitik || 60;
  this.format = opsi.format || function (v) { return String(Math.round(v)); };
  this.satuan = opsi.satuan || "";
  this.data = this.seri.map(function () { return []; });
  this.waktu = [];
  this.putaran = 0;
  this.kosongPesan = opsi.kosongPesan || "Menunggu data…";
  this.sorot = null;
  this._geo = null;

  var diri = this;
  window.addEventListener("resize", function () { diri.gambar(); });
  this._pasangSorot();
}

/* Hover reading: the cursor finds the nearest point horizontally (not nearest to the line), because readers think in time. */
Grafik.prototype._pasangSorot = function () {
  var diri = this;
  var c = this.canvas;

  c.addEventListener("pointermove", function (e) {
    if (!diri._geo || diri.waktu.length === 0) return;
    var r = c.getBoundingClientRect();
    var x = e.clientX - r.left;
    var g = diri._geo;

    var idx = Math.round((x - g.kiri) / g.langkah);
    idx = Math.max(0, Math.min(idx, diri.waktu.length - 1));

    if (x < g.kiri - 10 || x > g.kiri + g.L + 10) {
      if (diri.sorot !== null) { diri.sorot = null; diri.gambar(); sembunyikanPetunjukGrafik(); }
      return;
    }
    if (idx !== diri.sorot) { diri.sorot = idx; diri.gambar(); }
    tampilkanPetunjukGrafik(diri, idx, e.clientX, e.clientY);
  });

  c.addEventListener("pointerleave", function () {
    if (diri.sorot === null) return;
    diri.sorot = null;
    diri.gambar();
    sembunyikanPetunjukGrafik();
  });
};

var _petunjukGrafik = null;

function sembunyikanPetunjukGrafik() {
  if (_petunjukGrafik) _petunjukGrafik.classList.remove("terlihat");
}

function tampilkanPetunjukGrafik(grafik, idx, mx, my) {
  if (!_petunjukGrafik) {
    _petunjukGrafik = document.createElement("div");
    _petunjukGrafik.className = "petunjuk-grafik";
    document.body.appendChild(_petunjukGrafik);
  }
  var k = _petunjukGrafik;
  k.textContent = "";

  var waktu = grafik.waktu[idx];
  var judul = document.createElement("div");
  judul.className = "waktu";
  judul.textContent = waktu ? jamPendek(waktu) : "-";
  k.appendChild(judul);

  for (var s = 0; s < grafik.seri.length; s++) {
    var nilai = grafik.data[s][idx];
    var baris = document.createElement("div");
    baris.className = "baris";

    var tanda = document.createElement("span");
    tanda.className = "tanda";
    tanda.style.background = grafik.seri[s].warna || "#60a5fa";
    baris.appendChild(tanda);

    var nama = document.createElement("span");
    nama.className = "nama";
    nama.textContent = grafik.seri[s].nama;
    baris.appendChild(nama);

    var angka = document.createElement("span");
    angka.className = "angka";
    angka.textContent = (nilai === null || nilai === undefined)
      ? "tidak ada data" : grafik.format(nilai);
    baris.appendChild(angka);

    k.appendChild(baris);
  }

  k.classList.add("terlihat");
  var lebar = k.offsetWidth, tinggi = k.offsetHeight;
  var kiri = mx + 14, atas = my - tinggi - 10;
  if (kiri + lebar > window.innerWidth - 8) kiri = mx - lebar - 14;
  if (atas < 8) atas = my + 16;
  k.style.left = Math.round(kiri) + "px";
  k.style.top = Math.round(atas) + "px";
}

Grafik.prototype.tambah = function (nilai, waktuIso) {
  if (this.waktu.length >= this.maksTitik) {
    this.data = this.seri.map(function () { return []; });
    this.waktu = [];
    this.putaran++;
  }
  for (var i = 0; i < this.seri.length; i++) {
    var v = nilai[i];
    this.data[i].push(typeof v === "number" && isFinite(v) ? v : null);
  }
  this.waktu.push(waktuIso ? new Date(waktuIso) : new Date());
  this.gambar();
};

/* Bulk fill from old data when the page first opens. Only half the capacity is filled so the first new point does not immediately trigger a reset. */
Grafik.prototype.isiAwal = function (daftarNilai, daftarWaktu) {
  this.data = this.seri.map(function () { return []; });
  this.waktu = [];
  var muat = Math.max(1, Math.floor(this.maksTitik / 2));
  var batas = Math.min(daftarWaktu.length, muat);
  var mulai = daftarWaktu.length - batas;
  for (var t = mulai; t < daftarWaktu.length; t++) {
    for (var i = 0; i < this.seri.length; i++) {
      var v = daftarNilai[i][t];
      this.data[i].push(typeof v === "number" && isFinite(v) ? v : null);
    }
    this.waktu.push(new Date(daftarWaktu[t]));
  }
  this.gambar();
};

Grafik.prototype.jumlahTitik = function () { return this.waktu.length; };

/* Find a "round" Y-axis upper bound: 1, 2, 5, 10, 20, 50, 100, ... */
Grafik.prototype._batasAtas = function (maks) {
  if (!(maks > 0)) return 1;
  var pangkat = Math.pow(10, Math.floor(Math.log10(maks)));
  var sisa = maks / pangkat;
  var pengali = sisa <= 1 ? 1 : sisa <= 2 ? 2 : sisa <= 5 ? 5 : 10;
  return pengali * pangkat;
};

Grafik.prototype.gambar = function () {
  var c = this.canvas, ctx = this.ctx;
  var lebarCss = c.clientWidth || 600;
  var tinggiCss = c.clientHeight || 200;
  var dpr = window.devicePixelRatio || 1;

  // Draw at the real screen resolution, otherwise the canvas looks blurry.
  if (c.width !== Math.round(lebarCss * dpr) || c.height !== Math.round(tinggiCss * dpr)) {
    c.width = Math.round(lebarCss * dpr);
    c.height = Math.round(tinggiCss * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, lebarCss, tinggiCss);

  var kiri = 62, kanan = 12, atas = 26, bawah = 24;
  var L = lebarCss - kiri - kanan;
  var T = tinggiCss - atas - bawah;
  if (L <= 10 || T <= 10) return;

  var maks = 0, ada = false;
  for (var i = 0; i < this.data.length; i++) {
    for (var j = 0; j < this.data[i].length; j++) {
      var v = this.data[i][j];
      if (v === null) continue;
      ada = true;
      if (v > maks) maks = v;
    }
  }
  var batas = this._batasAtas(maks * 1.15);

  var langkahX = this.maksTitik > 1 ? L / (this.maksTitik - 1) : L;
  this._geo = { kiri: kiri, atas: atas, L: L, T: T, batas: batas, langkah: langkahX };

  // --- garis bantu mendatar + angka sumbu Y ---
  ctx.strokeStyle = "#2e2e2e";
  ctx.fillStyle = "#777";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.lineWidth = 1;
  for (var g = 0; g <= 4; g++) {
    var y = atas + T - (T * g / 4);
    ctx.beginPath();
    ctx.moveTo(kiri, Math.round(y) + 0.5);
    ctx.lineTo(kiri + L, Math.round(y) + 0.5);
    ctx.stroke();
    ctx.fillText(this.format(batas * g / 4), kiri - 8, y);
  }

  if (!ada) {
    ctx.fillStyle = "#5a5a5a";
    ctx.textAlign = "center";
    ctx.fillText(this.kosongPesan, kiri + L / 2, atas + T / 2);
    return;
  }

  var n = this.waktu.length;
  var langkah = this.maksTitik > 1 ? L / (this.maksTitik - 1) : L;

  for (var s = 0; s < this.seri.length; s++) {
    var titik = this.data[s];
    var warna = this.seri[s].warna || "#60a5fa";

    ctx.beginPath();
    var mulaiGambar = false, xAwal = kiri, xAkhir = kiri;
    for (var k = 0; k < titik.length; k++) {
      if (titik[k] === null) continue;
      var x = kiri + k * langkah;
      var yy = atas + T - (titik[k] / batas) * T;
      if (!mulaiGambar) { ctx.moveTo(x, yy); xAwal = x; mulaiGambar = true; }
      else ctx.lineTo(x, yy);
      xAkhir = x;
    }
    if (mulaiGambar) {
      ctx.lineTo(xAkhir, atas + T);
      ctx.lineTo(xAwal, atas + T);
      ctx.closePath();
      ctx.fillStyle = warna + "22";
      ctx.fill();
    }

    ctx.beginPath();
    mulaiGambar = false;
    for (var k2 = 0; k2 < titik.length; k2++) {
      if (titik[k2] === null) { mulaiGambar = false; continue; }
      var x2 = kiri + k2 * langkah;
      var y2 = atas + T - (titik[k2] / batas) * T;
      if (!mulaiGambar) { ctx.moveTo(x2, y2); mulaiGambar = true; }
      else ctx.lineTo(x2, y2);
    }
    ctx.strokeStyle = warna;
    ctx.lineWidth = 1.8;
    ctx.lineJoin = "round";
    ctx.stroke();

    for (var t2 = titik.length - 1; t2 >= 0; t2--) {
      if (titik[t2] === null) continue;
      var xt = kiri + t2 * langkah;
      var yt = atas + T - (titik[t2] / batas) * T;
      ctx.beginPath();
      ctx.arc(xt, yt, 3, 0, Math.PI * 2);
      ctx.fillStyle = warna;
      ctx.fill();
      break;
    }
  }

  if (this.sorot !== null && this.sorot < n) {
    var xs = kiri + this.sorot * langkah;
    ctx.save();
    ctx.strokeStyle = "#7a7a7a";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(Math.round(xs) + 0.5, atas);
    ctx.lineTo(Math.round(xs) + 0.5, atas + T);
    ctx.stroke();
    ctx.restore();

    for (var sp = 0; sp < this.seri.length; sp++) {
      var nilaiSorot = this.data[sp][this.sorot];
      if (nilaiSorot === null || nilaiSorot === undefined) continue;
      var ysp = atas + T - (nilaiSorot / batas) * T;
      ctx.beginPath();
      ctx.arc(xs, ysp, 5.5, 0, Math.PI * 2);
      ctx.fillStyle = "#141414";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(xs, ysp, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = this.seri[sp].warna || "#60a5fa";
      ctx.fill();
    }
  }

  // The range label width is computed first because it occupies the bottom right corner and the last time label must yield to it.
  ctx.font = "10px sans-serif";
  var teksRentang = n + "/" + this.maksTitik;
  if (n > 1) {
    teksRentang = rentangTeks((this.waktu[n - 1] - this.waktu[0]) / 1000)
                + " terakhir  ·  " + teksRentang;
  }
  var lebarRentang = ctx.measureText(teksRentang).width;

  // The range is also attached to the canvas element so the page can lift it into the chart title.
  this.canvas.dataset.rentang = teksRentang;

  ctx.fillStyle = "#666";
  ctx.textBaseline = "top";
  if (n > 0) {
    ctx.textAlign = "left";
    ctx.fillText(jamPendek(this.waktu[0]), kiri, atas + T + 6);
    var xAkhirLabel = kiri + (n - 1) * langkah;
    var batasKanan = kiri + L - lebarRentang - 12;
    if (n > 1 && xAkhirLabel - kiri > 70 && xAkhirLabel < batasKanan) {
      ctx.textAlign = "right";
      ctx.fillText(jamPendek(this.waktu[n - 1]), xAkhirLabel, atas + T + 6);
    }
  }

  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  var x0 = kiri;
  for (var s2 = 0; s2 < this.seri.length; s2++) {
    var w = this.seri[s2].warna || "#60a5fa";
    var terakhirNilai = null;
    for (var q = this.data[s2].length - 1; q >= 0; q--) {
      if (this.data[s2][q] !== null) { terakhirNilai = this.data[s2][q]; break; }
    }
    ctx.fillStyle = w;
    ctx.fillRect(x0, atas - 16, 9, 3);
    var teks = this.seri[s2].nama
             + (terakhirNilai === null ? "" : "  " + this.format(terakhirNilai));
    ctx.fillStyle = "#aaa";
    ctx.font = "11px sans-serif";
    ctx.fillText(teks, x0 + 14, atas - 15);
    x0 += 14 + ctx.measureText(teks).width + 18;
  }

  // Time range and fill level. The range must be shown because two side-by-side charts can cover very different spans (ping every 5 s vs bandwidth every 30 s with old samples). Drawn at the bottom right so it does not collide with the legend.
  ctx.textAlign = "right";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#5f5f5f";
  ctx.font = "10px sans-serif";
  ctx.fillText(teksRentang, kiri + L, atas + T + 6);
}

function rentangTeks(detik) {
  if (detik < 90) return Math.round(detik) + " detik";
  var menit = detik / 60;
  if (menit < 90) return Math.round(menit) + " menit";
  var jam = menit / 60;
  if (jam < 36) return (jam < 10 ? jam.toFixed(1).replace(".0", "") : Math.round(jam)) + " jam";
  return Math.round(jam / 24) + " hari";
}

function jamPendek(d) {
  function dua(x) { return x < 10 ? "0" + x : String(x); }
  return dua(d.getHours()) + ":" + dua(d.getMinutes()) + ":" + dua(d.getSeconds());
}
