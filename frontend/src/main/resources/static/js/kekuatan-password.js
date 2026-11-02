/*
 * Shared password strength meter. Display only, NOT a guard: the real check is `PasswordPolicy` on the Java side, and anything shown here can be bypassed by disabling JavaScript.
 *
 * Usage:
 *   pasangKekuatanPassword({
 *     password: "pw", ulangi: "pw2", meter: "bar", teks: "lbl",
 *     cocok: "matchlbl", lihat: "showpw", lain: ["cur"]
 *   });
 * All values are element ids; missing ones may be left out.
 */
function pasangKekuatanPassword(opsi) {
  function ambil(id) { return id ? document.getElementById(id) : null; }

  var pw     = ambil(opsi.password);
  var pw2    = ambil(opsi.ulangi);
  var meter  = ambil(opsi.meter);
  var teks   = ambil(opsi.teks);
  var cocok  = ambil(opsi.cocok);
  var lihat  = ambil(opsi.lihat);
  if (!pw) return;

  // Same thresholds as `PasswordPolicy` in Java: at least 8 characters, with upper case, lower case, and a digit.
  var ATURAN = [
    { id: "r-len",   uji: function (v) { return v.length >= 8; } },
    { id: "r-upper", uji: function (v) { return /[A-Z]/.test(v); } },
    { id: "r-lower", uji: function (v) { return /[a-z]/.test(v); } },
    { id: "r-digit", uji: function (v) { return /[0-9]/.test(v); } }
  ];

  var LEBAR = [0, 20, 40, 60, 85, 100];
  var WARNA = ["#333333", "#ef4444", "#f59e0b", "#f59e0b", "#84cc16", "#22c55e"];
  var NAMA  = ["Ketik password baru", "Sangat lemah", "Lemah", "Sedang", "Kuat", "Sangat kuat"];

  function nilai() {
    var v = pw.value;
    var skor = 0;
    ATURAN.forEach(function (a) {
      var ok = a.uji(v);
      var li = document.getElementById(a.id);
      if (li) li.className = ok ? "ok" : "";
      if (ok) skor++;
    });
    // A long password that meets all rules moves up one level.
    if (v.length === 0) skor = 0;
    else if (v.length >= 12 && skor === 4) skor = 5;

    if (meter) {
      meter.style.width = LEBAR[skor] + "%";
      meter.style.background = WARNA[skor];
    }
    if (teks) {
      teks.textContent = NAMA[skor];
      teks.style.color = skor >= 4 ? "#4ade80" : (skor >= 1 ? "#f59e0b" : "#8a8a8a");
    }
  }

  function periksaSama() {
    if (!pw2 || !cocok) return;
    if (pw2.value.length === 0) { cocok.textContent = ""; return; }
    var sama = pw.value === pw2.value;
    cocok.textContent = sama ? "Password cocok" : "Password belum sama";
    cocok.style.color = sama ? "#4ade80" : "#f87171";
  }

  pw.addEventListener("input", function () { nilai(); periksaSama(); });
  if (pw2) pw2.addEventListener("input", periksaSama);

  if (lihat) {
    lihat.addEventListener("change", function () {
      var tipe = this.checked ? "text" : "password";
      [pw, pw2].forEach(function (i) { if (i) i.type = tipe; });
      (opsi.lain || []).forEach(function (id) {
        var i = document.getElementById(id);
        if (i) i.type = tipe;
      });
    });
  }
}
