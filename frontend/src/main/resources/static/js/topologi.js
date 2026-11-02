/*
 * Network topology map for the dashboard, drawn as hand-written SVG (the CSP is `script-src 'self'`, so no graph library can be loaded).
 * Two layers with different visual language: cables (straight lines, from `tautan_tetap` / the device_link table) and conversations (dashed arcs, from `tautan_lalu_lintas`).
 * Layout is deterministic, not a physics simulation, so the same data always yields the same map. Only user dragging moves nodes.
 * `sidik` skips identical messages and `sidikStruktur` separates status changes (update in place) from structure changes (rebuild), so dragged positions survive refreshes.
 * A legend is attached to the bottom-left corner of the map frame.
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  /* Storage key version. Dragged positions in `localStorage` override computed ones, so bumping the version discards positions saved with the old card spacing. */
  var KUNCI_POSISI = "nsm.topologi.posisi.v3";
  var KUNCI_TRAFIK = "nsm.topologi.tampilkan-trafik";

  /* Node card size. Cards (not circles) so name and address are readable together; spacing is trimmed rather than font size so labels stay legible at 1:1. */
  var LEBAR_KARTU = 152, TINGGI_KARTU = 42;

  /* Card spacing. Leaves wide enough corridors between columns and rows for several parallel lines to pass without touching cards. */
  var JARAK_X = 240, JARAK_Y = 92;

  var KORIDOR_X = JARAK_X - LEBAR_KARTU;   /* 88 */
  var KORIDOR_Y = JARAK_Y - TINGGI_KARTU;  /* 50 */
  var PAD = 24, TINGGI_JUDUL_LAJUR = 18, JARAK_LAJUR = 6;
  /* Height reserved at the bottom for the legend box; must exceed the real legend height (about 92px at full width). */
  var RUANG_LEGENDA = 104;

  var svg, dunia, statusEl, kosongEl, wrap;
  var lapisLajur, lapisKabel, lapisTrafik, lapisSimpul;
  var timerCadangan = null, gagalBerturut = 0, GAGAL_BERTURUT_MAKS = 3;

  var S = {
    sidik: null,
    sidikStruktur: null,
    simpul: {},             // kunci -> simpul
    kabel: [],              // tautan fisik
    trafik: [],             // percakapan
    posisi: muatPosisi(), // key -> {x, y} from user drags
    skala: 1, geserX: 0, geserY: 0,
    lebar: 0, tinggi: 0,
    tampilTrafik: localStorage.getItem(KUNCI_TRAFIK) !== "0"
  };

  var TEKS_STATUS = {
    up: "menjawab", down: "tidak menjawab", tanya: "belum pernah diperiksa"
  };

  /* Meaning of each link kind, shared by the lines and the legend so the two cannot disagree. */
  var JENIS_JALUR = {
    kabel:    { label: "Kabel langsung", kelas: "j-kabel" },
    segmen:   { label: "Satu segmen LAN", kelas: "j-segmen" },
    wan:      { label: "WAN antar-lokasi (lewat ISP)", kelas: "j-wan" },
    nirkabel: { label: "Nirkabel", kelas: "j-nirkabel" }
  };

  function elSvg(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function fmtByte(n) {
    if (!n || n <= 0) return "0 B";
    var unit = ["B", "KB", "MB", "GB"], i = 0;
    while (n >= 1024 && i < unit.length - 1) { n /= 1024; i++; }
    return n.toFixed(i ? 1 : 0) + " " + unit[i];
  }

  /* Stroke width follows volume on a log scale, so one huge connection does not shrink the rest to invisible hairlines. */
  function tebalGaris(totalByte) {
    if (!totalByte || totalByte <= 0) return 1.2;
    return Math.max(1.2, Math.min(6, 1.2 + Math.log10(1 + totalByte / 1024) * 0.95));
  }

  function bentukUntukIkon(p) {
    return { device_type: p.jenis, platform: p.platform, location: p.lokasi };
  }

  function muatPosisi() {
    try { return JSON.parse(localStorage.getItem(KUNCI_POSISI)) || {}; }
    catch (e) { return {}; }
  }

  function simpanPosisi() {
    try { localStorage.setItem(KUNCI_POSISI, JSON.stringify(S.posisi)); }
    catch (e) { /* Storage full or denied: the map still works, positions are just not remembered. */ }
  }

  // =========================================================================
  // 1. TATA LETAK
  // =========================================================================

  /* Depth of each node from the network core, by BFS over cables (not conversations). The root is the node with the most cables, usually a core switch or router. */
  function hitungKedalaman(kunciSimpul, kabel) {
    var tetangga = {};
    kunciSimpul.forEach(function (k) { tetangga[k] = []; });
    kabel.forEach(function (t) {
      if (tetangga[t.a] && tetangga[t.b]) {
        tetangga[t.a].push(t.b);
        tetangga[t.b].push(t.a);
      }
    });

    var dalam = {}, belum = kunciSimpul.slice();
    while (belum.length) {
      var akar = belum[0];
      belum.forEach(function (k) {
        if (tetangga[k].length > tetangga[akar].length) akar = k;
      });

      var antre = [akar];
      dalam[akar] = 0;
      while (antre.length) {
        var k = antre.shift();
        tetangga[k].forEach(function (t) {
          if (dalam[t] === undefined) { dalam[t] = dalam[k] + 1; antre.push(t); }
        });
      }
      belum = belum.filter(function (k) { return dalam[k] === undefined; });
    }
    return dalam;
  }

  /* Place each node. Horizontal lane = location, column = depth from the core. Positions the user has dragged always win over computed ones. */
  function tataLetak() {
    var kunci = Object.keys(S.simpul);
    var dalam = hitungKedalaman(kunci, S.kabel);

    var lajur = {}, urutanLajur = [];
    kunci.sort().forEach(function (k) {
      var s = S.simpul[k];
      if (!lajur[s.lokasi]) { lajur[s.lokasi] = []; urutanLajur.push(s.lokasi); }
      lajur[s.lokasi].push(s);
    });
    urutanLajur.sort(function (a, b) {
      // "Outside the lab network" always goes last instead of being sorted alphabetically.
      if (a === "Di luar jaringan lab") return 1;
      if (b === "Di luar jaringan lab") return -1;
      return a < b ? -1 : a > b ? 1 : 0;
    });

    var y = PAD + TINGGI_JUDUL_LAJUR, lebarMaks = 0;
    S.lajur = [];
    urutanLajur.forEach(function (nama) {
      var isi = lajur[nama];

      var perKolom = {};
      isi.forEach(function (s) {
        var d = dalam[s.kunci] === undefined ? 0 : dalam[s.kunci];
        (perKolom[d] = perKolom[d] || []).push(s);
      });

      /* Order within a column: barycentric (average position of neighbors in the previous column) to reduce crossings, with alphabetical order as the tie-break so the layout is stable across loads. */
      var urutKolom = Object.keys(perKolom)
        .map(Number).sort(function (a, b) { return a - b; });
      var posisiUrut = {};   /* key -> index within its column */

      var tinggiLajur = 0;
      urutKolom.forEach(function (d) {
        var kolom = perKolom[d];
        kolom.forEach(function (s) {
          var tetangga = (S.tetangga && S.tetangga[s.kunci]) || [];
          var nilai = [];
          tetangga.forEach(function (k) {
            if (posisiUrut[k] !== undefined) nilai.push(posisiUrut[k]);
          });
          s._barisentrum = nilai.length
            ? nilai.reduce(function (a, b) { return a + b; }, 0) / nilai.length
            : Infinity;   
        });
        kolom.sort(function (a, b) {
          if (a._barisentrum !== b._barisentrum) {
            return a._barisentrum - b._barisentrum;
          }
          return a.nama < b.nama ? -1 : 1;
        });
        kolom.forEach(function (s, i) { posisiUrut[s.kunci] = i; });
        kolom.forEach(function (s, i) {
          // x and y are the card center, so half the card width must be included or the first column is clipped.
          s.xAsal = PAD + LEBAR_KARTU / 2 + Number(d) * JARAK_X;
          s.yAsal = y + TINGGI_KARTU / 2 + i * JARAK_Y;
        });
        tinggiLajur = Math.max(tinggiLajur, kolom.length * JARAK_Y);
        lebarMaks = Math.max(lebarMaks,
                             PAD + LEBAR_KARTU + Number(d) * JARAK_X);
      });

      S.lajur.push({ nama: nama, y: y - TINGGI_JUDUL_LAJUR - 4,
                     tinggi: tinggiLajur + TINGGI_JUDUL_LAJUR - 4 });
      y += tinggiLajur + TINGGI_JUDUL_LAJUR + JARAK_LAJUR;
    });

    // User-dragged positions override computed ones, not the other way around.
    kunci.forEach(function (k) {
      var s = S.simpul[k], p = S.posisi[k];
      s.x = p ? p.x : s.xAsal;
      s.y = p ? p.y : s.yAsal;
    });

    /* Location boxes are recomputed from the actual (possibly dragged) positions of their members. Boxes with no members are not drawn. */
    var kotak = {};
    kunci.forEach(function (k) {
      var s = S.simpul[k];
      var b = kotak[s.lokasi] || (kotak[s.lokasi] = {
        nama: s.lokasi, x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity
      });
      b.x1 = Math.min(b.x1, s.x - LEBAR_KARTU / 2);
      b.x2 = Math.max(b.x2, s.x + LEBAR_KARTU / 2);
      b.y1 = Math.min(b.y1, s.y - TINGGI_KARTU / 2);
      b.y2 = Math.max(b.y2, s.y + TINGGI_KARTU / 2);
    });
    S.lajur = Object.keys(kotak).map(function (nama) {
      var b = kotak[nama];
      return {
        nama: nama,
        x: b.x1 - 18,
        y: b.y1 - TINGGI_JUDUL_LAJUR - 8,
        lebar: (b.x2 - b.x1) + 36,
        tinggi: (b.y2 - b.y1) + TINGGI_JUDUL_LAJUR + 20
      };
    }).sort(function (a, b) { return a.y - b.y; });

    beriLajurKabel();

    /* Canvas size comes from the real bounds of all location boxes, so dragged cards are never clipped by the frame. */
    var batasX = 560, batasY = 260;
    S.lajur.forEach(function (l) {
      batasX = Math.max(batasX, l.x + l.lebar);
      batasY = Math.max(batasY, l.y + l.tinggi);
    });
    S.lebar = Math.max(lebarMaks + PAD, batasX + PAD);
    // Space for the legend in the bottom-left corner. The legend is attached to the frame and does not pan, so no card may be placed there.
    S.tinggi = Math.max(y + PAD + RUANG_LEGENDA,
                        batasY + PAD + RUANG_LEGENDA, 260);
  }

  // =========================================================================
  // 2. GEOMETRI GARIS
  // =========================================================================

  /* Lines stop at the card edge instead of running through to its center. */
  /* Line geometry. Lines leave a card side perpendicular from a fixed plug point, change direction only in the corridors between columns/rows (guaranteed free of cards), and lines sharing a corridor get separate lanes. */

  /* Plug point: the middle of one of the four card sides, so lines always enter perpendicular. */
  function colok(s, sisi) {
    var hw = LEBAR_KARTU / 2, hh = TINGGI_KARTU / 2;
    if (sisi === "kiri")  return { x: s.x - hw, y: s.y, dx: -1, dy: 0 };
    if (sisi === "kanan") return { x: s.x + hw, y: s.y, dx: 1, dy: 0 };
    if (sisi === "atas")  return { x: s.x, y: s.y - hh, dx: 0, dy: -1 };
    return { x: s.x, y: s.y + hh, dx: 0, dy: 1 };
  }

  /* Which side to use toward `ke`, chosen from the dominant direction to keep routes short with few bends. */
  function sisiMenuju(dari, ke) {
    var dx = ke.x - dari.x, dy = ke.y - dari.y;
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? "kanan" : "kiri";
    return dy >= 0 ? "bawah" : "atas";
  }

  /* Smooth cubic curve between two plug points. Each control point is pulled perpendicular out of its card side; `geser` offsets both control points sideways so lines sharing a corridor curve side by side. */
  function kendali(p1, p2, geser) {
    geser = geser || 0;
    var dx = p2.x - p1.x, dy = p2.y - p1.y;
    var jarak = Math.sqrt(dx * dx + dy * dy) || 1;

    /* How far control points are pulled out of the card: a third of the distance, clamped. */
    var tarik = Math.max(28, Math.min(120, jarak / 3));

    var nx = -dy / jarak, ny = dx / jarak;

    var c1 = { x: p1.x + p1.dx * tarik + nx * geser,
               y: p1.y + p1.dy * tarik + ny * geser };
    var c2 = { x: p2.x + p2.dx * tarik + nx * geser,
               y: p2.y + p2.dy * tarik + ny * geser };

    return [c1, c2];
  }

  function teksBezier(p1, c1, c2, p2) {
    return "M" + bulat(p1.x) + "," + bulat(p1.y) +
           " C" + bulat(c1.x) + "," + bulat(c1.y) +
           " " + bulat(c2.x) + "," + bulat(c2.y) +
           " " + bulat(p2.x) + "," + bulat(p2.y);
  }

  /* Try several arc sizes and use the first that touches no other card. The order alternates between directions so curves do not all bulge the same way. */
  function rute(p1, p2, geser, kotak) {
    var coba = [0, 26, -26, 52, -52, 84, -84, 120, -120];
    var terbaik = null, skorTerbaik = Infinity;
    for (var i = 0; i < coba.length; i++) {
      var g = (geser || 0) + coba[i];
      var c = kendali(p1, p2, g);
      var n = kotak ? tabrakan(p1, c[0], c[1], p2, kotak) : 0;
      if (n === 0) return teksBezier(p1, c[0], c[1], p2);
      if (n < skorTerbaik) { skorTerbaik = n; terbaik = c; }
    }
    return teksBezier(p1, terbaik[0], terbaik[1], p2);
  }

  /* Curves that avoid cards. Each path is tried with several arc sizes and the first one that touches no card other than its own endpoints wins; if none is clean, the one with the fewest overlaps is used. Samples come straight from the cubic bezier formula, not DOM `getPointAtLength()`, because this runs before the elements exist. */

  /* Bounding box of all cards, with a small margin. */
  function halangan(kecualiA, kecualiB) {
    var m = 4, hasil = [];
    Object.keys(S.simpul).forEach(function (k) {
      if (k === kecualiA || k === kecualiB) return;
      var s = S.simpul[k];
      hasil.push({ x1: s.x - LEBAR_KARTU / 2 - m, x2: s.x + LEBAR_KARTU / 2 + m,
                   y1: s.y - TINGGI_KARTU / 2 - m, y2: s.y + TINGGI_KARTU / 2 + m });
    });
    return hasil;
  }

  function titikBezier(p1, c1, c2, p2, t) {
    var u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
    return { x: a * p1.x + b * c1.x + c * c2.x + d * p2.x,
             y: a * p1.y + b * c1.y + c * c2.y + d * p2.y };
  }

  /* Number of sample points that fall inside another card. 0 = clean. */
  function tabrakan(p1, c1, c2, p2, kotak) {
    var n = 0;
    for (var i = 1; i < 40; i++) {
      var t = titikBezier(p1, c1, c2, p2, i / 40);
      for (var j = 0; j < kotak.length; j++) {
        var k = kotak[j];
        if (t.x > k.x1 && t.x < k.x2 && t.y > k.y1 && t.y < k.y2) { n++; break; }
      }
    }
    return n;
  }

  function bulat(n) { return Math.round(n * 10) / 10; }

  /* Assign each cable a lane within its corridor. Cables leaving the same side in the same direction would overlap, so the key is (corridor, direction) and members alternate left and right of the center line. */
  function beriLajurKabel() {
    var kelompok = {};
    S.kabel.forEach(function (t) {
      var a = S.simpul[t.a], b = S.simpul[t.b];
      if (!a || !b) return;
      var s1 = sisiMenuju(a, b);
      var mendatar = (s1 === "kiri" || s1 === "kanan");
      var koridor = mendatar
        ? "x:" + Math.round(((a.x + b.x) / 2) / 10)
        : "y:" + Math.round(((a.y + b.y) / 2) / 10);
      (kelompok[koridor] = kelompok[koridor] || []).push(t);
    });
    var maks = Math.min(KORIDOR_X, KORIDOR_Y) / 2 - 6;
    Object.keys(kelompok).forEach(function (k) {
      var anggota = kelompok[k];
      anggota.forEach(function (t, i) {
        if (anggota.length === 1) { t.geser = 0; return; }
        var langkah = Math.min(12, (maks * 2) / anggota.length);
        t.geser = (i - (anggota.length - 1) / 2) * langkah;
      });
    });
  }

  function jalurKabel(a, b, geser) {
    var s1 = sisiMenuju(a, b), s2 = sisiMenuju(b, a);
    return rute(colok(a, s1), colok(b, s2), geser,
                halangan(a.kunci, b.kunci));
  }

  /* Conversations follow the physical path, found by BFS over the cable graph. BFS (hop count) is used because the lab graph has no trustworthy weights, and it picks the same path every time. */

  /* Adjacency map built from the CABLES, rebuilt whenever the layout changes. */
  function bangunTetangga() {
    var t = {};
    Object.keys(S.simpul).forEach(function (k) { t[k] = []; });
    S.kabel.forEach(function (e) {
      if (t[e.a] && t[e.b]) { t[e.a].push(e.b); t[e.b].push(e.a); }
    });
    S.tetangga = t;
  }

  /* Nodes from a to b over cables, including both ends. Returns null when there is no cable path (for example addresses outside the lab), rather than inventing a route. */
  function jalurFisik(a, b) {
    var tet = S.tetangga || {};
    if (!tet[a] || !tet[b]) return null;
    var dari = {}, antre = [a];
    dari[a] = null;
    while (antre.length) {
      var k = antre.shift();
      if (k === b) {
        var jalan = [];
        for (var n = b; n !== null && n !== undefined; n = dari[n]) jalan.unshift(n);
        return jalan;
      }
      (tet[k] || []).forEach(function (x) {
        if (dari[x] === undefined) { dari[x] = k; antre.push(x); }
      });
    }
    return null;
  }

  /* Smooth curve through a list of points: midpoints become the anchors and the original nodes the control points. */
  function hitungJalurTrafik() {
    var perKoridor = {};
    S.trafik.forEach(function (t) {
      t.jalan = jalurFisik(t.a, t.b);
      var kunci = t.jalan ? t.jalan.join(">") : "langsung";
      perKoridor[kunci] = (perKoridor[kunci] || 0);
      t.lajur = perKoridor[kunci]++;
    });
  }

  /* Conversation arc, orthogonal and following the physical path. Each hop reuses the cable's route, offset to a different lane so conversations do not sit on the cable; `t.lajur` comes from `hitungJalurTrafik()` and is converted to a pixel offset. */
  function jalurTrafik(t) {
    var a = S.simpul[t.a], b = S.simpul[t.b];
    var jalan = t.jalan;

    /* Lane offset, clamped to stay inside the card-free corridor. */
    var maks = Math.min(KORIDOR_X, KORIDOR_Y) / 2 - 6;
    var geser = Math.min(maks, 8 + (t.lajur || 0) * 9);

    if (!jalan || jalan.length < 3) return jalurKabel(a, b, geser);

    /* Known path: connect hop by hop, using the same route as the cable underneath. */
    var potongan = [];
    for (var i = 0; i < jalan.length - 1; i++) {
      var s1 = S.simpul[jalan[i]], s2 = S.simpul[jalan[i + 1]];
      if (!s1 || !s2) continue;
      potongan.push(jalurKabel(s1, s2, geser));
    }
    return potongan.join(" ");
  }


  function susun(d) {
    var perangkat = (d && d.perangkat) || [];
    var trafikMentah = (d && d.tautan_lalu_lintas) || [];
    var tetap = (d && d.tautan_tetap) || [];

    var simpul = {};
    perangkat.forEach(function (p) {
      simpul["d" + p.id] = {
        kunci: "d" + p.id, tipe: "perangkat", data: p, nama: p.nama,
        lokasi: p.lokasi || "Tanpa lokasi tercatat"
      };
    });

    // Foreign addresses are kept: who in the lab talks outside, and to where, is exactly what a security map should show.
    trafikMentah.forEach(function (t) {
      if (t.dikenal) return;
      var k = "x" + t.ke_alamat;
      if (!simpul[k]) {
        simpul[k] = {
          kunci: k, tipe: "luar", nama: t.ke_alamat,
          data: { ip: t.ke_alamat, luar_jaringan: t.luar_jaringan },
          lokasi: "Di luar jaringan lab"
        };
      }
    });

    var kabel = [];
    tetap.forEach(function (t) {
      var a = "d" + t.dari_id, b = "d" + t.ke_id;
      if (!simpul[a] || !simpul[b] || a === b) return;
      kabel.push({
        kunci: "k" + t.id, a: a, b: b,
        jenis: JENIS_JALUR[t.jenis] ? t.jenis : "kabel",
        keterangan: t.keterangan || ""
      });
    });

    // Conversations are merged into undirected pairs (A->B and B->A are one arc).
    var petaTepi = {};
    trafikMentah.forEach(function (t) {
      var kA = "d" + t.dari_id;
      var kB = t.dikenal ? "d" + t.ke_id : "x" + t.ke_alamat;
      if (!simpul[kA] || !simpul[kB] || kA === kB) return;
      var kunci = [kA, kB].sort().join("|");
      var e = petaTepi[kunci];
      if (!e) e = petaTepi[kunci] = { kunci: "t" + kunci, a: kA, b: kB,
                                      byte: 0, koneksi: 0, pintu: {}, terakhir: null };
      e.byte += (t.byte_masuk || 0) + (t.byte_keluar || 0);
      e.koneksi += t.koneksi || 0;
      (t.pintu || []).forEach(function (p) {
        if (!e.pintu[p.port] || p.nama) e.pintu[p.port] = p.nama;
      });
      if (t.terakhir && (!e.terakhir || t.terakhir > e.terakhir)) e.terakhir = t.terakhir;
    });

    return {
      simpul: simpul, kabel: kabel,
      trafik: Object.keys(petaTepi).map(function (k) { return petaTepi[k]; })
    };
  }

  /* Layout fingerprint: which devices and cables exist, without status, bytes, or connection counts. It separates a redraw from an in-place update. */
  function sidikStruktur(b) {
    return Object.keys(b.simpul).sort().join(",") + "||" +
           b.kabel.map(function (t) { return t.a + ">" + t.b + ":" + t.jenis; }).sort().join(",") + "||" +
           b.trafik.map(function (t) { return t.a + ">" + t.b; }).sort().join(",");
  }

  // =========================================================================
  // 4. MENGGAMBAR
  // =========================================================================

  function kosongkanSopan(teks) {
    if (dunia) dunia.replaceChildren();
    if (kosongEl) { kosongEl.textContent = teks; kosongEl.hidden = false; }
    if (svg) svg.setAttribute("aria-hidden", "true");
  }

  function terima(d) {
    if (!svg) return;
    // Guard 1: identical to what is already drawn.
    if (d && d.sidik && d.sidik === S.sidik) return;
    S.sidik = (d && d.sidik) || null;

    var perangkat = (d && d.perangkat) || [];
    if (!perangkat.length) {
      kosongkanSopan("Belum ada perangkat terdaftar untuk dipetakan.");
      return;
    }
    if (kosongEl) kosongEl.hidden = true;
    if (svg) svg.removeAttribute("aria-hidden");

    var b = susun(d);
    var sidikBaru = sidikStruktur(b);

    // Guard 2: same layout, only numbers changed, so update colors, widths, and captions in place.
    if (sidikBaru === S.sidikStruktur) {
      perbaruiDiTempat(b);
      return;
    }
    S.sidikStruktur = sidikBaru;
    S.simpul = b.simpul; S.kabel = b.kabel; S.trafik = b.trafik;
    bangunTetangga();
    hitungJalurTrafik();
    tataLetak();
    bangun();
  }

  /* The `viewBox` equals the frame size in pixels, so one drawing unit is one screen pixel and label size does not shrink as devices are added. Larger content is handled by pan and zoom. */
  function pasangViewBox() {
    var r = svg.getBoundingClientRect();
    var w = Math.max(320, Math.round(r.width));
    var h = Math.max(240, Math.round(r.height));
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    S.ukuran = { w: w, h: h };
    return S.ukuran;
  }

  /* Re-measure after the browser finishes layout (the first measurement can precede full CSS). If the user has already touched the view, the size is updated but the view is not refitted. */
  function segarkanUkuran() {
    if (!S.lebar) return;
    var lama = S.ukuran || { w: 0, h: 0 };
    var u = pasangViewBox();
    if (!S.disentuh && (Math.abs(u.w - lama.w) > 2 || Math.abs(u.h - lama.h) > 2 || !S.pernahDipaskan)) {
      paskan(u);
      S.pernahDipaskan = true;
      terapkanPandangan();
    }
  }

  /* Initial view: fit when content is larger than the frame, 1:1 when it fits; never zoomed above 100%. */
  function paskan(ukuran) {
    var muat = Math.min((ukuran.w - 24) / S.lebar, (ukuran.h - 24) / S.tinggi);
    S.skala = Math.max(0.45, Math.min(1, muat));
    // Centered on both axes.
    S.geserX = Math.max(12, (ukuran.w - S.lebar * S.skala) / 2);
    S.geserY = Math.max(12, (ukuran.h - S.tinggi * S.skala) / 2);
  }

  function bangun() {
    dunia.replaceChildren();
    var ukuran = pasangViewBox();

    lapisLajur  = elSvg("g", { class: "topo-lapis-lajur" });
    lapisKabel  = elSvg("g", { class: "topo-lapis-kabel" });
    lapisTrafik = elSvg("g", { class: "topo-lapis-trafik" });
    lapisSimpul = elSvg("g", { class: "topo-lapis-simpul" });
    // Order matters: rearmost lane first, front-most card last.
    dunia.appendChild(lapisLajur);
    dunia.appendChild(lapisTrafik);
    dunia.appendChild(lapisKabel);
    dunia.appendChild(lapisSimpul);

    (S.lajur || []).forEach(function (l) {
      lapisLajur.appendChild(elSvg("rect", {
        x: l.x, y: l.y, rx: 10,
        width: l.lebar, height: l.tinggi, class: "topo-lajur"
      }));
      var t = elSvg("text", { x: l.x + 12, y: l.y + 15, class: "topo-label-lokasi" });
      t.textContent = l.nama;
      lapisLajur.appendChild(t);
    });

    S.kabel.forEach(gambarKabel);
    S.trafik.forEach(gambarTrafik);
    Object.keys(S.simpul).forEach(function (k) { gambarSimpul(S.simpul[k]); });

    terapkanTrafikTampil();
    if (!S.pernahDipaskan) { paskan(ukuran); S.pernahDipaskan = true; }
    terapkanPandangan();
    if (window.requestAnimationFrame) requestAnimationFrame(segarkanUkuran);
  }

  function gambarKabel(t) {
    var a = S.simpul[t.a], b = S.simpul[t.b];
    var p = elSvg("path", {
      d: jalurKabel(a, b, t.geser || 0), tabindex: "0",
      class: "topo-kabel " + JENIS_JALUR[t.jenis].kelas
    });
    // A cable with a dead endpoint is dimmed, not drawn red: only the device's ping failed, not necessarily the cable.
    if (mati(a) || mati(b)) p.classList.add("ujung-mati");
    p.setAttribute("data-petunjuk", ketKabel(t, a, b));
    t.el = p;
    lapisKabel.appendChild(p);
  }

  function gambarTrafik(t) {
    var p = elSvg("path", {
      d: jalurTrafik(t), tabindex: "0",
      class: "topo-trafik" + (t.jalan && t.jalan.length > 2 ? "" : " tak-terjejak"),
      "stroke-width": tebalGaris(t.byte).toFixed(2)
    });
    p.setAttribute("data-petunjuk", ketTrafik(t, S.simpul[t.a], S.simpul[t.b]));
    t.el = p;
    lapisTrafik.appendChild(p);
  }

  function ketKabel(t, a, b) {
    return "JALUR TETAP — " + a.nama + " <-> " + b.nama + ". " +
           JENIS_JALUR[t.jenis].label +
           (t.keterangan ? ". " + t.keterangan : "") +
           ". Ini jalur yang tercatat di NSM, bukan hasil deteksi otomatis: " +
           "NSM tidak membaca LLDP/CDP, jadi kabel yang dicabut diam-diam " +
           "tidak akan hilang sendiri dari peta ini.";
  }

  /* The hop list goes in the caption too, since device names cannot be read from the arc shape. */
  function teksLompatan(t) {
    if (!t.jalan || t.jalan.length < 3) return "";
    var tengah = t.jalan.slice(1, -1).map(function (k) {
      return S.simpul[k] ? S.simpul[k].nama : k;
    });
    return ". Jalurnya melewati " + tengah.join(" -> ") +
           " (" + (t.jalan.length - 1) + " lompatan)";
  }

  function ketTrafik(t, a, b) {
    var pintu = Object.keys(t.pintu).map(Number).sort(function (x, y) { return x - y; })
      .map(function (p) { return t.pintu[p] ? (t.pintu[p] + " (" + p + ")") : ("port " + p); });
    return "PERCAKAPAN — " + a.nama + " <-> " + b.nama + ": " + t.koneksi +
           " koneksi, " + fmtByte(t.byte) + ", lewat " +
           (pintu.length ? pintu.join(", ") : "pintu tidak dikenali") +
           teksLompatan(t) +
           (t.terakhir && window.waktuRelatif ? (". Terakhir " + waktuRelatif(t.terakhir)) : "") +
           ". Ini BUKAN kabel — busurnya menyusuri jalur tetap yang harus " +
           "dilewati paketnya.";
  }

  function mati(s) { return s.tipe === "perangkat" && s.data.status === "down"; }

  /* Map icons are drawn here instead of using `ikonDevice()` from ikon.js: that function bakes the status color into attributes at creation (stale after in-place updates), and its icons are designed for 74px dashboard cards. These use `currentColor`, so the status CSS class on the card colors them with no JavaScript. */
  var BENTUK_IKON = {
    router:
      '<rect x="1.5" y="11" width="17" height="7.5" rx="1.6"/>' +
      '<path d="M5 15h1.6M8.2 15h1.6M11.4 15h1.6"/>' +
      '<path d="M10 8.5V3"/><path d="M6.5 5.5 10 2l3.5 3.5"/>',
    switch:
      '<rect x="1.5" y="6.5" width="17" height="9" rx="1.6"/>' +
      '<path d="M4.5 10v2.5M7.5 10v2.5M10.5 10v2.5M13.5 10v2.5"/>',
    server:
      '<rect x="3.5" y="1.8" width="13" height="5" rx="1.3"/>' +
      '<rect x="3.5" y="8.5" width="13" height="5" rx="1.3"/>' +
      '<rect x="3.5" y="15.2" width="13" height="3.4" rx="1.3"/>' +
      '<path d="M6 4.3h.01M6 11h.01M6 16.9h.01"/>',
    laptop:
      '<rect x="3" y="4" width="14" height="9" rx="1.4"/>' +
      '<path d="M1.5 16h17"/>',
    vm:
      '<rect x="2.5" y="3" width="15" height="11" rx="1.6"/>' +
      '<path d="M7 17h6M10 14v3"/>',
    tanya:
      '<circle cx="10" cy="10" r="7.5"/>' +
      '<path d="M8 8a2 2 0 1 1 2.6 1.9c-.5.2-.6.6-.6 1.1v.4"/>' +
      '<path d="M10 14.4h.01"/>'
  };

  function ikonPeta(jenis, x, y) {
    var g = elSvg("g", {
      class: "topo-ikon",
      transform: "translate(" + x + "," + y + ") scale(1)"
    });
    g.innerHTML = BENTUK_IKON[jenis] || BENTUK_IKON.tanya;
    return g;
  }

  function gambarSimpul(s) {
    var g = elSvg("g", {
      transform: "translate(" + s.x + "," + s.y + ")",
      class: "topo-simpul" + (s.tipe === "luar" ? " luar" : ""),
      tabindex: "0"
    });

    g.appendChild(elSvg("rect", {
      x: -LEBAR_KARTU / 2, y: -TINGGI_KARTU / 2, rx: 9,
      width: LEBAR_KARTU, height: TINGGI_KARTU, class: "topo-kartu"
    }));
    // Status stripe on the left edge. Color is always paired with a shape and a word, since red-green color blindness is common.
    g.appendChild(elSvg("rect", {
      x: -LEBAR_KARTU / 2, y: -TINGGI_KARTU / 2, width: 4, height: TINGGI_KARTU,
      class: "topo-pita"
    }));

    if (s.tipe === "perangkat") {
      g.appendChild(ikonPeta(jenisIkon(bentukUntukIkon(s.data)),
                             -LEBAR_KARTU / 2 + 13, -10));
    } else {
      // External nodes get no device icon: only the address is known, not what the device is.
      g.appendChild(elSvg("circle", { cx: -LEBAR_KARTU / 2 + 23, cy: 0, r: 5,
                                      class: "topo-titik-luar" }));
    }

    var nama = elSvg("text", { x: -LEBAR_KARTU / 2 + 42, y: -3, class: "topo-nama" });
    nama.textContent = potong(s.nama, 17);
    g.appendChild(nama);

    var sub = elSvg("text", { x: -LEBAR_KARTU / 2 + 42, y: 11, class: "topo-sub" });
    sub.textContent = s.tipe === "perangkat" ? (s.data.ip || "tanpa alamat") : "tak terdaftar";
    g.appendChild(sub);

    s.el = g;
    perbaruiSimpul(s);
    pasangTarik(g, s);
    lapisSimpul.appendChild(g);
  }

  function potong(t, n) {
    t = String(t || "");
    return t.length > n ? t.slice(0, n - 1) + "…" : t;
  }

  function perbaruiSimpul(s) {
    if (!s.el) return;
    var st = s.tipe === "perangkat" ? s.data.status : "luar";
    s.el.setAttribute("class", "topo-simpul st-" + st + (s.tipe === "luar" ? " luar" : ""));
    s.el.setAttribute("data-petunjuk", s.tipe === "perangkat"
      ? (s.data.nama + " (" + (s.data.ip || "alamat tidak diketahui") + ") — " +
         TEKS_STATUS[s.data.status] + ". Lokasi: " + s.lokasi +
         ". Seret untuk memindahkan.")
      : (s.data.ip + " — bukan perangkat yang terdaftar di NSM" +
         (s.data.luar_jaringan ? ", di luar jaringan lab" : "")));
  }

  /* Changes that do not alter the layout (status, bytes, connection counts). No element may be created or removed here, or dragged positions would be lost. */
  function perbaruiDiTempat(b) {
    Object.keys(b.simpul).forEach(function (k) {
      var lama = S.simpul[k];
      if (!lama) return;
      lama.data = b.simpul[k].data;
      perbaruiSimpul(lama);
    });
    var petaTrafik = {};
    b.trafik.forEach(function (t) { petaTrafik[t.a + "|" + t.b] = t; });
    S.trafik.forEach(function (t) {
      var baru = petaTrafik[t.a + "|" + t.b];
      if (!baru || !t.el) return;
      t.byte = baru.byte; t.koneksi = baru.koneksi;
      t.pintu = baru.pintu; t.terakhir = baru.terakhir;
      t.el.setAttribute("stroke-width", tebalGaris(t.byte).toFixed(2));
      t.el.setAttribute("data-petunjuk", ketTrafik(t, S.simpul[t.a], S.simpul[t.b]));
    });
    S.kabel.forEach(function (t) {
      if (!t.el) return;
      t.el.classList.toggle("ujung-mati", mati(S.simpul[t.a]) || mati(S.simpul[t.b]));
    });
  }

  // =========================================================================
  // 5. INTERAKSI: seret node, geser latar, perbesar
  // =========================================================================

  /* Mouse coordinates to drawing coordinates, via the SVG's own matrix rather than element width over viewBox width, which breaks on scroll or browser zoom. */
  function keKoordinatDunia(ev) {
    var p = svg.createSVGPoint();
    p.x = ev.clientX; p.y = ev.clientY;
    var m = dunia.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    return p.matrixTransform(m.inverse());
  }

  function pasangTarik(g, s) {
    var awal = null;
    g.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0) return;
      ev.stopPropagation();
      var t = keKoordinatDunia(ev);
      awal = { dx: t.x - s.x, dy: t.y - s.y, geser: false };
      // `setPointerCapture` throws for an inactive pointer; it is caught so the rest of the drag setup still runs.
      try { g.setPointerCapture(ev.pointerId); } catch (e) {}
      g.classList.add("sedang-ditarik");
    });
    g.addEventListener("pointermove", function (ev) {
      if (!awal) return;
      var t = keKoordinatDunia(ev);
      s.x = t.x - awal.dx; s.y = t.y - awal.dy;
      awal.geser = true;
      S.disentuh = true;
      g.setAttribute("transform", "translate(" + s.x + "," + s.y + ")");
      perbaruiGarisSekitar(s);
    });
    function selesai(ev) {
      if (!awal) return;
      if (awal.geser) {
        S.posisi[s.kunci] = { x: Math.round(s.x), y: Math.round(s.y) };
        simpanPosisi();
        tandaiAdaSimpanan();
      }
      awal = null;
      g.classList.remove("sedang-ditarik");
      try {
        if (ev && ev.pointerId !== undefined && g.hasPointerCapture(ev.pointerId)) {
          g.releasePointerCapture(ev.pointerId);
        }
      } catch (e) {}
    }
    g.addEventListener("pointerup", selesai);
    g.addEventListener("pointercancel", selesai);

    // Keyboard support: arrow keys move 12 pixels.
    g.addEventListener("keydown", function (ev) {
      var d = { ArrowLeft: [-12, 0], ArrowRight: [12, 0],
                ArrowUp: [0, -12], ArrowDown: [0, 12] }[ev.key];
      if (!d) return;
      ev.preventDefault();
      s.x += d[0]; s.y += d[1];
      g.setAttribute("transform", "translate(" + s.x + "," + s.y + ")");
      perbaruiGarisSekitar(s);
      S.posisi[s.kunci] = { x: Math.round(s.x), y: Math.round(s.y) };
      simpanPosisi();
      tandaiAdaSimpanan();
    });
  }

  function perbaruiGarisSekitar(s) {
    S.kabel.forEach(function (t) {
      if (t.el && (t.a === s.kunci || t.b === s.kunci)) {
        t.el.setAttribute("d",
          jalurKabel(S.simpul[t.a], S.simpul[t.b], t.geser || 0));
      }
    });
    // Conversations passing through this node also move, not only those ending at it.
    S.trafik.forEach(function (t) {
      if (!t.el) return;
      var kena = t.a === s.kunci || t.b === s.kunci ||
                 (t.jalan && t.jalan.indexOf(s.kunci) >= 0);
      if (kena) t.el.setAttribute("d", jalurTrafik(t));
    });
  }

  function terapkanPandangan() {
    dunia.setAttribute("transform",
      "translate(" + S.geserX + "," + S.geserY + ") scale(" + S.skala + ")");
  }

  function pasangGeserLatar() {
    var awal = null;
    svg.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0) return;
      awal = { x: ev.clientX, y: ev.clientY, gx: S.geserX, gy: S.geserY };
      svg.classList.add("sedang-digeser");
      try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
    });
    svg.addEventListener("pointermove", function (ev) {
      if (!awal) return;
      // Screen movement is converted to drawing units using the viewBox-to-real-width ratio, not the content width.
      var r = svg.getBoundingClientRect();
      var vb = svg.viewBox.baseVal;
      var f = (vb && vb.width ? vb.width : r.width) / (r.width || 1);
      S.geserX = awal.gx + (ev.clientX - awal.x) * f;
      S.geserY = awal.gy + (ev.clientY - awal.y) * f;
      S.disentuh = true;
      terapkanPandangan();
    });
    function lepas(ev) {
      awal = null;
      svg.classList.remove("sedang-digeser");
      try {
        if (ev && ev.pointerId !== undefined && svg.hasPointerCapture(ev.pointerId)) {
          svg.releasePointerCapture(ev.pointerId);
        }
      } catch (e) {}
    }
    svg.addEventListener("pointerup", lepas);
    svg.addEventListener("pointercancel", lepas);

    svg.addEventListener("wheel", function (ev) {
      // Without Ctrl the mouse wheel still scrolls the page.
      if (!ev.ctrlKey) return;
      ev.preventDefault();
      zoomKe(S.skala * (ev.deltaY < 0 ? 1.12 : 1 / 1.12));
    }, { passive: false });
  }

  function zoomKe(nilai) {
    S.skala = Math.max(0.45, Math.min(2.4, nilai));
    S.disentuh = true;
    terapkanPandangan();
  }

  function terapkanTrafikTampil() {
    if (lapisTrafik) lapisTrafik.style.display = S.tampilTrafik ? "" : "none";
    var kotak = document.getElementById("topo-saklar-trafik");
    if (kotak) kotak.checked = S.tampilTrafik;
  }

  function tandaiAdaSimpanan() {
    var b = document.getElementById("topo-atur-ulang");
    if (b) b.hidden = !Object.keys(S.posisi).length;
  }

  function pasangTombol() {
    var ulang = document.getElementById("topo-atur-ulang");
    if (ulang) {
      ulang.addEventListener("click", function () {
        S.posisi = {};
        simpanPosisi();
        S.pernahDipaskan = false;
        S.disentuh = false;
        tataLetak();
        bangun();
        tandaiAdaSimpanan();
      });
    }
    var saklar = document.getElementById("topo-saklar-trafik");
    if (saklar) {
      saklar.addEventListener("change", function () {
        S.tampilTrafik = saklar.checked;
        localStorage.setItem(KUNCI_TRAFIK, S.tampilTrafik ? "1" : "0");
        terapkanTrafikTampil();
      });
    }
    var masuk = document.getElementById("topo-zoom-masuk");
    if (masuk) masuk.addEventListener("click", function () { zoomKe(S.skala * 1.2); });
    var keluar = document.getElementById("topo-zoom-keluar");
    if (keluar) keluar.addEventListener("click", function () { zoomKe(S.skala / 1.2); });
    var pas = document.getElementById("topo-zoom-pas");
    if (pas) pas.addEventListener("click", function () {
      S.disentuh = false;
      paskan(pasangViewBox());
      terapkanPandangan();
    });
    tandaiAdaSimpanan();
  }


  function tandaiStatus(teks, kelas) {
    if (!statusEl) return;
    statusEl.textContent = teks;
    statusEl.className = "topologi-status" + (kelas ? " " + kelas : "");
  }

  function mulaiCadanganPolling() {
    if (timerCadangan) return;
    tandaiStatus("WebSocket tidak tersedia — memeriksa tiap 5 detik", "cadangan");
    function tarik() {
      ambilJson("/api/topologi").then(terima).catch(function () {});
    }
    tarik();
    timerCadangan = setInterval(tarik, 5000);
  }

  function hentikanCadanganPolling() {
    if (timerCadangan) { clearInterval(timerCadangan); timerCadangan = null; }
  }

  function sambungWs() {
    if (!("WebSocket" in window)) { mulaiCadanganPolling(); return; }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var soket;
    try {
      soket = new WebSocket(proto + "//" + location.host + "/ws/topologi");
    } catch (e) { mulaiCadanganPolling(); return; }

    soket.onopen = function () {
      gagalBerturut = 0;
      tandaiStatus("Hidup lewat WebSocket", "hidup");
      hentikanCadanganPolling();
    };
    soket.onmessage = function (ev) {
      try { terima(JSON.parse(ev.data)); } catch (e) {}
    };
    soket.onclose = function () {
      gagalBerturut++;
      tandaiStatus("Terputus, menyambung ulang…", "terputus");
      if (gagalBerturut >= GAGAL_BERTURUT_MAKS) mulaiCadanganPolling();
      setTimeout(sambungWs, Math.min(30000, 1000 * Math.pow(2, gagalBerturut)));
    };
    soket.onerror = function () { soket.close(); };
  }

  function pasang() {
    svg = document.getElementById("topologi-svg");
    statusEl = document.getElementById("topologi-status");
    kosongEl = document.getElementById("topologi-kosong");
    wrap = document.getElementById("topologi-bingkai");
    if (!svg) return;

    dunia = elSvg("g", { class: "topo-dunia" });
    svg.appendChild(dunia);

    pasangGeserLatar();
    pasangTombol();

    // Frame width changed: update the viewBox but keep the user's zoom and pan.
    var tunda = null;
    window.addEventListener("resize", function () {
      if (tunda) clearTimeout(tunda);
      tunda = setTimeout(segarkanUkuran, 150);
    });

    /* The map frame height stretches with the right column (see align-items:stretch in dashboard.html), which can change without a window resize. ResizeObserver watches the SVG element's own size, whatever the cause. */
    if (window.ResizeObserver) {
      new ResizeObserver(function () { segarkanUkuran(); }).observe(svg);
    }

    ambilJson("/api/topologi").then(terima).catch(function () {});
    sambungWs();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pasang);
  } else {
    pasang();
  }
})();
