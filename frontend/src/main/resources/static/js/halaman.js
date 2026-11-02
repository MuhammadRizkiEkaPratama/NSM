/* Page glue replacing the inline <script> blocks formerly in the HTML. With no inline scripts, the CSP can drop 'unsafe-inline'. Server values are passed as data-* attributes on <body> (treated as text, not code). Each section checks that its element exists, since the file is shared by many pages. */
(function () {
  var tubuh = document.body;
  var data = tubuh ? tubuh.dataset : {};

  /* Server-provided values, read once. `data-device-id` is read as `dataset.deviceId`; `data-deviceid` would not match. */
  window.DEVICE_ID = data.deviceId ? parseInt(data.deviceId, 10) : 0;
  window.PERIODE_AWAL = data.periode || "24h";

  /* Password strength meter. Wired before the "show password" button because it already handles masking; the reverse order would attach two handlers to the same toggle. */
  if (typeof pasangKekuatanPassword === "function" && document.getElementById("pw")) {
    window._kekuatanPasswordAktif = true;
    pasangKekuatanPassword({
      password: "pw",
      ulangi: document.getElementById("pw2") ? "pw2" : null,
      meter: document.getElementById("bar") ? "bar" : null,
      teks: document.getElementById("lbl") ? "lbl" : null,
      cocok: document.getElementById("matchlbl") ? "matchlbl" : null,
      lihat: document.getElementById("showpw") ? "showpw" : null,
      lain: document.getElementById("cur") ? ["cur"] : []
    });
  }

  /* "Show password" button for pages without the strength meter (Login, Change Email); toggles masking of all password fields on the page. */
  var saklarLihat = document.getElementById("showpw");
  if (saklarLihat && !window._kekuatanPasswordAktif) {
    saklarLihat.addEventListener("change", function () {
      var tipe = this.checked ? "text" : "password";
      var kolom = document.querySelectorAll('input[type="password"], input[data-pw]');
      Array.prototype.forEach.call(kolom, function (i) {
        i.setAttribute("data-pw", "1");
        i.type = tipe;                     // setelah tipenya berubah jadi text
      });
    });
  }

  /* Account lock countdown on the login page. Seconds are read from the URL (?secs=), not a Thymeleaf attribute: an array-valued parameter once broke rendering. */
  var mundur = document.getElementById("countdown");
  if (mundur) {
    var sisa = parseInt(new URLSearchParams(window.location.search).get("secs"), 10) || 0;
    (function detak() {
      if (sisa <= 0) { mundur.textContent = "00:00, bisa dicoba lagi"; return; }
      var m = Math.floor(sisa / 60), d = sisa % 60;
      mundur.textContent = (m < 10 ? "0" : "") + m + ":" + (d < 10 ? "0" : "") + d;
      sisa--;
      setTimeout(detak, 1000);
    })();
  }

  /* Timestamp appended to the captcha image URL so the browser requests a fresh image. */
  var tombolCaptcha = document.getElementById("capreload");
  if (tombolCaptcha) {
    if (typeof ikonUI === "function") tombolCaptcha.appendChild(ikonUI("segarkan", 16));
    tombolCaptcha.addEventListener("click", function () {
      var gambar = document.getElementById("capimg");
      if (gambar) gambar.src = "/captcha?" + Date.now();
    });
  }
})();


/* Shared JSON fetcher. When a session expires, Spring Security answers `/api/...` with the login page (HTML) instead of 401, so `r.json()` would fail with `Unexpected token '<'`. Checking the content type first distinguishes expired session, backend down, and malformed data. */
function ambilJson(url, opsi) {
  return fetch(url, opsi).then(function (r) {
    var jenis = r.headers.get("content-type") || "";

    // Redirected to the login page, or answered with any HTML
    if (jenis.indexOf("application/json") < 0) {
      var keLogin = (r.redirected && r.url && r.url.indexOf("/login") >= 0)
                 || r.status === 401 || r.status === 403;
      var e = new Error(keLogin
        ? "Sesi login sudah habis. Muat ulang halaman ini untuk masuk lagi."
        : "Server membalas " + r.status + " dengan isi bukan JSON.");
      e.sesiHabis = keLogin;
      throw e;
    }
    if (!r.ok) {
      // The body may be valid JSON even on failure (e.g. `{"ok": false, "ditolak": "..."}` from a command Python rejected). It is attached as `.badan` so callers can show the reason; callers that ignore it get the generic message.
      return r.json().then(function (badan) {
        var e = new Error("Server membalas kode " + r.status + ".");
        e.badan = badan;
        throw e;
      }, function () {
        throw new Error("Server membalas kode " + r.status + ".");
      });
    }
    return r.json();
  });
}


/* Fill one "who" cell of a traffic table: ADDRESS first, name second. The access log records only the IP; the device name comes from matching the address against the device list when the page opens, so a reassigned address (DHCP) could blame the wrong device. The name is shown as a hint ("matches"), not as log content. Shared by three tables on two pages. */
function selKlien(td, ip, namaDevice) {
  var alamat = document.createElement("div");
  alamat.className = "nama-klien";
  alamat.textContent = ip || "alamat tidak tercatat";
  td.appendChild(alamat);

  var ket = document.createElement("div");
  ket.className = "ip-klien";
  if (namaDevice) {
    ket.textContent = "cocok dengan device: " + namaDevice;
  } else {
    ket.textContent = "tidak terdaftar sebagai device";
  }
  td.appendChild(ket);
  return td;
}


/* Summary card sub-label: a short line on the card, the full sentence in the tooltip (P7). The short line states the fact that most changes the number's meaning (e.g. "Observed 6h16m of 24h"). */
function subKartu(ringkas, penuh) {
  var d = document.createElement("div");
  d.className = "sub";
  if (!penuh || penuh === ringkas) {
    d.textContent = ringkas;
    return d;
  }

  d.className = "sub sub-bertanya";
  d.setAttribute("data-petunjuk", penuh);

  // The full sentence is also written to the DOM, not only the attribute: paper has no cursor, and `@media print` swaps the two.
  var layar = document.createElement("span");
  layar.className = "sub-layar";
  layar.textContent = ringkas;
  d.appendChild(layar);

  var kertas = document.createElement("span");
  kertas.className = "sub-penuh";
  kertas.textContent = penuh;
  d.appendChild(kertas);
  return d;
}
