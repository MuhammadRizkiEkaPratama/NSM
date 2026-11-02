/*
 * Diagnosis panel: what is broken, who is affected, and the first step.
 *
 * Findings are shown as compact cards side by side, each with a severity tag (SEBAB / TERDAMPAK / PERINGATAN), the name and device, and one sentence. Only the steps and evidence are collapsed. Only one card is open at a time, and the cards widen to a full row when open so shell commands can be copied.
 */
(function () {
  "use strict";

  var kotak = document.getElementById("diagnosis");
  if (!kotak) return;

  // Built with the DOM API, not innerHTML: `bukti` contains text from service configuration and `arti` may contain error messages from devices.
  function el(tag, kelas, teks) {
    var n = document.createElement(tag);
    if (kelas) n.className = kelas;
    if (teks !== undefined && teks !== null) n.textContent = teks;
    return n;
  }

  // Three severity levels: the third means "will break if left alone", the only one that can be acted on before anything is disrupted.
  var TANDA = { sebab: "SEBAB", akibat: "TERDAMPAK", peringatan: "PERINGATAN" };

  function tautanAksi(x) {
    var baris = el("div", "diag-aksi");
    if (x.device_id) {
      var a = el("a", "diag-tombol", "Riwayat perangkat");
      a.href = "/report/device/" + x.device_id;
      baris.appendChild(a);
      var b = el("a", "diag-tombol", "Data SSH");
      b.href = "/device/" + x.device_id + "/ssh";
      baris.appendChild(b);
    }
    if (x.layanan_id) {
      var c = el("a", "diag-tombol", "Halaman layanan");
      c.href = "/services";
      baris.appendChild(c);
    }
    return baris.childNodes.length ? baris : null;
  }

  function kartu(x, nomor) {
    var sebab = x.vonis === "sebab";
    var n = el("div", "diag-kartu diag-" + x.vonis);

    /* The header is a button so keyboard and screen readers work (`aria-expanded` announces the state). */
    var kepala = el("button", "diag-kepala");
    kepala.type = "button";
    kepala.setAttribute("aria-expanded", "false");
    kepala.setAttribute("aria-controls", "diag-isi-" + nomor);
    kepala.appendChild(el("span", "diag-tanda", TANDA[x.vonis] || "?"));
    var teks = el("span", "diag-kepala-teks");
    teks.appendChild(el("b", "diag-nama", x.nama));
    teks.appendChild(el("span", "diag-device", x.device));
    kepala.appendChild(teks);
    kepala.appendChild(el("span", "diag-panah-buka", "▾"));
    n.appendChild(kepala);

    // One sentence, always visible, also when the card is closed.
    n.appendChild(el("div", "diag-arti", x.arti));

    var isi = el("div", "diag-isi");
    isi.id = "diag-isi-" + nomor;
    isi.hidden = true;

    kepala.addEventListener("click", function () {
      var bukaSekarang = isi.hidden;
      kotak.querySelectorAll(".diag-kartu.terbuka").forEach(function (lain) {
        lain.classList.remove("terbuka");
        var i = lain.querySelector(".diag-isi");
        if (i) i.hidden = true;
        var t = lain.querySelector(".diag-kepala");
        if (t) t.setAttribute("aria-expanded", "false");
      });
      isi.hidden = !bukaSekarang;
      n.classList.toggle("terbuka", bukaSekarang);
      kepala.setAttribute("aria-expanded", bukaSekarang ? "true" : "false");
      terbukaKunci = bukaSekarang ? kunciKartu(x) : null;
    });


    // If this is a consequence, name the cause explicitly rather than "see above"; readers may arrive by direct link.
    if (!sebab && x.karena) {
      var asal = x.karena_layanan || x.karena_device || "";
      var b = el("div", "diag-karena");
      // ASCII arrow, not U+21B3: the page font lacks that glyph and it rendered as "l,".
      b.appendChild(el("span", "diag-panah", "->"));
      b.appendChild(el("span", null, " ikut jatuh karena "));
      b.appendChild(el("b", null, asal));
      b.appendChild(el("span", null, " — " + x.karena));
      isi.appendChild(b);
      isi.appendChild(el("div", "diag-jangan",
        "Tidak perlu diperiksa sendiri. Perbaiki penyebabnya, lalu lihat lagi."));
    }

    // Steps are shown only for causes; sending people to check a merely affected service would be misleading.
    if (x.langkah && x.langkah.length) {
      isi.appendChild(el("div", "diag-judul", "Langkah pertama"));
      var ol = el("ol", "diag-langkah");
      x.langkah.forEach(function (l) {
        var li = el("li");
        var pisah = l.split("   — ");
        li.appendChild(el("code", null, pisah[0]));
        if (pisah[1]) li.appendChild(el("span", "diag-ket", " " + pisah[1]));
        ol.appendChild(li);
      });
      isi.appendChild(ol);
      if (x.kalau_buntu) isi.appendChild(el("div", "diag-buntu", x.kalau_buntu));
    }

    var aksi = tautanAksi(x);
    if (aksi) isi.appendChild(aksi);

    var kaki = el("div", "diag-kaki");
    kaki.appendChild(el("code", null, x.bukti));
    if (x.kode) kaki.appendChild(el("span", null, "  kode " + x.kode));
    if (x.waktu_ms) {
      kaki.appendChild(el("span", null, "  " + Math.round(x.waktu_ms) + " ms"));
    }
    if (x.kategori) kaki.appendChild(el("span", null, "  " + x.kategori));
    isi.appendChild(kaki);

    n.appendChild(isi);
    return n;
  }

  /* Remember the open card and a fingerprint of the panel content. The panel rebuilds itself every 10 seconds, and without these a card being read would close mid-read. */
  var terbukaKunci = null;
  var sidikTerakhir = null;

  function kunciKartu(x) { return x.vonis + "|" + x.device + "|" + x.nama; }

  function gambar(h) {
    var sidik = JSON.stringify(h);
    if (sidik === sidikTerakhir) return;
    sidikTerakhir = sidik;

    kotak.textContent = "";

    if (!h || !h.daftar || !h.daftar.length) {
      var sehat = el("div", "diag-sehat");
      sehat.appendChild(el("span", "diag-titik-hijau", "●"));
      sehat.appendChild(el("span", null,
        " " + ((h && h.ringkas) || "Semua layanan yang dipantau sehat.")));
      kotak.appendChild(sehat);
      return;
    }

    var kepala = el("div", "diag-ringkas");
    kepala.appendChild(el("span", "diag-titik-merah", "●"));
    kepala.appendChild(el("span", null, " " + h.ringkas));
    kepala.appendChild(el("span", "diag-petunjuk-klik", "klik kartu untuk langkah dan buktinya"));
    kotak.appendChild(kepala);

    var kisi = el("div", "diag-kisi");
    h.daftar.forEach(function (x, i) { kisi.appendChild(kartu(x, i)); });
    kotak.appendChild(kisi);

    // Restore the open card by content, not by position, since the order can change when new findings appear.
    if (terbukaKunci) {
      var idx = -1;
      h.daftar.forEach(function (x, i) { if (kunciKartu(x) === terbukaKunci) idx = i; });
      if (idx >= 0) {
        var tombol = kisi.children[idx].querySelector(".diag-kepala");
        if (tombol) tombol.click();
      } else {
        terbukaKunci = null;
      }
    }
  }

  function muat() {
    fetch("/api/diagnosis", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(gambar)
      .catch(function () {
        // The panel being quiet must not read as "everything is healthy".
        kotak.textContent = "";
        kotak.appendChild(el("div", "diag-gagal",
          "Diagnosis tidak bisa dibaca. Ini BUKAN berarti semuanya sehat — " +
          "artinya NSM sendiri sedang tidak bisa menjawab."));
      });
  }

  muat();
  // Refreshes every 10 seconds, not 5 like the device cards: diagnosis changes less often than ping status.
  setInterval(muat, 10000);
})();
