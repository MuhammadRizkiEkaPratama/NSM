/* Device icons and status animation, pure SVG and CSS with no external files (keeps CSP at 'self'). Colors follow device status directly. */

// Style: 1 = line, 2 = soft fill, 3 = layered bold,
// 4 = isometric 3D, 5 = isometric neon, 6 = neon halo, 7 = custom image
var GAYA = 5;

/* Color follows the device state, not set per icon. */
function warnaStatus(hidup) {
  if (hidup === true) return { utama: "#4ade80", muda: "#4ade8033", garis: "#4ade80" };
  if (hidup === false) return { utama: "#f87171", muda: "#f8717133", garis: "#f87171" };
  return { utama: "#9ca3af", muda: "#9ca3af22", garis: "#9ca3af" };
}

function jenisIkon(d) {
  var tipe = (d.device_type || "").toLowerCase();
  var plat = (d.platform || "").toLowerCase();
  var lokasi = (d.location || "").toLowerCase();

  if (plat === "cisco_ios" || tipe === "router") return "router";
  if (tipe === "switch") return "switch";
  if (lokasi.indexOf("virtualbox") >= 0 || lokasi.indexOf("gns3") >= 0) return "vm";
  if (tipe === "server") return "server";
  if (tipe === "pc" || tipe === "laptop") return "laptop";
  return "tanya";
}

var NAMA_JENIS = {
  server: "Server", router: "Router", switch: "Switch",
  laptop: "Laptop / PC", vm: "Mesin Virtual", tanya: "Tidak dikenal",
};

// Base shape per device kind, all drawn on a 48x48 canvas.
function bentuk(jenis, w, isi, tebal) {
  var g = w.garis, m = isi ? w.muda : "none";
  var t = tebal || 2;

  if (jenis === "server") {
    return (
      '<rect x="10" y="7"  width="28" height="10" rx="2" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<rect x="10" y="19" width="28" height="10" rx="2" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<rect x="10" y="31" width="28" height="10" rx="2" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<circle cx="15" cy="12" r="1.6" fill="' + g + '"/>' +
      '<circle cx="15" cy="24" r="1.6" fill="' + g + '"/>' +
      '<circle cx="15" cy="36" r="1.6" fill="' + g + '"/>' +
      '<line x1="21" y1="12" x2="33" y2="12" stroke="' + g + '" stroke-width="1.4" opacity=".55"/>' +
      '<line x1="21" y1="24" x2="33" y2="24" stroke="' + g + '" stroke-width="1.4" opacity=".55"/>' +
      '<line x1="21" y1="36" x2="33" y2="36" stroke="' + g + '" stroke-width="1.4" opacity=".55"/>'
    );
  }
  if (jenis === "router") {
    return (
      '<rect x="7" y="26" width="34" height="14" rx="3" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<circle cx="14" cy="33" r="1.7" fill="' + g + '"/>' +
      '<circle cx="20" cy="33" r="1.7" fill="' + g + '" opacity=".6"/>' +
      '<circle cx="26" cy="33" r="1.7" fill="' + g + '" opacity=".35"/>' +
      '<line x1="16" y1="26" x2="12" y2="14" stroke="' + g + '" stroke-width="' + t + '" stroke-linecap="round"/>' +
      '<line x1="32" y1="26" x2="36" y2="14" stroke="' + g + '" stroke-width="' + t + '" stroke-linecap="round"/>' +
      '<path d="M20 16 A 8 8 0 0 1 28 16" fill="none" stroke="' + g + '" stroke-width="1.6" opacity=".6"/>' +
      '<path d="M17 11 A 13 13 0 0 1 31 11" fill="none" stroke="' + g + '" stroke-width="1.6" opacity=".3"/>'
    );
  }
  if (jenis === "switch") {
    return (
      '<rect x="6" y="20" width="36" height="16" rx="3" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<rect x="11" y="25" width="4" height="6" rx="1" fill="' + g + '" opacity=".8"/>' +
      '<rect x="18" y="25" width="4" height="6" rx="1" fill="' + g + '" opacity=".65"/>' +
      '<rect x="25" y="25" width="4" height="6" rx="1" fill="' + g + '" opacity=".5"/>' +
      '<rect x="32" y="25" width="4" height="6" rx="1" fill="' + g + '" opacity=".35"/>' +
      '<path d="M16 20 L16 13 L32 13" fill="none" stroke="' + g + '" stroke-width="1.6" opacity=".55"/>' +
      '<path d="M32 20 L32 9 L20 9"  fill="none" stroke="' + g + '" stroke-width="1.6" opacity=".35"/>'
    );
  }
  if (jenis === "laptop") {
    return (
      '<rect x="11" y="11" width="26" height="18" rx="2" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<path d="M6 33 L42 33 L38 29 L10 29 Z" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '" stroke-linejoin="round"/>' +
      '<line x1="20" y1="36" x2="28" y2="36" stroke="' + g + '" stroke-width="1.6" opacity=".5"/>' +
      '<line x1="16" y1="17" x2="32" y2="17" stroke="' + g + '" stroke-width="1.4" opacity=".45"/>' +
      '<line x1="16" y1="21" x2="27" y2="21" stroke="' + g + '" stroke-width="1.4" opacity=".3"/>'
    );
  }
  if (jenis === "vm") {
    return (
      // outer box = physical host, inner box = virtual machine inside it
      '<rect x="6" y="9" width="36" height="30" rx="3" fill="none" stroke="' + g + '" stroke-width="' + t + '" opacity=".55" stroke-dasharray="4 3"/>' +
      '<rect x="13" y="16" width="22" height="16" rx="2" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
      '<circle cx="18" cy="21" r="1.5" fill="' + g + '"/>' +
      '<line x1="23" y1="21" x2="31" y2="21" stroke="' + g + '" stroke-width="1.4" opacity=".55"/>' +
      '<line x1="18" y1="26" x2="31" y2="26" stroke="' + g + '" stroke-width="1.4" opacity=".35"/>'
    );
  }
  return (
    '<circle cx="24" cy="24" r="15" fill="' + m + '" stroke="' + g + '" stroke-width="' + t + '"/>' +
    '<text x="24" y="30" text-anchor="middle" font-size="17" fill="' + g + '">?</text>'
  );
}

