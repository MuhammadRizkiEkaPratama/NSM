/*
 * System Health page. The healthy/attention/danger verdict comes from the server; JavaScript only picks colors.
 * Anti-XSS: textContent and createElement only, never innerHTML with data (error messages and file names are uncontrolled).
 * Auto-refresh is 30 seconds, slower than the dashboard, because each refresh also opens a socket to the mail server.
 */

var JEDA_SEGAR_MS = 30000;
var pewaktu = null;

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function kosongkan(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/* Large numbers are grouped with a space, not a dot, because the dot means decimal everywhere else in the app and "170.428" would be ambiguous. */
function kelompokRibuan(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/* One card per checked item; same shape for Python and Java sections. */
function kartu(nama, vonis, nilai, ket) {
  var k = el("div", "periksa " + (vonis || ""));
  var kepala = el("div", "kepala");
  kepala.appendChild(el("span", "nama", nama));
  kepala.appendChild(el("span", "nilai", nilai || "-"));
  k.appendChild(kepala);

  // The explanation is hidden unless the card has a problem, so the healthy/unhealthy answer stays near the top; problem cards always show it.
  if (ket) {
    var gawat = (vonis === "perhatian" || vonis === "bahaya");
    if (gawat) {
      k.appendChild(el("div", "ket", ket));
    } else if (window.jelas) {
      window.jelas.pasang(kepala, ket, k);
    } else {
      // Fallback when jelas.js failed to load: show the text instead of losing the explanation.
      k.appendChild(el("div", "ket", ket));
    }
  }
  return k;
}

function tambahRincian(kartuEl, daftar) {
  if (!daftar || !daftar.length) return;
  var kotak = el("div", "rincian");
  daftar.forEach(function (r) {
    var baris = el("div", "baris");
    baris.appendChild(el("b", null, r.label));
    baris.appendChild(el("span", null, r.nilai));
    if (r.ket) baris.setAttribute("data-petunjuk", r.ket);
    kotak.appendChild(baris);
  });
  kartuEl.appendChild(kotak);
}

function gambarVonis(vonis, ringkas, masalah) {
  var kotak = document.getElementById("vonis");
  kosongkan(kotak);
  kotak.className = vonis || "";

  var judul = vonis === "sehat" ? "NSM sehat"
            : vonis === "perhatian" ? "Ada yang perlu dilirik"
            : "Ada bagian yang berhenti";
  kotak.appendChild(el("h2", null, judul));
  kotak.appendChild(el("div", "ringkas", ringkas || ""));

  if (masalah && masalah.length) {
    var ul = el("ul");
    masalah.forEach(function (m) { ul.appendChild(el("li", null, m)); });
    kotak.appendChild(ul);
  }
}

/* Overall verdict is merged here because the sections come from two sources (Python and Java); only the existing severities are combined, no new judgment. */
var URUTAN = { "sehat": 0, "mati-sengaja": 0, "perhatian": 1, "bahaya": 2 };

function terburuk(daftar) {
  var hasil = "sehat";
  daftar.forEach(function (v) {
    if ((URUTAN[v] || 0) > (URUTAN[hasil] || 0)) hasil = v;
  });
  return hasil;
}

function gambar(d) {
  var kisi = document.getElementById("kisi");
  kosongkan(kisi);

  var semuaVonis = [];
  var masalah = [];

  if (d.python_hidup === false) {
    semuaVonis.push("bahaya");
    masalah.push("Backend Python (uvicorn) tidak bisa dihubungi. Seluruh data "
      + "device, laporan, dan lalu lintas tidak tersedia selama ini "
      + "berlangsung, dan poller kemungkinan besar ikut mati.");
    // Written as a sentence, not a raw error message.
    kisi.appendChild(kartu("Backend Python (uvicorn)", "bahaya",
      "tidak terhubung",
      "Java tidak bisa menghubungi http://localhost:8000"
      + (d.python_galat ? ": " + d.python_galat : "")
      + ". Nyalakan lagi dengan: uvicorn main:app --port 8000"));
  } else {
    var p = d.python || {};
    kisi.appendChild(kartu("Backend Python (uvicorn)", "sehat", "terhubung",
      "Menjawab di http://localhost:8000. Seluruh angka di halaman ini, "
      + "kecuali MySQL dan server email, dihitung di sana."));

    (p.bagian || []).forEach(function (b) {
      semuaVonis.push(b.vonis);
      var k = kartu(b.nama, b.vonis, b.nilai, b.ket);
      tambahRincian(k, b.rincian);

      if (b.jumlah_baris) {
        var potong = [];
        Object.keys(b.jumlah_baris).forEach(function (t) {
          var n = b.jumlah_baris[t];
          if (n !== null && n !== undefined) {
            potong.push(t + " " + kelompokRibuan(n));
          }
        });
        if (potong.length) {
          k.appendChild(el("div", "jumlah-baris", potong.join("  ·  ")));
        }
      }

      if (b.lompatan && b.lompatan.length) {
        k.appendChild(el("div", "jumlah-baris",
          "lompatan terpanjang: " + b.lompatan.join(" dtk, ") + " dtk"));
      }
      kisi.appendChild(k);
    });

    (p.masalah || []).forEach(function (m) { masalah.push(m); });
  }

  ["mysql", "smtp"].forEach(function (kunci) {
    var b = d[kunci];
    if (!b) return;
    semuaVonis.push(b.vonis);
    var nama = kunci === "mysql" ? "MySQL (akun & audit log)"
                                 : "Server email (" + (b.tujuan || "SMTP") + ")";
    var nilai = b.nilai;
    if (b.ms !== undefined && b.ms !== null) nilai += "  ·  " + b.ms + " ms";
    kisi.appendChild(kartu(nama, b.vonis, nilai, b.ket));
    if (b.vonis === "perhatian" || b.vonis === "bahaya") masalah.push(b.ket);
  });

  var vonis = terburuk(semuaVonis);
  var ringkas = (d.python && d.python.ringkas) ? d.python.ringkas : "";
  if (vonis !== "sehat" && masalah.length) {
    ringkas = masalah.length + " hal perlu diperiksa.";
  } else if (vonis === "sehat") {
    ringkas = "Semua bagian NSM berjalan sesuai jadwal, termasuk MySQL dan "
            + "server email.";
  }
  gambarVonis(vonis, ringkas, masalah);

  // Labeled "Diperbarui" (last page fetch time), consistent with the other pages; the Backup page deliberately says "Diperiksa" because its value comes from the server.
  document.getElementById("meta").textContent =
    "Diperbarui " + new Date().toLocaleTimeString("id-ID");
}

function muat() {
  ambilJson("/api/kesehatan").then(gambar).catch(function (e) {
    // Distinguished so the cause is not misattributed: an expired session needs a re-login, a broken page needs the Console.
    var kotak = document.getElementById("vonis");
    kosongkan(kotak);
    kotak.className = "bahaya";
    kotak.appendChild(el("h2", null, e.sesiHabis
      ? "Sesi login habis" : "Halaman ini gagal memuat"));
    kotak.appendChild(el("div", "ringkas", e.message));
    console.error("[NSM] gagal memuat kesehatan:", e);
  });
}

document.getElementById("segarkan").addEventListener("click", muat);

document.addEventListener("visibilitychange", function () {
  // Hidden tabs do not need to keep opening sockets to the mail server.
  if (document.hidden) {
    clearInterval(pewaktu);
    pewaktu = null;
  } else if (!pewaktu) {
    muat();
    pewaktu = setInterval(muat, JEDA_SEGAR_MS);
  }
});

muat();
pewaktu = setInterval(muat, JEDA_SEGAR_MS);
