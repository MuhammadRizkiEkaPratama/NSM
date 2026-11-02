/*
 * Fluid background that reacts to cursor and scroll, with no library (CSP stays at 'self').
 *
 * Metaball technique: each blob is a circle bright in the center and fading outward, drawn in "lighter" mode so overlapping colors add. A moderate CSS contrast then makes overlapping areas merge into one shape while thin edges disappear. Moderate contrast merges blobs only partially.
 *
 * The canvas is drawn at a quarter of the screen size and stretched; the result is blurred anyway and this cuts pixel work about sixteen times.
 */
(function () {
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var kanvas = document.createElement("canvas");
  kanvas.id = "latar-nsm";
  kanvas.setAttribute("aria-hidden", "true");
  document.body.insertBefore(kanvas, document.body.firstChild);
  var ctx = kanvas.getContext("2d", { alpha: false });

  var SKALA = 4;
  var lebar = 0, tinggi = 0;

  var gayaAkar = getComputedStyle(document.documentElement);
  function token(nama, cadangan) {
    var v = (gayaAkar.getPropertyValue(nama) || "").trim();
    return v || cadangan;
  }

  var WARNA_DASAR = token("--bg", "#1a1a1a");
  if (!/^#[0-9a-fA-F]{6}$/.test(WARNA_DASAR)) WARNA_DASAR = "#1a1a1a";

  /* Only blue and green: yellow means "needs attention" elsewhere in the app, so it is kept off the background. */
  var PALET = [
    token("--brand", "#2b6049"),
    token("--brand-terang", "#3d8a68"),
    token("--aksi-gelap", "#1d4ed8"),
    "#1e5f8f",
    "#2f7d5f",
    token("--aksi", "#2563eb")
  ];

  function acak(a, b) { return a + Math.random() * (b - a); }
  function ambilAcak(daftar) { return daftar[Math.floor(Math.random() * daftar.length)]; }

  /* Ensure the color is #rrggbb. Gradient midpoints append an alpha to the hex (e.g. "#2b6049" -> "#2b604980"); with rgb() or a named color `addColorStop` would throw and stop the whole animation, so other forms fall back to a valid default. */
  function hexAman(w, cadangan) {
    return /^#[0-9a-fA-F]{6}$/.test(w) ? w : cadangan;
  }

  var gumpalan = [];

  function siapkan() {
    /* Uses `documentElement.clientWidth`, not `window.innerWidth`: the difference is the scrollbar width, and using innerWidth made the canvas wider than the page, causing a horizontal scrollbar on long pages. */
    var lebarTersedia = document.documentElement.clientWidth || window.innerWidth;
    lebar = Math.max(1, Math.ceil(lebarTersedia / SKALA));
    tinggi = Math.max(1, Math.ceil(window.innerHeight / SKALA));
    kanvas.width = lebar;
    kanvas.height = tinggi;

    /* Randomized on every page load (count, size, color, position, direction, rhythm). Each blob also wanders: its heading is shifted by two waves with different periods and phases, so the path never repeats. */
    var jumlah = Math.round(acak(5, 8));
    var kecil = Math.min(lebar, tinggi);
    gumpalan = [];
    for (var i = 0; i < jumlah; i++) {
      gumpalan.push({
        x: acak(0, lebar),
        y: acak(0, tinggi),
        dx: acak(-0.16, 0.16),
        dy: acak(-0.16, 0.16),
        r: kecil * acak(0.30, 0.52),
        warna: hexAman(ambilAcak(PALET), "#2b6049"),
        fa: acak(0, Math.PI * 2), fb: acak(0, Math.PI * 2),
        ka: acak(0.00018, 0.00055), kb: acak(0.00012, 0.00040),
        px: 0, py: 0
      });
    }
  }

  /* Cursor stirs rather than follows: its velocity (not position) drags nearby blobs along with a slight push away. A still cursor has no effect. */
  var kursor = { x: -9999, y: -9999, vx: 0, vy: 0, ada: false };

  window.addEventListener("pointermove", function (e) {
    var x = e.clientX / SKALA, y = e.clientY / SKALA;
    if (kursor.ada) {
      kursor.vx = kursor.vx * 0.6 + (x - kursor.x) * 0.4;
      kursor.vy = kursor.vy * 0.6 + (y - kursor.y) * 0.4;
    }
    kursor.x = x; kursor.y = y; kursor.ada = true;
  }, { passive: true });

  window.addEventListener("pointerleave", function () {
    kursor.ada = false; kursor.vx = kursor.vy = 0;
  });

  /* Scroll: the liquid lags behind and swings back, modeled as a simple damped spring. */
  var geser = 0;
  var geserLaju = 0;
  var gulirTerakhir = window.scrollY || 0;

  window.addEventListener("scroll", function () {
    var kini = window.scrollY || 0;
    var selisih = kini - gulirTerakhir;
    gulirTerakhir = kini;
    // Scrolling down jerks the liquid UP (negative), since the container moves, not the content.
    geserLaju -= (selisih / SKALA) * 0.42;
    // Clamped so very fast scrolling does not throw blobs out.
    var BATAS = tinggi * 0.6;
    if (geserLaju > BATAS) geserLaju = BATAS;
    if (geserLaju < -BATAS) geserLaju = -BATAS;
  }, { passive: true });

  var mulai = performance.now();

  function langkah(waktu) {
    var t = waktu - mulai;

    // Scroll spring: pull back toward zero, then damp.
    geserLaju += (0 - geser) * 0.045;   // kekakuan pegas
    geserLaju *= 0.90;                  // redaman
    geser += geserLaju;

    // Fill the background opaque first so the CSS contrast works on predictable values.
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = WARNA_DASAR;
    ctx.fillRect(0, 0, lebar, tinggi);

    // Colors add up in "lighter" mode; that is what makes overlaps brighter and lets the contrast merge them.
    ctx.globalCompositeOperation = "lighter";

    for (var i = 0; i < gumpalan.length; i++) {
      var g = gumpalan[i];

      var ax = Math.sin(t * g.ka + g.fa) * 0.010;
      var ay = Math.cos(t * g.kb + g.fb) * 0.010;
      g.dx += ax; g.dy += ay;

      var laju = Math.sqrt(g.dx * g.dx + g.dy * g.dy);
      var LAJU_MAKS = 0.30;
      if (laju > LAJU_MAKS) { g.dx = g.dx / laju * LAJU_MAKS; g.dy = g.dy / laju * LAJU_MAKS; }

      // Pengadukan kursor.
      if (kursor.ada) {
        var jx = g.x - kursor.x, jy = g.y - kursor.y;
        var jarak = Math.sqrt(jx * jx + jy * jy) || 0.001;
        var JANGKAUAN = Math.min(lebar, tinggi) * 0.55;
        if (jarak < JANGKAUAN) {
          var kuat = 1 - jarak / JANGKAUAN;
          // Dragged along with the cursor motion: the main part of the stirring effect.
          g.px += kursor.vx * kuat * 0.16;
          g.py += kursor.vy * kuat * 0.16;
          // Pushed slightly away, so it makes way instead of sticking to the cursor.
          g.px += (jx / jarak) * kuat * 0.05;
          g.py += (jy / jarak) * kuat * 0.05;
        }
      }
      g.px *= 0.93; g.py *= 0.93;

      g.x += g.dx + g.px;
      g.y += g.dy + g.py;

      // Blobs bounce off the edges; wrapping around would look like a blink.
      var tepi = g.r * 0.55;
      if (g.x < -tepi) { g.x = -tepi; g.dx = Math.abs(g.dx); g.px = Math.abs(g.px); }
      if (g.x > lebar + tepi) { g.x = lebar + tepi; g.dx = -Math.abs(g.dx); g.px = -Math.abs(g.px); }
      if (g.y < -tepi) { g.y = -tepi; g.dy = Math.abs(g.dy); g.py = Math.abs(g.py); }
      if (g.y > tinggi + tepi) { g.y = tinggi + tepi; g.dy = -Math.abs(g.dy); g.py = -Math.abs(g.py); }

      // Scroll offset only affects drawing, not the real position, so bounce math stays stable on fast scrolls.
      var gy = g.y + geser;

      /* The blob core is deliberately not fully opaque: "lighter" mode sums colors, and overlapping opaque cores would glare and hide text. */
      var grad = ctx.createRadialGradient(g.x, gy, 0, g.x, gy, g.r);
      grad.addColorStop(0, g.warna + "9e");
      grad.addColorStop(0.42, g.warna + "4d");
      grad.addColorStop(1, "#00000000");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(g.x, gy, g.r, 0, Math.PI * 2);
      ctx.fill();
    }

    if (!document.hidden) requestAnimationFrame(langkah);
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      gulirTerakhir = window.scrollY || 0;
      requestAnimationFrame(langkah);
    }
  });

  var jedaUkur = null;
  window.addEventListener("resize", function () {
    clearTimeout(jedaUkur);
    jedaUkur = setTimeout(siapkan, 200);
  });

  siapkan();
  requestAnimationFrame(langkah);
})();