// Isometric style: each point (x, y, z) is projected with
//     X = (x - y) * cos(30deg)
//     Y = (x + y) * sin(30deg) - z
// No perspective. Depth comes from shading: top lightest, left medium, right darkest.
var COS30 = 0.8660254;
var nomorUnik = 0;

function proyeksi(x, y, z) {
  return [(x - y) * COS30, (x + y) * 0.5 - z];
}

/* Darken a color, used for block edges so the faces stay distinguishable at small sizes. */
function gelap(hex, faktor) {
  var r = parseInt(hex.substr(1, 2), 16);
  var g = parseInt(hex.substr(3, 2), 16);
  var b = parseInt(hex.substr(5, 2), 16);
  function dua(v) {
    var s = Math.max(0, Math.round(v * faktor)).toString(16);
    return s.length < 2 ? "0" + s : s;
  }
  return "#" + dua(r) + dua(g) + dua(b);
}

function poligon(titik, warna, alpha, garis) {
  var d = titik.map(function (p, i) {
    var s = proyeksi(p[0], p[1], p[2]);
    return (i === 0 ? "M" : "L") + s[0].toFixed(2) + " " + s[1].toFixed(2);
  }).join(" ") + " Z";
  return '<path d="' + d + '" fill="' + warna + '" fill-opacity="' + alpha +
         '" stroke="' + garis + '" stroke-width="1.1" stroke-linejoin="round"/>';
}

/* One block: width w (x axis), depth d (y axis), height h (z axis), base centered at (0,0) and standing from z0. */
function balok(w, d, h, warna, z0) {
  var a = -w / 2, b = w / 2, c = -d / 2, e = d / 2;
  var z1 = z0 || 0, z2 = z1 + h;
  var tepi = gelap(warna, 0.42);
  return (
    poligon([[b, c, z1], [b, e, z1], [b, e, z2], [b, c, z2]], warna, 0.42, tepi) +
    // sisi kiri (y = e), sedang
    poligon([[a, e, z1], [b, e, z1], [b, e, z2], [a, e, z2]], warna, 0.68, tepi) +
    poligon([[a, c, z2], [b, c, z2], [b, e, z2], [a, e, z2]], warna, 1.0, tepi)
  );
}

