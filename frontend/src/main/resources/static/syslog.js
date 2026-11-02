/* Syslog page. One request loads the summary (`/api/syslog/dasbor`: cards, chart, tags, senders) so the page never half-fills; the message list is separate because it changes with every filter or page change. */
(function () {
  "use strict";

  var elJam      = document.getElementById("sl-jam");
  var elCari     = document.getElementById("sl-cari");
  var elPenting  = document.getElementById("sl-penting");
  var elUbin     = document.getElementById("sl-ubin");
  var elGrafik   = document.getElementById("sl-grafik");
  var elGrafikKet = document.getElementById("sl-grafik-ket");
  var elGrafikKosong = document.getElementById("sl-grafik-kosong");
  var elTag      = document.getElementById("sl-tag");
  var elKirim    = document.getElementById("sl-pengirim");
  var elBaris    = document.getElementById("sl-baris");
  var elHalKet   = document.getElementById("sl-halaman-ket");
  var elSaring   = document.getElementById("sl-saring-aktif");
  var btnSebelum = document.getElementById("sl-sebelum");
  var btnSesudah = document.getElementById("sl-sesudah");

  var keadaan = { jam: 24, tag: null, deviceId: null, cari: "", penting: false, halaman: 1 };
  var grafik = null;
  var ambangPenting = 4;

  /* Severity colors. Syslog numbers are inverted from intuition: 0 is most severe, 7 least (RFC 3164). Translated in one place. */
  function warnaSeverity(s) {
    if (s === null || s === undefined) return "var(--tak-diketahui)";
    if (s <= 2) return "var(--down)";
    if (s <= 4) return "var(--hati-hati)";
    if (s <= 5) return "var(--oranye)";
    return "var(--up)";
  }

  function esc(t) {
    return String(t === null || t === undefined ? "" : t)
      .replace(/[&<>"]/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
      });
  }

  function angka(n) {
    return Number(n || 0).toLocaleString("id-ID");
  }

  function ambil(url) {
    return fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }

  /* ------------------------------------------------------------ ringkasan */
  function gambarUbin(d) {
    var persenPenting = d.total ? Math.round(d.penting * 100 / d.total) : 0;
    var teratas = (d.per_tag && d.per_tag[0]) || null;

    var ubin = [
      { label: "Pesan diterima", nilai: angka(d.total),
        kaki: d.jam + " jam terakhir" },
      { label: "Tergolong gawat", nilai: angka(d.penting),
        kaki: persenPenting + "% dari seluruh pesan",
        sorot: persenPenting >= 70 },
      { label: "Pengirim", nilai: angka((d.per_device || []).length),
        kaki: (d.dari_pengirim_tak_dikenal
               ? angka(d.dari_pengirim_tak_dikenal) + " pesan dari pengirim tak dikenal"
               : "semuanya dikenal"),
        sorot: d.dari_pengirim_tak_dikenal > 0 },
      { label: "Pola berbeda", nilai: angka((d.templat_teratas || []).length),
        kaki: teratas ? teratas.persen + "% cuma satu pola" : "belum ada" }
    ];

    elUbin.innerHTML = ubin.map(function (u) {
      return '<div class="sl-ubin-kartu">' +
        '<span class="sl-ubin-label">' + esc(u.label) + "</span>" +
        '<span class="sl-ubin-nilai">' + u.nilai + "</span>" +
        '<span class="sl-ubin-kaki' + (u.sorot ? " sorot" : "") + '">' +
          esc(u.kaki) + "</span>" +
      "</div>";
    }).join("");
  }

  /* --------------------------------------------------------------- grafik */
  function bacaWarna(nama) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(nama).trim() || "#888";
  }

  function gambarGrafik(deret) {
    if (!deret || !deret.length) {
      elGrafikKosong.hidden = false;
      elGrafik.style.display = "none";
      if (grafik) { grafik.dispose(); grafik = null; }
      return;
    }
    elGrafikKosong.hidden = true;
    elGrafik.style.display = "";

    if (!grafik) grafik = echarts.init(elGrafik, null, { renderer: "canvas" });

    var jam    = deret.map(function (t) { return t.jam.slice(11, 16); });
    var semua  = deret.map(function (t) { return t.semua - t.penting; });
    var gawat  = deret.map(function (t) { return t.penting; });

    var teksRedup = bacaWarna("--teks-redup");
    var garis     = bacaWarna("--garis");

    grafik.setOption({
      grid: { left: 46, right: 14, top: 18, bottom: 28 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: bacaWarna("--permukaan-3"),
        borderColor: garis,
        textStyle: { color: bacaWarna("--teks"), fontSize: 12 }
      },
      legend: {
        show: true, top: -2, right: 0, itemHeight: 8, itemWidth: 14,
        textStyle: { color: teksRedup, fontSize: 11 }
      },
      xAxis: {
        type: "category", data: jam,
        axisLine: { lineStyle: { color: garis } },
        axisTick: { show: false },
        axisLabel: { color: teksRedup, fontSize: 11 }
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: garis, type: "dashed" } },
        axisLabel: { color: teksRedup, fontSize: 11 }
      },
      series: [
        { name: "Biasa", type: "bar", stack: "x", data: semua,
          itemStyle: { color: bacaWarna("--teks-samar"), borderRadius: [0, 0, 2, 2] } },
        { name: "Gawat", type: "bar", stack: "x", data: gawat,
          itemStyle: { color: bacaWarna("--hati-hati"), borderRadius: [2, 2, 0, 0] } }
      ]
    });
    grafik.resize();
  }

  /* ------------------------------------------------------------ tag & kirim */
  function gambarTag(daftar) {
    if (!daftar || !daftar.length) {
      elTag.innerHTML = '<p class="redup">Belum ada pesan pada jendela ini.</p>';
      return;
    }
    elTag.innerHTML = daftar.map(function (t) {
      var aktif = keadaan.tag === t.tag;
      return '<button type="button" class="sl-baris-pilih" data-tag="' + esc(t.tag) + '"' +
        ' aria-pressed="' + aktif + '" style="--aksen:' + warnaSeverity(t.terparah) + '">' +
        '<span class="sl-titik"></span>' +
        '<span class="sl-baris-teks">' +
          '<span class="sl-baris-utama mono">' + esc(t.tag) + "</span>" +
          '<span class="sl-baris-bawah">paling gawat: ' + esc(t.terparah_nama) + "</span>" +
        "</span>" +
        '<span class="sl-baris-angka">' + angka(t.jumlah) +
          "<small>" + t.persen + "%</small></span>" +
        '<span class="sl-bilah"><i style="width:' + Math.max(2, t.persen) + '%"></i></span>' +
      "</button>";
    }).join("");
  }

  function gambarKirim(daftar) {
    if (!daftar || !daftar.length) {
      elKirim.innerHTML = '<p class="redup">Belum ada pengirim pada jendela ini.</p>';
      return;
    }
    var puncak = daftar[0].jumlah || 1;
    elKirim.innerHTML = daftar.map(function (p) {
      var aktif = keadaan.deviceId === p.device_id && p.device_id !== null;
      var persen = Math.round(p.jumlah * 100 / puncak);
      return '<button type="button" class="sl-baris-pilih"' +
        ' data-device="' + (p.device_id === null ? "" : p.device_id) + '"' +
        ' aria-pressed="' + aktif + '" style="--aksen:' + warnaSeverity(p.terparah) + '">' +
        '<span class="sl-titik"></span>' +
        '<span class="sl-baris-teks">' +
          '<span class="sl-baris-utama' + (p.dikenal ? "" : " tak-dikenal") + '">' +
            esc(p.nama) + "</span>" +
          '<span class="sl-baris-bawah">' + esc(p.alamat) +
            " &middot; paling gawat: " + esc(p.terparah_nama) + "</span>" +
        "</span>" +
        '<span class="sl-baris-angka">' + angka(p.jumlah) + "</span>" +
        '<span class="sl-bilah"><i style="width:' + Math.max(2, persen) + '%"></i></span>' +
      "</button>";
    }).join("");
  }

  /* --------------------------------------------------------------- daftar */
  function gambarBaris(d) {
    if (!d.pesan || !d.pesan.length) {
      elBaris.innerHTML = '<tr><td colspan="5" class="redup">' +
        "Tidak ada pesan yang cocok dengan penyaring ini.</td></tr>";
    } else {
      elBaris.innerHTML = d.pesan.map(function (p) {
        return "<tr>" +
          '<td class="kol-waktu">' + esc(p.waktu.slice(5, 19)) + "</td>" +
          "<td" + (p.dikenal ? "" : ' class="tak-dikenal"') + ">" + esc(p.nama) + "</td>" +
          '<td><span class="sl-tingkat">' +
            '<span class="sl-titik" style="--aksen:' + warnaSeverity(p.severity) + '"></span>' +
            esc(p.severity_nama) + "</span></td>" +
          '<td class="kol-tag">' + esc(p.tag) + "</td>" +
          '<td class="kol-isi">' + esc(p.pesan) + "</td>" +
        "</tr>";
      }).join("");
    }

    var dari = d.total ? (d.halaman - 1) * d.per_halaman + 1 : 0;
    var sampai = Math.min(d.halaman * d.per_halaman, d.total);
    elHalKet.textContent = d.total
      ? "Baris " + dari + "–" + sampai + " dari " + angka(d.total) +
        " · halaman " + d.halaman + " dari " + d.jumlah_halaman
      : "Tidak ada baris";
    btnSebelum.disabled = d.halaman <= 1;
    btnSesudah.disabled = d.halaman >= d.jumlah_halaman;
    keadaan.halaman = d.halaman;
  }

  function ketSaring() {
    var bagian = [];
    if (keadaan.tag) bagian.push("tag " + keadaan.tag);
    if (keadaan.deviceId !== null) bagian.push("satu perangkat");
    if (keadaan.penting) bagian.push("hanya yang gawat");
    if (keadaan.cari) bagian.push('mengandung "' + keadaan.cari + '"');
    elSaring.textContent = bagian.length
      ? "disaring: " + bagian.join(" · ") + " — klik ulang untuk melepas"
      : "";
  }

  /* ----------------------------------------------------------------- muat */
  function muatRingkas() {
    return ambil("/api/syslog/dasbor?jam=" + keadaan.jam).then(function (d) {
      ambangPenting = d.ambang_penting;
      elGrafikKet.textContent = angka(d.total) + " pesan · " + d.jam + " jam";
      gambarUbin(d);
      gambarGrafik(d.deret);
      gambarTag(d.per_tag);
      gambarKirim(d.per_device);
    }).catch(function (e) {
      elUbin.innerHTML = '<p class="redup">Gagal memuat ringkasan: ' + esc(e.message) + "</p>";
    });
  }

  function muatDaftar() {
    var u = "/api/syslog/pesan?jam=" + keadaan.jam +
            "&halaman=" + keadaan.halaman + "&perHalaman=5";
    if (keadaan.tag) u += "&tag=" + encodeURIComponent(keadaan.tag);
    if (keadaan.deviceId !== null) u += "&deviceId=" + keadaan.deviceId;
    if (keadaan.penting) u += "&penting=true";
    if (keadaan.cari) u += "&cari=" + encodeURIComponent(keadaan.cari);

    ketSaring();
    return ambil(u).then(gambarBaris).catch(function (e) {
      elBaris.innerHTML = '<tr><td colspan="5" class="redup">Gagal memuat: ' +
        esc(e.message) + "</td></tr>";
    });
  }

  function muatSemua() {
    keadaan.halaman = 1;
    return Promise.all([muatRingkas(), muatDaftar()]);
  }

  /* -------------------------------------------------------------- kendali */
  elJam.addEventListener("change", function () {
    keadaan.jam = Number(elJam.value);
    muatSemua();
  });

  elPenting.addEventListener("change", function () {
    keadaan.penting = elPenting.checked;
    keadaan.halaman = 1;
    muatDaftar();
  });

  /* Search is debounced by 300 ms to avoid one request per keystroke. */
  var jedaCari = null;
  elCari.addEventListener("input", function () {
    clearTimeout(jedaCari);
    jedaCari = setTimeout(function () {
      keadaan.cari = elCari.value.trim();
      keadaan.halaman = 1;
      muatDaftar();
    }, 300);
  });

  btnSebelum.addEventListener("click", function () {
    if (keadaan.halaman > 1) { keadaan.halaman--; muatDaftar(); }
  });
  btnSesudah.addEventListener("click", function () {
    keadaan.halaman++; muatDaftar();
  });

  /* Clicking a tag or sender filters; clicking again clears the filter. */
  elTag.addEventListener("click", function (e) {
    var b = e.target.closest("[data-tag]");
    if (!b) return;
    keadaan.tag = (keadaan.tag === b.dataset.tag) ? null : b.dataset.tag;
    keadaan.halaman = 1;
    Array.prototype.forEach.call(elTag.querySelectorAll("[data-tag]"), function (x) {
      x.setAttribute("aria-pressed", String(x.dataset.tag === keadaan.tag));
    });
    muatDaftar();
  });

  elKirim.addEventListener("click", function (e) {
    var b = e.target.closest("[data-device]");
    if (!b) return;
    var id = b.dataset.device === "" ? null : Number(b.dataset.device);
    if (id === null) return;      /* unknown senders cannot be filtered yet */
    keadaan.deviceId = (keadaan.deviceId === id) ? null : id;
    keadaan.halaman = 1;
    Array.prototype.forEach.call(elKirim.querySelectorAll("[data-device]"), function (x) {
      x.setAttribute("aria-pressed",
        String(x.dataset.device !== "" && Number(x.dataset.device) === keadaan.deviceId));
    });
    muatDaftar();
  });

  /* ECharts reads colors once when drawing, so the chart is redrawn when the theme changes. */
  document.addEventListener("nsm:tema", function () { muatRingkas(); });
  window.addEventListener("resize", function () { if (grafik) grafik.resize(); });

  muatSemua();
})();
