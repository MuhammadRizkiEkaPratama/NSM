/*
 * Long explanations hidden behind a small icon button at the corner of an element. Unlike `petunjuk.js` (hover, glance-level hints), this uses a real button that is clicked, so it works on touch screens, with Tab, and with screen readers.
 *
 * The template needs a `.kepala` header holding the title, plus a hidden `.jelas-isi` panel; `jelas.pasang()` adds the `.jelas-tombol` button. Or call `jelas.pasang(wadahKepala, teks)` from code that builds the card.
 */
(function (global) {
  "use strict";

  var nomor = 0;

  /*
   * Attach the explanation icon to a card.
   *
   * `kepala`  element where the icon goes (corner of the title row)
   * `teks`    full explanation
   * `induk`   element that holds the panel (default: parent of `kepala`)
   *
   * Returns the panel so callers can add more content.
   */
  function pasang(kepala, teks, induk) {
    if (!kepala || !teks) return null;
    induk = induk || kepala.parentNode;
    nomor += 1;
    var id = "jelas-" + nomor;

    var tombol = document.createElement("button");
    tombol.type = "button";
    tombol.className = "jelas-tombol"; // Without type="button" it would submit the form.
    tombol.setAttribute("aria-expanded", "false");
    tombol.setAttribute("aria-controls", id);
    // The name says WHAT is explained, since screen readers read buttons without context.
    var nama = kepala.querySelector(".nama");
    tombol.setAttribute("aria-label",
      "Penjelasan" + (nama ? " " + nama.textContent : ""));
    tombol.textContent = "?";
    kepala.appendChild(tombol);

    var panel = document.createElement("div");
    panel.className = "jelas-isi";
    panel.id = id;
    panel.hidden = true;
    panel.textContent = teks; // textContent, not innerHTML: the text may come from the server.
    induk.appendChild(panel);

    tombol.addEventListener("click", function (ev) {
      // The click stops here: if the icon sits on a collapsible heading (`data-lipat`), one click would both open the explanation and collapse the section.
      ev.stopPropagation();
      var buka = panel.hidden;
      panel.hidden = !buka;
      tombol.setAttribute("aria-expanded", buka ? "true" : "false");
      tombol.classList.toggle("terbuka", buka);
    });

    return panel;
  }

  /* Explanations written directly in templates are collapsed automatically. Conditions: (1) directly after an <h3>/<h4>; (2) the heading has no `data-lipat` (`lipatan.js` already handles those); (3) the content is fixed text, not an empty id-bearing container filled by JavaScript, which would hide the page's answer. */
  function lipatKet(wadah) {
    var daftar = wadah.querySelectorAll(".ket");
    for (var i = 0; i < daftar.length; i++) {
      var ket = daftar[i];
      if (ket.dataset.siap || ket.id) continue;
      var judul = ket.previousElementSibling;
      if (!judul) continue;
      if (judul.tagName !== "H3" && judul.tagName !== "H4") continue;
      if (judul.hasAttribute("data-lipat")) continue;
      if (!ket.textContent.trim()) continue;

      ket.dataset.siap = "1";
      judul.classList.add("kepala", "judul-berikon");
      var isi = ket.cloneNode(true);
      isi.className = "jelas-isi";
      isi.removeAttribute("data-siap");
      var tombol = pasangKosong(judul, isi, ket);
      if (!tombol) ket.dataset.siap = "";
    }
  }

  /* Like `pasang()`, but the panel is already an element; used when the explanation has links or <b> that would be lost as plain text. */
  function pasangKosong(kepala, panel, gantikan) {
    nomor += 1;
    var id = "jelas-" + nomor;
    var tombol = document.createElement("button");
    tombol.type = "button";
    tombol.className = "jelas-tombol";
    tombol.setAttribute("aria-expanded", "false");
    tombol.setAttribute("aria-controls", id);
    tombol.setAttribute("aria-label",
      "Penjelasan " + (kepala.textContent || "").trim());
    tombol.textContent = "?";
    kepala.appendChild(tombol);

    panel.id = id;
    panel.hidden = true;
    gantikan.parentNode.replaceChild(panel, gantikan);

    tombol.addEventListener("click", function (ev) {
      ev.stopPropagation(); // see pasang() for the reason
      var buka = panel.hidden;
      panel.hidden = !buka;
      tombol.setAttribute("aria-expanded", buka ? "true" : "false");
      tombol.classList.toggle("terbuka", buka);
    });
    return tombol;
  }

  /* For markup that already contains `.jelas-isi` in the template. Runs once on page ready. */
  function terapkan(wadah) {
    wadah = wadah || document;
    var daftar = wadah.querySelectorAll(".jelas-isi[data-untuk]");
    for (var i = 0; i < daftar.length; i++) {
      var panel = daftar[i];
      var kepala = wadah.querySelector(panel.getAttribute("data-untuk"));
      if (!kepala || panel.dataset.siap) continue;
      panel.dataset.siap = "1";
      var teks = panel.textContent;
      panel.textContent = "";
      panel.remove();
      pasang(kepala, teks, kepala.parentNode);
    }
    lipatKet(wadah);
  }

  global.jelas = { pasang: pasang, terapkan: terapkan, lipatKet: lipatKet };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { terapkan(); });
  } else {
    terapkan();
  }
})(window);