function garisIso(p1, p2, warna, tebal, alpha) {
  var s1 = proyeksi(p1[0], p1[1], p1[2]);
  var s2 = proyeksi(p2[0], p2[1], p2[2]);
  return '<line x1="' + s1[0].toFixed(2) + '" y1="' + s1[1].toFixed(2) +
         '" x2="' + s2[0].toFixed(2) + '" y2="' + s2[1].toFixed(2) +
         '" stroke="' + warna + '" stroke-width="' + (tebal || 1) +
         '" stroke-linecap="round" opacity="' + (alpha === undefined ? 1 : alpha) + '"/>';
}

function bentukIso(jenis, w) {
  var g = w.garis;

  if (jenis === "server") {
    var s = "";
    for (var i = 0; i < 3; i++) {
      s += balok(15, 15, 5, g, i * 7);
    }
    for (var j = 0; j < 3; j++) {
      s += '<circle cx="' + proyeksi(-5, 7.5, j * 7 + 2.5)[0].toFixed(2) +
           '" cy="' + proyeksi(-5, 7.5, j * 7 + 2.5)[1].toFixed(2) +
           '" r="1.1" fill="' + g + '"/>';
    }
    return s;
  }
  if (jenis === "router") {
    return balok(19, 19, 4, g) +
      garisIso([-5, -5, 4], [-8, -8, 15], g, 1.6) +
      garisIso([5, 5, 4], [8, 8, 15], g, 1.6) +
      '<circle cx="' + proyeksi(-8, -8, 15)[0].toFixed(2) + '" cy="' +
      proyeksi(-8, -8, 15)[1].toFixed(2) + '" r="1.6" fill="' + g + '"/>' +
      '<circle cx="' + proyeksi(8, 8, 15)[0].toFixed(2) + '" cy="' +
      proyeksi(8, 8, 15)[1].toFixed(2) + '" r="1.6" fill="' + g + '"/>' +
      garisIso([-6, 8, 2], [6, 8, 2], g, 1.2, 0.5);
  }
  if (jenis === "switch") {
    var s2 = balok(24, 11, 4, g);
    for (var p = -9; p <= 9; p += 4.5) {
      s2 += garisIso([p, 5.5, 1], [p, 5.5, 3], g, 1.6, 0.85);
    }
    return s2;
  }
  if (jenis === "laptop") {
    return balok(20, 14, 1.6, g) +
      poligon([[-10, -7, 1.6], [10, -7, 1.6], [10, -7, 14], [-10, -7, 14]], g, 0.8, g) +
      garisIso([-6, -7.1, 5], [6, -7.1, 5], g, 1, 0.45) +
      garisIso([-6, -7.1, 8], [3, -7.1, 8], g, 1, 0.3) +
      garisIso([-4, 6, 1.8], [4, 6, 1.8], g, 1.2, 0.5);
  }
  if (jenis === "vm") {
    var luar = "";
    var a = -11, b = 11;
    [[a, a], [b, a], [b, b], [a, b]].forEach(function (t, i, arr) {
      var n = arr[(i + 1) % 4];
      luar += garisIso([t[0], t[1], 0], [n[0], n[1], 0], g, 1, 0.4);
      luar += garisIso([t[0], t[1], 16], [n[0], n[1], 16], g, 1, 0.4);
      luar += garisIso([t[0], t[1], 0], [t[0], t[1], 16], g, 1, 0.25);
    });
    return luar + balok(12, 12, 9, g, 2);
  }
  return balok(13, 13, 13, g) +
    '<text x="0" y="-4" text-anchor="middle" font-size="11" fill="' + g + '">?</text>';
}

