/*
 * Three Dashboard charts beside the topology map, each answering something the page does not already show:
 *   1. Hourly availability: the dashboard shows only the present, not last night.
 *   2. Device messages per hour: syslog volume was not visible on the dashboard.
 *   3. Storage capacity: shows which device is closest to its threshold.
 */
(function () {
  "use strict";

  var el = {
    ada: document.getElementById("dg-ketersediaan"),
    ket: document.getElementById("dg-ketersediaan"),
    pesan: document.getElementById("dg-pesan"),
    kap: document.getElementById("dg-kapasitas"),
    ketKaki: document.getElementById("dg-ketersediaan-kaki"),
    pesanKaki: document.getElementById("dg-pesan-kaki"),
    kapKaki: document.getElementById("dg-kapasitas-kaki")
  };
  if (!el.ada) return;              

  var grafik = { ket: null, pesan: null, kap: null };

  function warna(nama) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(nama).trim() || "#888";
  }

  function angka(n, desimal) {
    return Number(n || 0).toLocaleString("id-ID", {
      minimumFractionDigits: desimal || 0, maximumFractionDigits: desimal || 0
    });
  }

  /* `toFixed()` always uses a decimal point; NSM uses a comma ("99,21%"), so numbers are formatted to match. */
  function persen(n, desimal) {
    return angka(n, desimal === undefined ? 2 : desimal) + "%";
  }

  function dasar() {
    var redup = warna("--teks-redup"), garis = warna("--garis");
    return {
      grid: { left: 38, right: 10, top: 12, bottom: 20 },
      tooltip: {
        trigger: "axis",
        backgroundColor: warna("--permukaan-3"),
        borderColor: garis,
        textStyle: { color: warna("--teks"), fontSize: 11 }
      },
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: garis } },
        axisTick: { show: false },
        axisLabel: { color: redup, fontSize: 10, interval: "auto" }
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: garis, type: "dashed" } },
        axisLabel: { color: redup, fontSize: 10 }
      }
    };
  }

  /* ---------------------------------------------------------------- 1. */
  function gambarKetersediaan(d) {
    var titik = d.ketersediaan.filter(function (t) { return t.persen !== null; });
    if (!titik.length) {
      el.ketKaki.textContent = "Belum ada data ringkasan per jam.";
      return;
    }
    var nilai = titik.map(function (t) { return t.persen; });
    var terendah = Math.min.apply(null, nilai);

    /* The Y axis deliberately does not start at zero: daily availability sits at 99-100%, and a 0-100 axis would hide a dip to 97%. The lower bound is stated in the chart caption. */
    var bawah = Math.max(0, Math.floor(terendah * 10) / 10 - 0.2);

    if (!grafik.ket) grafik.ket = echarts.init(el.ket, null, { renderer: "canvas" });
    var o = dasar();
    o.xAxis.data = titik.map(function (t) { return t.jam.slice(11, 16); });
    o.yAxis.min = bawah;
    o.yAxis.max = 100;
    o.yAxis.axisLabel.formatter = function (v) { return persen(v, 1); };
    o.tooltip.valueFormatter = function (v) { return persen(v, 2); };
    o.series = [{
      name: "Menjawab", type: "line", data: nilai,
      smooth: false, symbol: "none",
      lineStyle: { width: 2, color: warna("--up") },
      areaStyle: { color: warna("--up"), opacity: 0.12 },
      markLine: {
        silent: true, symbol: "none",
        data: [{ yAxis: 100 }],
        lineStyle: { color: warna("--garis-terang"), type: "dotted", width: 1 },
        label: { show: false }
      }
    }];
    grafik.ket.setOption(o, true);
    grafik.ket.resize();

    var jamTurun = titik.filter(function (t) { return t.persen < 100; }).length;
    el.ketKaki.textContent = jamTurun
      ? jamTurun + " dari " + titik.length + " jam ada yang sempat tidak menjawab" +
        " · terendah " + persen(terendah, 2) + " · sumbu mulai " + persen(bawah, 1)
      : "Tidak ada satu jam pun yang turun dari 100% · " + titik.length + " jam";
  }

  /* ---------------------------------------------------------------- 2. */
  function gambarPesan(d) {
    var titik = d.pesan || [];
    if (!titik.length) {
      el.pesanKaki.textContent = "Belum ada pesan pada jendela ini.";
      return;
    }
    if (!grafik.pesan) grafik.pesan = echarts.init(el.pesan, null, { renderer: "canvas" });
    var o = dasar();
    o.grid.left = 34;
    o.xAxis.data = titik.map(function (t) { return t.jam.slice(11, 16); });
    o.series = [
      { name: "Biasa", type: "bar", stack: "x",
        data: titik.map(function (t) { return t.semua - t.penting; }),
        itemStyle: { color: warna("--teks-samar") } },
      { name: "Gawat", type: "bar", stack: "x",
        data: titik.map(function (t) { return t.penting; }),
        itemStyle: { color: warna("--hati-hati"), borderRadius: [2, 2, 0, 0] } }
    ];
    grafik.pesan.setOption(o, true);
    grafik.pesan.resize();

    var total = titik.reduce(function (a, t) { return a + t.semua; }, 0);
    var gawat = titik.reduce(function (a, t) { return a + t.penting; }, 0);
    var puncak = titik.reduce(function (a, t) { return t.semua > a.semua ? t : a; }, titik[0]);
    el.pesanKaki.textContent =
      angka(total) + " pesan · " + angka(gawat) + " gawat · " +
      "tersibuk pukul " + puncak.jam.slice(11, 16) + " (" + angka(puncak.semua) + ")";
  }

  /* ---------------------------------------------------------------- 3. */
  function gambarKapasitas(d) {
    var baris = (d.kapasitas || []).filter(function (k) { return k.disk_persen !== null; });
    if (!baris.length) {
      el.kapKaki.textContent = "Belum ada pengukuran sumber daya.";
      return;
    }
    if (!grafik.kap) grafik.kap = echarts.init(el.kap, null, { renderer: "canvas" });

    /* Horizontal bars: device names are long, and vertical bars would need rotated or truncated labels. */
    var nama = baris.map(function (k) {
      return k.nama.replace(/\s*\(Lokasi [AB]\)/, "").slice(0, 18);
    });
    var disk = baris.map(function (k) { return k.disk_persen; });

    var o = {
      grid: { left: 4, right: 34, top: 6, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow" },
        backgroundColor: warna("--permukaan-3"), borderColor: warna("--garis"),
        textStyle: { color: warna("--teks"), fontSize: 11 },
        formatter: function (p) {
          var k = baris[p[0].dataIndex];
          return "<b>" + k.nama + "</b><br>disk " + k.disk_persen + "%" +
                 (k.mem_persen !== null ? "<br>memori " + k.mem_persen + "%" : "") +
                 (k.load_per_inti !== null ? "<br>beban " + k.load_per_inti + " / inti" : "");
        }
      },
      xAxis: { type: "value", max: 100, splitLine: { show: false },
               axisLabel: { show: false } },
      yAxis: { type: "category", data: nama, inverse: true,
               axisLine: { show: false }, axisTick: { show: false },
               axisLabel: { color: warna("--teks-2"), fontSize: 10.5 } },
      series: [{
        type: "bar", data: disk, barWidth: 11,
        /* Color follows closeness to the threshold, not order, so devices past it stand out without comparison. */
        itemStyle: {
          borderRadius: [0, 3, 3, 0],
          color: function (p) {
            var v = p.value;
            if (v >= d.ambang_disk) return warna("--down");
            if (v >= d.ambang_disk - 20) return warna("--hati-hati");
            return warna("--up");
          }
        },
        label: { show: true, position: "right", color: warna("--teks-2"),
                 fontSize: 10.5, formatter: "{c}%" },
        markLine: {
          silent: true, symbol: "none",
          data: [{ xAxis: d.ambang_disk }],
          lineStyle: { color: warna("--down"), type: "dashed", width: 1 },
          label: { show: true, position: "end", formatter: d.ambang_disk + "%",
                   color: warna("--down"), fontSize: 9.5 }
        }
      }]
    };
    grafik.kap.setOption(o, true);
    grafik.kap.resize();

    var tertinggi = baris[0];
    var dekat = baris.filter(function (k) { return k.disk_persen >= d.ambang_disk - 20; }).length;
    el.kapKaki.textContent =
      baris.length + " server terukur · tertinggi " + tertinggi.nama + " " +
      persen(tertinggi.disk_persen, 1) +
      (dekat ? " · " + dekat + " sudah di atas " + (d.ambang_disk - 20) + "%" : "");
  }

  /* ------------------------------------------------------------- muat */
  function muat() {
    fetch("/api/dasbor/grafik?jam=24", { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (d && d.ok === false) throw new Error(d.ditolak || "ditolak");
        gambarKetersediaan(d);
        gambarPesan(d);
        gambarKapasitas(d);
      })
      .catch(function (e) {
        [el.ketKaki, el.pesanKaki, el.kapKaki].forEach(function (k) {
          if (k) k.textContent = "Gagal memuat: " + e.message;
        });
      });
  }

  /* ECharts reads theme colors once when drawing and does not know the theme changed. The theme switch reloads the page, so this is only a safety net. */
  document.addEventListener("nsm:tema", muat);

  window.addEventListener("resize", function () {
    Object.keys(grafik).forEach(function (k) {
      if (grafik[k]) grafik[k].resize();
    });
  });

  muat();
  /* Refreshed every 60 seconds, not every 5 like the device cards: these charts show hours, and faster polling only adds database load. */
  setInterval(muat, 60000);
})();
