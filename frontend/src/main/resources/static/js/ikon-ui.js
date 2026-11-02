/* NSM interface icons (controls: pause, resume, download, copy, close). Device icons are in ikon.js. Drawn as SVG instead of emoji, which vary across systems and cannot be colored. All icons use a 24x24 box, stroke width 2, round caps, and `currentColor`. */

var IKON_UI_JALUR = {
  // Kontrol pemantauan
  jeda:      ["M10 5v14", "M16 5v14"],
  lanjut:    ["M7 4.5l12 7.5-12 7.5z"],

  unduh:     ["M12 3v12", "M7 11l5 5 5-5", "M4 20h16"],
  salin:     ["M9 9h10v10H9z", "M5 15V5h10"],
  segarkan:  ["M20 12a8 8 0 1 1-2.6-5.9", "M20 4v4h-4"],

  kembali:   ["M15 5l-7 7 7 7"],
  tutup:     ["M6 6l12 12", "M18 6L6 18"],
  cari:      ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-4-4"],

  // Penanda keadaan
  ceklis:    ["M5 13l4 4L19 7"],
  peringatan:["M12 4l9 16H3z", "M12 10v4", "M12 17.5v.5"],
  info:      ["M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z", "M12 11v5", "M12 7.5v.5"],
  jam:       ["M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z", "M12 8v4.5l3 1.8"],
  lonceng:   ["M6 16V11a6 6 0 1 1 12 0v5l2 3H4z", "M10 22h4"]
};

/* Return a new <svg> element. Always builds elements (not HTML strings) so the app has no innerHTML path. */
function ikonUI(nama, ukuran) {
  var NS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(NS, "svg");
  var s = ukuran || 16;
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", s);
  svg.setAttribute("height", s);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  // Icons always accompany text or a title on their button, so they are decorative for screen readers; hiding them avoids double announcements.
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  var jalur = IKON_UI_JALUR[nama] || [];
  jalur.forEach(function (d) {
    var p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  });
  return svg;
}

/* Icon-only button. The label text is required: a nameless button is unusable for screen reader users. */
function tombolIkon(nama, penjelasan, kelas) {
  var b = document.createElement("button");
  b.className = kelas || "";
  b.setAttribute("title", penjelasan);
  b.setAttribute("aria-label", penjelasan);
  b.appendChild(ikonUI(nama, 15));
  return b;
}