function ikonDevice(jenis, hidup, ukuran, gaya) {
  var w = warnaStatus(hidup);
  var s = gaya || GAYA;
  var px = ukuran || 34;
  var kelas = "ikon gaya" + s +
    (hidup === true ? " hidup" : hidup === false ? " mati" : " tanya");

  var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 48 48");
  svg.setAttribute("width", px);
  svg.setAttribute("height", px);

  if (s === 7) {
    var kotak = document.createElement("span");
    kotak.className = "ikon-gambar" +
      (hidup === true ? " hidup" : hidup === false ? " mati" : " tanya");
    kotak.style.width = px + "px";
    kotak.style.height = px + "px";

    var gambar = document.createElement("img");
    gambar.src = "/ikon/" + jenis + ".png";
    gambar.alt = NAMA_JENIS[jenis] || jenis;
    gambar.width = px;
    gambar.height = px;
    // If the file has not been downloaded, fall back to style 2, which is always available.
    gambar.addEventListener("error", function () {
      var ganti = ikonDevice(jenis, hidup, px, 2);
      if (kotak.parentNode) kotak.parentNode.replaceChild(ganti, kotak);
    });
    kotak.appendChild(gambar);
    return kotak;
  }

  var isi;
  if (s === 6) {
    kelas += " halo";
    var idHalo = "halo" + (++nomorUnik);
    isi =
      '<defs><radialGradient id="' + idHalo + '">' +
      '<stop offset="0%"   stop-color="' + w.garis + '" stop-opacity="0.55"/>' +
      '<stop offset="55%"  stop-color="' + w.garis + '" stop-opacity="0.16"/>' +
      '<stop offset="100%" stop-color="' + w.garis + '" stop-opacity="0"/>' +
      '</radialGradient></defs>' +
      '<circle cx="24" cy="24" r="24" fill="url(#' + idHalo + ')"/>' +
      bentuk(jenis, w, true, 2.2);
  } else if (s === 4 || s === 5) {
    // --- gaya isometrik ---
    kelas += " iso";
    var cahaya = "";
    if (s === 5) {
      // Neon glow uses a gradient, not `feGaussianBlur`: SVG filters are recomputed every frame while the icon floats, a gradient is drawn once.
      var idCahaya = "cahaya" + (++nomorUnik);
      cahaya =
        '<defs><radialGradient id="' + idCahaya + '">' +
        '<stop offset="0%"   stop-color="' + w.garis + '" stop-opacity="0.5"/>' +
        '<stop offset="45%"  stop-color="' + w.garis + '" stop-opacity="0.2"/>' +
        '<stop offset="100%" stop-color="' + w.garis + '" stop-opacity="0"/>' +
        '</radialGradient></defs>' +
        '<circle cx="24" cy="22" r="24" fill="url(#' + idCahaya + ')"/>';
    }
    var bayangan = '<ellipse cx="0" cy="2" rx="13" ry="6.5" fill="' + w.garis +
                   '" opacity="' + (hidup === false ? "0.07" : "0.13") + '"/>';
    isi = cahaya + '<g transform="translate(24,30)">' +
          bayangan + bentukIso(jenis, w) + '</g>';
  } else {
    // --- gaya datar ---
    var latar = "";
    if (s === 2) {
      latar = '<circle cx="24" cy="24" r="22" fill="' + w.muda + '"/>';
    } else if (s === 3) {
      latar = '<rect x="2" y="2" width="44" height="44" rx="11" fill="' + w.muda + '"/>' +
              '<rect x="2" y="2" width="44" height="44" rx="11" fill="none" stroke="' +
              w.garis + '" stroke-width="1.2" opacity=".45"/>';
    }
    isi = latar + bentuk(jenis, w, s !== 1, s === 3 ? 2.6 : 2);
  }

  svg.setAttribute("class", kelas);
  // The SVG content comes only from constants in this file; no user or database text enters it.
  svg.innerHTML = isi;
  return svg;
}

function titikStatus(hidup) {
  var span = document.createElement("span");
  span.className = "titik-status " +
    (hidup === true ? "st-hidup" : hidup === false ? "st-mati" : "st-tanya");
  span.setAttribute("title",
    hidup === true ? "UP" : hidup === false ? "DOWN" : "Belum ada data");
  return span;
}

function _el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  // textContent, not innerHTML: device name and location come from the database.
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

