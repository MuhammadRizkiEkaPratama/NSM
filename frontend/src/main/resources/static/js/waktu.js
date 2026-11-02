/* Shared time formatting. Relative times ("2 menit lalu") show how fresh data is; the exact time is available as a tooltip. Do not use in printed documents. */

function waktuRelatif(tanggal) {
  if (!tanggal) return "-";
  var d = (tanggal instanceof Date) ? tanggal : new Date(tanggal);
  if (isNaN(d.getTime())) return "-";

  var detik = Math.floor((Date.now() - d.getTime()) / 1000);
  if (detik < 0) detik = 0;

  if (detik < 10) return "baru saja";
  if (detik < 60) return detik + " detik lalu";

  var menit = Math.floor(detik / 60);
  if (menit < 60) return menit + " menit lalu";

  var jam = Math.floor(menit / 60);
  if (jam < 24) return jam + " jam lalu";

  var hari = Math.floor(jam / 24);
  if (hari === 1) return "kemarin";
  if (hari < 30) return hari + " hari lalu";

  return waktuLengkap(d);
}

function waktuLengkap(tanggal) {
  if (!tanggal) return "-";
  var d = (tanggal instanceof Date) ? tanggal : new Date(tanggal);
  if (isNaN(d.getTime())) return "-";
  return d.toLocaleString("id-ID", {
    day: "2-digit", month: "long", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}

function jamSaja(tanggal) {
  if (!tanggal) return "-";
  var d = (tanggal instanceof Date) ? tanggal : new Date(tanggal);
  if (isNaN(d.getTime())) return "-";
  return d.toLocaleTimeString("id-ID");
}

/* Elements showing relative time must age on their own, or a page left open keeps showing "just now". */
function pasangWaktuRelatif(el, tanggal) {
  function perbarui() {
    el.textContent = waktuRelatif(tanggal);
    el.setAttribute("data-petunjuk", waktuLengkap(tanggal));
  }
  perbarui();
  if (!window._jamRelatif) {
    window._jamRelatif = [];
    setInterval(function () {
      if (document.hidden) return;
      window._jamRelatif.forEach(function (f) { f(); });
    }, 20000);
  }
  window._jamRelatif.push(perbarui);
}