/* "Services on this device" section of the detail card. A device with no registered services is not a problem device, so the empty state must not look like a failed load. */
function bagianLayanan(l, mesinMati) {
  var kotak = _el("div", "layanan-ikon");

  if (!l || !l.total) {
    kotak.appendChild(_el("div", "judul-bagian", "Layanan"));
    kotak.appendChild(_el("div", "kosong-layanan",
      "Tidak ada layanan terdaftar di device ini."));
    return kotak;
  }

  // The title leads with the number of problem services, since people open this card to find the red ones.
  var judul = _el("div", "judul-bagian");
  judul.appendChild(_el("span", null, "Layanan"));
  var ringkas = _el("span", l.bermasalah ? "cap-buruk" : "cap-baik",
    l.bermasalah ? (l.bermasalah + " dari " + l.total + " bermasalah")
                 : (l.sehat + " dari " + l.total + " sehat"));
  judul.appendChild(ringkas);
  kotak.appendChild(judul);

  // If the machine itself does not answer, the FAILED rows below say nothing about the services (ICMP silent but TCP answering usually means a firewall). This line is only shown under that condition.
  if (mesinMati) {
    var adaYangHidup = l.layanan.some(function (s) {
      return s.aktif && s.ok === true;
    });
    kotak.appendChild(_el("div", "catatan-layanan", adaYangHidup
      ? "Ping ke mesin ini tidak menjawab, tetapi ada layanan di bawah yang "
        + "JUSTRU menjawab. Mesin yang menjawab koneksi TCP itu hidup: yang "
        + "kemungkinan besar diblokir ICMP-nya, bukan mesinnya yang mati."
      : "Mesinnya tidak menjawab ping, dan tidak ada satu pun layanannya yang "
        + "menjawab. Semua pemeriksaan di bawah gagal karena tidak terjangkau, "
        + "jadi ini belum tentu berarti layanannya rusak."));
  }

  l.layanan.forEach(function (s) {
    var b = _el("div", "baris-layanan");

    // Four states, not two: "never checked" is distinct from "down", so a newly registered service does not look broken.
    var kelas = !s.aktif ? "svc-jeda"
              : s.ok === true ? "svc-hidup"
              : s.ok === false ? "svc-mati" : "svc-tanya";
    b.appendChild(_el("span", "titik-svc " + kelas));

    var teks = _el("div", "isi-layanan");
    teks.appendChild(_el("div", "nama-svc", s.nama));
    teks.appendChild(_el("div", "alamat-svc",
      (s.jenis || "?").toUpperCase() + " " + s.port));
    b.appendChild(teks);

    var kata = !s.aktif ? "dijeda"
             : s.ok === true ? "OK"
             : s.ok === false ? "GAGAL" : "belum dicek";
    b.appendChild(_el("span", "vonis-svc " + kelas, kata));

    // The reason, if any, comes from Python; JavaScript never builds the explanation for a red service itself.
    if (s.ok === false && s.kategori_teks) {
      b.setAttribute("data-petunjuk", s.kategori_teks);
    }
    kotak.appendChild(b);
  });

  return kotak;
}

/*
 * Short detail card for a device.
 *
 * `sejajarDengan` (optional) is the element that sets the card's width and left edge, so the card stacks over its own device card instead of covering neighbors.
 *
 * `layanan` (optional) is the current service state computed by Python: {total, sehat, bermasalah, dijeda, layanan:[...]}. Ping only proves the machine is up, so this lets the card show services without leaving the page. JavaScript only picks colors from the `ok` value decided by Python.
 */
function kartuIkon(d, jenis, dariEl, sejajarDengan, layanan) {
  var lama = document.querySelector(".kartu-ikon");
  if (lama) lama.remove();

  var kartu = _el("div", "kartu-ikon");
  var atas = _el("div", "atas");
  atas.appendChild(ikonDevice(jenis, d.is_reachable, 46));
  var teks = _el("div");
  teks.appendChild(_el("div", "judul", d.name));
  teks.appendChild(_el("div", "sub",
    (NAMA_JENIS[jenis] || jenis) + " • " + d.ip_address));
  atas.appendChild(teks);
  kartu.appendChild(atas);

  var rinci = _el("div", "rinci");
  function baris(label, nilai, kelas) {
    var b = _el("div");
    b.appendChild(_el("b", null, label + ": "));
    b.appendChild(_el("span", kelas || null, nilai));
    return b;
  }
  rinci.appendChild(baris("Status",
    d.is_reachable === true ? "UP" : d.is_reachable === false ? "DOWN" : "Belum ada data",
    d.is_reachable === true ? "nilai-hidup" : d.is_reachable === false ? "nilai-mati" : null));
  rinci.appendChild(baris("Latency",
    (d.is_reachable && d.response_time_ms !== null && d.response_time_ms !== undefined)
      ? d.response_time_ms + " ms" : "-"));
  rinci.appendChild(baris("Tipe", d.device_type || "-"));
  rinci.appendChild(baris("Platform", d.platform || "belum diisi"));
  rinci.appendChild(baris("Lokasi", d.location || "-"));
  if (d.last_checked) {
    rinci.appendChild(baris("Terakhir cek", d.last_checked.substring(11, 19)));
  }
  kartu.appendChild(rinci);

  // Only drawn when the caller supplies the data; the Report page uses the same card without this section, and an empty section there would read as "no services".
  if (layanan !== undefined && layanan !== null) {
    // Paused devices are not counted as down: `is_reachable` is not updated while paused.
    var mesinMati = d.aktif !== false && d.is_reachable === false;
    kartu.appendChild(bagianLayanan(layanan, mesinMati));
  }

  document.body.appendChild(kartu);

  // The small "Klik untuk rincian device" hint is disabled while the card is open. It is stored as `title` until `js/petunjuk.js` moves it to `data-petunjuk` on first hover, so both attributes are checked.
  var atributPetunjuk = dariEl.hasAttribute("data-petunjuk")
    ? "data-petunjuk" : "title";
  var petunjukAsli = dariEl.getAttribute(atributPetunjuk);
  if (petunjukAsli !== null) {
    dariEl.removeAttribute(atributPetunjuk);
    // Removing the attribute does not close an already visible hint; a pointerover on an element without a hint makes `js/petunjuk.js` close it.
    document.dispatchEvent(new Event("pointerover", { bubbles: true }));
  }

  var r = dariEl.getBoundingClientRect();
  var atasnya = r.bottom + 8;

  if (sejajarDengan) {
    var rk = sejajarDengan.getBoundingClientRect();
    kartu.style.width = Math.max(232, rk.width) + "px";
    kartu.style.left = Math.max(10, Math.min(
      rk.left, window.innerWidth - Math.max(232, rk.width) - 16)) + "px";
  } else {
    var kiri = Math.min(r.left, window.innerWidth - kartu.offsetWidth - 16);
    kartu.style.left = Math.max(10, kiri) + "px";
  }

  if (atasnya + kartu.offsetHeight > window.innerHeight - 10) {
    atasnya = Math.max(10, r.top - kartu.offsetHeight - 8);
  }
  kartu.style.top = atasnya + "px";

  // Both listeners are declared first so each can remove the other when the card closes; otherwise closing with Escape leaves a dangling click listener.
  function tutupKartu() {
    kartu.remove();
    if (petunjukAsli !== null) dariEl.setAttribute(atributPetunjuk, petunjukAsli);
    document.removeEventListener("click", klikDiLuar);
    document.removeEventListener("keydown", tekanEsc);
  }

  function klikDiLuar(e) {
    if (!kartu.contains(e.target)) tutupKartu();
  }

  function tekanEsc(e) {
    if (e.key === "Escape") tutupKartu();
  }

  // Deferred one tick so the click that opens the card does not immediately close it.
  setTimeout(function () {
    document.addEventListener("click", klikDiLuar);
    document.addEventListener("keydown", tekanEsc);
  }, 0);
  return kartu;
}

function selDevice(d) {
  var jenis = jenisIkon(d);
  var bungkus = document.createElement("span");
  bungkus.className = "sel-device";

  var kotakIkon = _el("span", "bungkus-ikon");
  kotakIkon.setAttribute("title", "Klik untuk detail singkat");
  kotakIkon.appendChild(ikonDevice(jenis, d.is_reachable, 32));
  kotakIkon.addEventListener("click", function (e) {
    e.stopPropagation();
    kartuIkon(d, jenis, kotakIkon);
  });

  var teks = _el("div");
  teks.appendChild(_el("div", "nama", d.name));
  teks.appendChild(_el("div", "jenis", NAMA_JENIS[jenis] || jenis));

  bungkus.appendChild(kotakIkon);
  bungkus.appendChild(teks);
  return bungkus;
}
