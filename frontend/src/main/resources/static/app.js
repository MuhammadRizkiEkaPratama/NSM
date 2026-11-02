/*
 * NSM dashboard: one card per device. Anti-XSS: name, IP and location come from the database,
 * so they go through textContent, never innerHTML.
 */

function el(tag, kelas, teks) {
  var e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined && teks !== null) e.textContent = teks;
  return e;
}

function tautan(teks, href, kelas) {
  var a = el("a", kelas, teks);
  a.setAttribute("href", href);
  return a;
}

// CSRF token and role, read once from <meta> in dashboard.html
function meta(nama) {
  var m = document.querySelector('meta[name="' + nama + '"]');
  return m ? m.getAttribute("content") : "";
}
var ADMIN = meta("admin") === "true";

/*
 * Requests that WRITE. All go through one path so CSRF token handling and failures are handled
 * in one place, with a double-click guard: SQLite allows a single writer, and a duplicated
 * request (later also config pushes) could otherwise run twice on a real router.
 */
var sedangMengirim = {};

async function kirimUbahan(jalur, badan, pesanGagal, tombol) {
  if (sedangMengirim[jalur]) return;
  sedangMengirim[jalur] = true;

  if (tombol) {
    tombol.disabled = true;
    tombol.classList.add("sibuk");
  }

  var header = { "Content-Type": "application/json" };
  var namaHeader = meta("_csrf_header");
  if (namaHeader) header[namaHeader] = meta("_csrf");
  try {
    var r = await fetch(jalur, {
      method: "POST", headers: header, body: JSON.stringify(badan)
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    await muat();
  } catch (e) {
    // Messages are distinguished: rejected because not admin is different from a busy database.
    var pesan = String(e.message).indexOf("403") >= 0
      ? pesanGagal + "\nHanya admin yang boleh melakukan ini."
      : pesanGagal + "\nCoba lagi sebentar lagi; basis data sedang sibuk menulis.";
    alert(pesan);
    console.error("[NSM] gagal mengirim ubahan:", jalur, e);
  } finally {
    delete sedangMengirim[jalur];
    // The button may already be gone if muat() redrew the cards; then there is nothing to restore.
    if (tombol && tombol.isConnected) {
      tombol.disabled = false;
      tombol.classList.remove("sibuk");
    }
  }
}

function ubahAktif(d, jadiAktif, tombol) {
  var badan = { aktif: jadiAktif };

  // The reason is asked when pausing and may be left empty. An empty reason is accepted: forcing
  // one makes people type "." which is worse than empty.
  if (!jadiAktif) {
    var alasan = window.prompt(
      "Kenapa " + d.name + " dijeda?\n\n"
      + "Boleh dikosongkan, tetapi jeda tanpa alasan tidak bisa dibedakan\n"
      + "dari jeda yang terlupakan saat dibaca berminggu-minggu kemudian.\n\n"
      + "Contoh: sedang di luar lokasi · VM dimatikan untuk snapshot",
      "");
    // `null` means the dialog was cancelled, which is NOT the same as an empty reason: it means "do not pause".
    if (alasan === null) return Promise.resolve();
    badan.alasan = alasan;
  }

  return kirimUbahan("/api/devices/" + d.id + "/aktif", badan,
    "Gagal mengubah status pemantauan " + d.name + ".", tombol);
}

/*
 * Pause note for a device, or null if not paused. Three states: not paused; paused with a
 * reason (show it); paused with NO recorded reason (say so as-is, neither accusing nor hiding).
 */
function ketJeda(d) {
  if (d.aktif !== false) return null;
  var lama = d.jeda_sejak ? waktuRelatif(d.jeda_sejak) : null;
  if (d.jeda_alasan) {
    return {
      teks: d.jeda_alasan,
      sub: (lama ? "dijeda " + lama : "dijeda")
           + (d.jeda_oleh ? " oleh " + d.jeda_oleh : ""),
      tercatat: true
    };
  }
  return {
    teks: "alasan tidak tercatat",
    sub: lama ? "dijeda " + lama : "dijeda sebelum alasan mulai dicatat",
    tercatat: false
  };
}

/*
 * Duration of one neon-ring revolution, derived from ping latency on a LOGARITHMIC scale:
 * latency here spans 0.27 ms to 21 ms (78x), and a linear scale would bunch most devices at the fast end.
 */
function durasiNeon(ms) {
  var TERCEPAT = 2.5, TERLAMBAT = 9.0;      // detik per putaran
  var BATAS_BAWAH = 0.2, BATAS_ATAS = 30;
  if (typeof ms !== "number" || !isFinite(ms) || ms <= 0) return TERLAMBAT;
  var v = Math.min(Math.max(ms, BATAS_BAWAH), BATAS_ATAS);
  var bagian = (Math.log10(v) - Math.log10(BATAS_BAWAH))
             / (Math.log10(BATAS_ATAS) - Math.log10(BATAS_BAWAH));
  var detik = TERCEPAT + bagian * (TERLAMBAT - TERCEPAT);

  // Rounded to half seconds: latency jitters slightly each check, and any change of animation
  // duration makes the browser recompute the ring position so the light jumps.
  return (Math.round(detik * 2) / 2).toFixed(1) + "s";
}

/*
 * Display fingerprint of a card: everything that, if changed, requires redrawing it. Latency is
 * deliberately excluded because it changes every five seconds without changing the card's shape.
 */
function sidikKartu(d) {
  var dijeda = d.aktif === false;
  var status = dijeda ? "tanya"
             : d.is_reachable === true ? "hidup"
             : d.is_reachable === false ? "mati" : "tanya";
  var bisaSsh = !!d.platform && d.is_reachable === true && !dijeda;
  // The interface name is part of the fingerprint but the figures are not: figures are
  // overwritten in place, while a changed interface name changes the row and needs a rebuild.
  var bw = bwTerkini[String(d.id)];
  // The number of problem services is included (it decides whether the badge exists), not the list of names.
  var svc = layananTerkini[String(d.id)];
  // The pause reason is part of the fingerprint because it is written on the card.
  return [d.id, d.name, d.device_type, d.platform, status, dijeda, bisaSsh,
          bw ? bw.iface : "", svc ? svc.bermasalah : "",
          dijeda ? (d.jeda_alasan || "") : ""].join("|");
}

/*
 * Latest traffic rate per device, filled by muat(). Left empty if the request fails: a card
 * without a traffic row beats a dashboard that stops showing up/down status.
 */
var bwTerkini = {};

/* Service state per device, filled by muat(). Keys are STRINGS because JSON object keys cannot be numbers. */
var layananTerkini = {};

/*
 * Whether service state was ever fetched successfully. Distinguishes "never fetched" (say
 * nothing about services) from "fetched but this device has none" (really has no registered
 * services); otherwise a dead backend would claim that on every card.
 */
var layananPernahTerbaca = false;

/*
 * Smoothed latency per device (moving average, weight 0.25 for the new reading). Raw latency of
 * the emulated routers swings widely between checks, which would change ring speed on almost every poll.
 */
var latencyLicin = {};

function licinkanLatency(id, ms) {
  if (typeof ms !== "number" || !isFinite(ms) || ms <= 0) return null;
  var lama = latencyLicin[id];
  latencyLicin[id] = (lama === undefined) ? ms : (lama * 0.75 + ms * 0.25);
  return latencyLicin[id];
}

/*
 * Changes the ring speed without making it jump back to the start. Changing animation-duration
 * makes the browser recompute the animation from zero, so the elapsed fraction of the
 * revolution is re-applied under the new duration.
 */
function aturKecepatanNeon(kartu, id, msMentah) {
  var ms = licinkanLatency(id, msMentah);
  if (ms === null) return;

  var barunya = parseFloat(durasiNeon(ms));
  var sekarang = parseFloat(kartu.style.getPropertyValue("--durasi-neon"));

  // Threshold: differences under one second are not considered meaningful.
  if (isFinite(sekarang) && Math.abs(barunya - sekarang) < 1.0) return;

  var pecahan = 0;
  var anim = null;
  if (typeof kartu.getAnimations === "function") {
    // The ring animation is on ::after, so it must be found through the subtree.
    var semua = kartu.getAnimations({ subtree: true });
    for (var i = 0; i < semua.length; i++) {
      if (semua[i].animationName === "nsm-keliling") { anim = semua[i]; break; }
    }
    if (anim && anim.effect && typeof anim.currentTime === "number") {
      var lamaMs = anim.effect.getTiming().duration;
      if (typeof lamaMs === "number" && lamaMs > 0) {
        pecahan = (anim.currentTime % lamaMs) / lamaMs;
      }
    }
  }

  kartu.style.setProperty("--durasi-neon", barunya.toFixed(1) + "s");

  if (anim && pecahan > 0) {
    // Applied on the next frame, after the browser has applied the new duration; otherwise it would be overwritten.
    requestAnimationFrame(function () {
      try { anim.currentTime = pecahan * barunya * 1000; } catch (e) { /* abaikan */ }
    });
  }
}

/*
 * Updates traffic figures on cards whose shape did not change. The interface name is not
 * touched here: if it changes, the fingerprint changes and the card is rebuilt.
 */
function segarkanBaris(kartu, d) {
  var bw = bwTerkini[String(d.id)];
  var baris = kartu.querySelector(".baris-bw");
  if (!bw || !baris) return;

  var masuk = baris.querySelector(".bw-masuk");
  var keluar = baris.querySelector(".bw-keluar");
  if (masuk && masuk.textContent !== bw.in_teks) masuk.textContent = bw.in_teks;
  if (keluar && keluar.textContent !== bw.out_teks) keluar.textContent = bw.out_teks;
  baris.classList.toggle("basi", !!bw.basi);
}

function kartuDevice(d) {
  var dijeda = d.aktif === false;
  var status = dijeda ? "tanya"
             : d.is_reachable === true ? "hidup"
             : d.is_reachable === false ? "mati" : "tanya";
  var kartu = el("div", "kartu-device " + status + (dijeda ? " dijeda" : ""));
  kartu.dataset.id = d.id;
  kartu.dataset.sidik = sidikKartu(d);

  // The orbiting light is only for devices that are up and monitored: a down device keeps its red
  // pulse as the only attention-grabber, and a paused one has no new latency to set the speed.
  if (!dijeda && d.is_reachable === true) {
    kartu.classList.add("berputar");
    // New card: use the smoothed value if the device was seen before, so speed does not jump when a card is redrawn.
    var msAwal = licinkanLatency(d.id, d.response_time_ms);
    kartu.style.setProperty("--durasi-neon",
      durasiNeon(msAwal === null ? d.response_time_ms : msAwal));
  }

  var jenis = jenisIkon(d);
  var kepala = el("div", "kepala");

  var sorot = el("div", "sorot-ikon");
  var kotakIkon = el("span", "bungkus-ikon");
  kotakIkon.setAttribute("title", "Klik untuk rincian device");
  // A paused device is drawn neutral (gray), not green/red, because its status is unknown (it is not checked).
  kotakIkon.appendChild(ikonDevice(jenis, dijeda ? null : d.is_reachable, 54));
  kotakIkon.addEventListener("click", function (e) {
    e.stopPropagation();
    // The device card is passed so the details line up with and match the width of this card.
    // `layananTerkini` is read AT CLICK TIME, not when the card is drawn: cards persist while their
    // shape is unchanged, so capturing it earlier would freeze a stale service list. A device absent
    // from the server answer has no registered services, but only if the answer ever arrived;
    // otherwise the services section is not drawn.
    var svcDevice = layananPernahTerbaca
      ? (layananTerkini[String(d.id)]
         || { total: 0, sehat: 0, bermasalah: 0, dijeda: 0, layanan: [] })
      : undefined;
    kartuIkon(d, jenis, kotakIkon, kartu, svcDevice);
  });
  sorot.appendChild(kotakIkon);

  var teksKepala = el("div", "teks-kepala");
  var barisNama = el("div", "baris-nama");
  barisNama.appendChild(el("span", "nama", d.name));
  teksKepala.appendChild(barisNama);
  teksKepala.appendChild(el("div", "jenis", NAMA_JENIS[jenis] || jenis));
  kepala.appendChild(sorot);
  kepala.appendChild(teksKepala);
  kartu.appendChild(kepala);

  // --- status ---
  if (dijeda) {
    kartu.appendChild(el("div", "lencana-jeda", "Pemantauan dijeda"));
    // The reason, if any. Built with textContent via el(), not innerHTML: it is typed by a person and shown to others.
    var ket = ketJeda(d);
    if (ket) {
      var kotakJeda = el("div", "ket-jeda" + (ket.tercatat ? "" : " tanpa-alasan"));
      kotakJeda.appendChild(el("div", "ket-jeda-teks", ket.teks));
      kotakJeda.appendChild(el("div", "ket-jeda-sub", ket.sub));
      kartu.appendChild(kotakJeda);
    }
  } else {
    var barisStatus = el("div", "status-baris");
    barisStatus.appendChild(titikStatus(d.is_reachable));
    barisStatus.appendChild(el("b",
      status === "hidup" ? "hijau" : status === "mati" ? "merah" : "abu",
      status === "hidup" ? "UP" : status === "mati" ? "DOWN" : "Belum ada data"));
    if (d.is_reachable && d.response_time_ms !== null && d.response_time_ms !== undefined) {
      var angkaMs = el("span", "abu latency-teks", "• " + d.response_time_ms + " ms");
      jelaskan(angkaMs, "latency",
        "Cahaya yang berkeliling di tepi kartu ini bergerak mengikuti angka "
        + "tersebut: makin cepat device menjawab, makin cepat ia berputar.");
      barisStatus.appendChild(angkaMs);
    }
    kartu.appendChild(barisStatus);
  }

  // Badge: a service is down on this device. Ping only proves the MACHINE is up; a service can
  // stop without changing the ping result. The card color is deliberately unchanged, because a
  // green card is correct (the device is up) and turning it red would erase the difference
  // between "machine down" and "service down".
  var svcKartu = layananTerkini[String(d.id)];
  if (!dijeda && svcKartu && svcKartu.bermasalah > 0) {
    var lencana = el("div", "lencana-layanan",
      svcKartu.bermasalah + " layanan mati");
    var mati = svcKartu.layanan
      .filter(function (s) { return s.aktif && s.ok === false; })
      .map(function (s) {
        return s.nama + " (" + (s.jenis || "?").toUpperCase() + " " + s.port + ")";
      });
    // The wording depends on machine state. A fixed sentence ("responds to ping normally...") is
    // wrong for a down device, and "machine unreachable" can also be wrong: a device marked DOWN
    // may still answer TCP on SSH (it just does not answer ICMP). A successful service check is the
    // strongest evidence that NSM's own DOWN verdict is mistaken, so it is used here.
    var hidup = svcKartu.layanan
      .filter(function (s) { return s.aktif && s.ok === true; })
      .map(function (s) {
        return s.nama + " (" + (s.jenis || "?").toUpperCase() + " " + s.port + ")";
      });

    if (status === "mati" && hidup.length) {
      lencana.textContent = svcKartu.bermasalah + " layanan mati";
      lencana.setAttribute("data-petunjuk",
        "Kartu ini merah karena ping tidak menjawab, TETAPI layanan berikut "
        + "justru menjawab:\n" + hidup.join("\n")
        + "\n\nMesin yang menjawab koneksi TCP itu hidup. Yang kemungkinan "
        + "besar diblokir ICMP-nya (firewall), bukan mesinnya yang mati. "
        + "Periksa `sudo ufw status` di device itu.\n\nLayanan yang benar-benar "
        + "tidak menjawab:\n" + mati.join("\n"));
    } else if (status === "mati") {
      lencana.textContent = svcKartu.bermasalah + " layanan ikut tak terjangkau";
      lencana.setAttribute("data-petunjuk",
        "Mesin ini TIDAK menjawab ping, dan tidak ada satu pun layanannya yang "
        + "menjawab. Yang ikut tidak bisa dihubungi:\n" + mati.join("\n")
        + "\n\nIni belum tentu berarti layanannya rusak. Selama mesinnya tidak "
        + "terjangkau, tidak ada cara membuktikan layanan di atasnya sehat atau "
        + "tidak. Yang perlu diperbaiki lebih dulu mesinnya.");
    } else {
      lencana.setAttribute("data-petunjuk",
        "Device ini menjawab ping dengan normal, tetapi layanan berikut tidak "
        + "menjawab dengan benar:\n" + mati.join("\n")
        + "\n\nKartu tetap hijau karena mesinnya memang hidup. Klik ikon device "
        + "untuk daftar lengkapnya.");
    }
    kartu.appendChild(lencana);
  }

  // Traffic: current flow and the interface it goes through. Shows the BUSIEST interface, not the
  // sum: hosts have idle virtual adapters, and summing would give a number that answers nothing.
  var bw = bwTerkini[String(d.id)];
  if (!dijeda && bw) {
    var barisBw = el("div", "baris-bw");
    barisBw.appendChild(el("span", "iface-bw", bw.iface));

    var masuk = el("span", "arah-bw masuk");
    masuk.appendChild(el("span", "panah", "↓"));
    masuk.appendChild(el("span", "nilai bw-masuk", bw.in_teks));
    barisBw.appendChild(masuk);

    var keluar = el("span", "arah-bw keluar");
    keluar.appendChild(el("span", "panah", "↑"));
    keluar.appendChild(el("span", "nilai bw-keluar", bw.out_teks));
    barisBw.appendChild(keluar);

    // The raw value, interface count, and source go in the hover text; a single Mbps unit would show small traffic as 0.000.
    var ket = "Masuk " + (bw.in_asli || "-") + ", keluar " + (bw.out_asli || "-")
            + ", pada interface " + bw.iface + ".";
    if (bw.jumlah_iface > 1) {
      ket += " Ini interface tersibuk dari " + bw.jumlah_iface
           + " interface yang terbaca; rinciannya ada di halaman Riwayat.";
    }
    if (bw.source) {
      ket += " Dibaca lewat " + bw.source
           + (bw.source === "ssh" ? " (jalur cadangan, SNMP tidak menjawab)" : "") + ".";
    }
    if (bw.basi) {
      // Stale readings are stated plainly: an old figure shown like a live one is how a dashboard lies.
      barisBw.classList.add("basi");
      ket += " Bacaan terakhir sudah " + bw.umur_detik
           + " detik lalu, jadi belum tentu mewakili keadaan sekarang.";
    }
    barisBw.setAttribute("data-petunjuk", ket);
    kartu.appendChild(barisBw);
  }

  // IP, location and check time are deliberately not shown on the card; they are in the details shown on click.

  // SSH data only for devices that have a platform AND are up; for a down device it would just wait for a connection that must fail.
  var bisaSsh = !!d.platform && d.is_reachable === true && !dijeda;
  var tombol = el("div", "aksi-kartu");
  tombol.appendChild(tautan("Riwayat", "/report/device/" + d.id + "?period=24h"));

  /*
   * The label follows HOW the data is actually fetched. A device with platform "lokal" is read
   * directly from this machine without SSH, and labeling it "SSH data" would misstate the access path.
   */
  var lokal = d.platform === "lokal";
  var ssh = tautan(lokal ? "Data Lokal" : "Data SSH",
                   bisaSsh ? "/device/" + d.id + "/ssh" : "#",
                   "utama" + (bisaSsh ? "" : " mati-tombol"));
  if (!bisaSsh) {
    ssh.setAttribute("title", dijeda
      ? "Pemantauan device ini sedang dijeda"
      : !d.platform
        ? "Device ini belum punya platform, jadi tidak bisa diakses lewat SSH"
        : "Device sedang tidak merespons");
  }
  tombol.appendChild(ssh);

  // The pause button is for admins only. The backend also rejects it, so hiding the button is cosmetic, not the only guard.
  if (ADMIN) {
    var jeda = tombolIkon(
      dijeda ? "lanjut" : "jeda",
      dijeda
        ? "Lanjutkan pemantauan " + d.name
        : "Jeda pemantauan " + d.name + " (riwayat lama tetap tersimpan)",
      "jeda");
    jeda.addEventListener("click", function (e) {
      e.stopPropagation();
      ubahAktif(d, dijeda, jeda);
    });
    tombol.appendChild(jeda);
  }

  kartu.appendChild(tombol);
  return kartu;
}

// Cursor-following spotlight. JavaScript only sets two CSS variables (--x, --y) and CSS draws
// the radial gradient there. The position chases the cursor each frame instead of jumping, and
// one listener on the container serves all cards; style writes are deferred to
// requestAnimationFrame, at most once per frame.
var kartuDisorot = null;
var tujuanX = 50, tujuanY = 50;
var kiniX = 50, kiniY = 50;
var rafJalan = false;

var tanpaAnimasi = window.matchMedia
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function langkahCahaya() {
  if (!kartuDisorot) { rafJalan = false; return; }
  // 0.16 = seberapa cepat mengejar. Makin kecil makin lembut & lambat.
  kiniX += (tujuanX - kiniX) * 0.16;
  kiniY += (tujuanY - kiniY) * 0.16;
  kartuDisorot.style.setProperty("--x", kiniX.toFixed(2) + "%");
  kartuDisorot.style.setProperty("--y", kiniY.toFixed(2) + "%");
  // Stop once close enough; sub-pixel differences are invisible.
  if (Math.abs(tujuanX - kiniX) < 0.2 && Math.abs(tujuanY - kiniY) < 0.2) {
    rafJalan = false;
    return;
  }
  requestAnimationFrame(langkahCahaya);
}

function pasangCahaya() {
  var wadah = document.getElementById("kartu-kotak");
  if (!wadah || tanpaAnimasi) return;

  wadah.addEventListener("pointermove", function (e) {
    var kartu = e.target.closest(".kartu-device");
    if (!kartu) return;
    if (kartu !== kartuDisorot) {
      // Switching cards: start from the cursor position instead of dragging from the old card.
      kartuDisorot = kartu;
      var r0 = kartu.getBoundingClientRect();
      kiniX = (e.clientX - r0.left) / r0.width * 100;
      kiniY = (e.clientY - r0.top) / r0.height * 100;
    }
    var r = kartu.getBoundingClientRect();
    tujuanX = (e.clientX - r.left) / r.width * 100;
    tujuanY = (e.clientY - r.top) / r.height * 100;
    if (!rafJalan) { rafJalan = true; requestAnimationFrame(langkahCahaya); }
  });

  wadah.addEventListener("pointerleave", function () {
    kartuDisorot = null;
  });

  /*
   * A cursor resting on a card fires no pointermove. Since cards now persist, a card replaced
   * under a stationary cursor would leave its light at the center, so the last position is
   * remembered and restored to whichever card is under the cursor after a redraw.
   */
  wadah.addEventListener("pointermove", function (e) {
    posisiKursor.x = e.clientX;
    posisiKursor.y = e.clientY;
  }, { passive: true });
}

var posisiKursor = { x: null, y: null };

/* Called after the card list is updated: finds the card under the cursor and lights it at that point. */
function pulihkanCahaya() {
  if (tanpaAnimasi || posisiKursor.x === null) return;
  var bawah = document.elementFromPoint(posisiKursor.x, posisiKursor.y);
  var kartu = bawah && bawah.closest ? bawah.closest(".kartu-device") : null;
  if (!kartu) { kartuDisorot = null; return; }
  if (kartu === kartuDisorot) return;

  kartuDisorot = kartu;
  var r = kartu.getBoundingClientRect();
  kiniX = tujuanX = (posisiKursor.x - r.left) / r.width * 100;
  kiniY = tujuanY = (posisiKursor.y - r.top) / r.height * 100;
  kartu.style.setProperty("--x", kiniX.toFixed(2) + "%");
  kartu.style.setProperty("--y", kiniY.toFixed(2) + "%");
}

async function muat() {
  try {
    // Three requests at once, but only ONE may fail the page: device up/down status is the point of
    // the dashboard; traffic and service data are extras, and their failures are caught locally.
    var [data, bw, svc] = await Promise.all([
      ambilJson("/api/devices"),
      ambilJson("/api/devices/bandwidth-terkini").catch(function (e) {
        console.warn("[NSM] lalu lintas terkini tidak bisa diambil:", e);
        return null;
      }),
      // Uses the "ringkas" endpoint, not /api/services: only current up/down is needed, and
      // /api/services computes availability over the whole period, wasteful every five seconds.
      ambilJson("/api/services/ringkas").catch(function (e) {
        console.warn("[NSM] keadaan layanan tidak bisa diambil:", e);
        return null;
      })
    ]);
    if (bw && bw.devices) bwTerkini = bw.devices;
    if (svc && svc.per_device) {
      layananTerkini = svc.per_device;
      layananPernahTerbaca = true;
    }

    var kotak = document.getElementById("kartu-kotak");
    var pertamaKali = !kotak.dataset.pernahDigambar;

    /*
     * Cards are updated in place, not rebuilt. Rebuilding every five seconds restarted the neon
     * ring, reset the spotlight, and dropped text selection. Cards are matched by device id; if the
     * shape (name, status, paused) is unchanged only latency and ring speed are updated, otherwise
     * (for example UP to DOWN) the card is rebuilt, where a flash is useful.
     */
    var lama = {};
    Array.prototype.forEach.call(kotak.children, function (k) {
      if (k.dataset && k.dataset.id) lama[k.dataset.id] = k;
    });

    var up = 0, dipantau = 0, dijeda = 0;
    var urut = [];

    data.forEach(function (d, urutan) {
      if (d.aktif === false) dijeda++;
      else { dipantau++; if (d.is_reachable) up++; }

      var kunci = String(d.id);
      var kartu = lama[kunci];

      if (kartu && kartu.dataset.sidik === sidikKartu(d)) {
        var teksMs = kartu.querySelector(".latency-teks");
        if (teksMs && typeof d.response_time_ms === "number") {
          var baru = "• " + d.response_time_ms + " ms";
          if (teksMs.textContent !== baru) teksMs.textContent = baru;
        }
        if (kartu.classList.contains("berputar")) {
          aturKecepatanNeon(kartu, d.id, d.response_time_ms);
        }
        // Traffic figures are overwritten in place, like latency; rebuilding the card would restart the ring animation every five seconds.
        segarkanBaris(kartu, d);
      } else {
        var pengganti = kartuDevice(d);
        if (pertamaKali) {
          pengganti.classList.add("muncul");
          // Staggered delay so cards enter in sequence.
          pengganti.style.animationDelay = (Math.min(urutan, 8) * 45) + "ms";
        }
        if (kartu) {
          // A card under the cursor disappears together with its element.
          if (kartuDisorot === kartu) kartuDisorot = null;
          kotak.replaceChild(pengganti, kartu);
        }
        kartu = pengganti;
      }

      urut.push(kartu);
      delete lama[kunci];
    });

    // Devices no longer in the list are removed.
    Object.keys(lama).forEach(function (k) {
      if (kartuDisorot === lama[k]) kartuDisorot = null;
      lama[k].remove();
    });

    // Match the server order, touching only cards that are out of place; moving correctly placed elements has a cost and can disturb running animations.
    urut.forEach(function (k, i) {
      if (kotak.children[i] !== k) kotak.insertBefore(k, kotak.children[i] || null);
    });

    /*
     * Empty device list. Without this branch the dashboard is a blank page, indistinguishable from a
     * broken one on a fresh install before any `devices` row exists.
     */
    var kosong = document.getElementById("dashboard-kosong");
    if (data.length === 0) {
      if (!kosong) {
        kosong = el("div", "kosong");
        kosong.id = "dashboard-kosong";
        kosong.appendChild(el("div", "kosong-judul", "Belum ada device yang dipantau"));
        kosong.appendChild(el("div", null,
          "NSM membaca daftar perangkat dari tabel devices di nsm.db. "
          + "Menambah perangkat berarti menambah baris di sana, bukan mengubah kode."));
        kosong.appendChild(el("div", "kosong-perintah",
          "cd backend  →  py init_db.py"));
        kotak.parentNode.insertBefore(kosong, kotak.nextSibling);
      }
    } else if (kosong) {
      kosong.remove();
    }

    kotak.dataset.pernahDigambar = "1";
    pulihkanCahaya(); // card replaced while the cursor rests on it

    /*
     * Summary per location, in the summary row only. With two locations "10 of 10 UP" hides which
     * SIDE has a problem. Grouping is done in the summary row rather than by splitting the card
     * container, because cards update in place and their animation depends on their DOM position.
     */
    var perLokasi = {};
    data.forEach(function (d) {
      if (d.aktif === false) return;
      var lok = d.location || "Tanpa lokasi";
      if (!perLokasi[lok]) perLokasi[lok] = { total: 0, up: 0 };
      perLokasi[lok].total++;
      if (d.is_reachable) perLokasi[lok].up++;
    });
    var potongan = Object.keys(perLokasi).sort().map(function (lok) {
      var a = perLokasi[lok];
      // Full ones are named briefly, others show their count, so the eye goes to the problem side.
      return lok + " " + (a.up === a.total ? a.total + " UP"
                                           : a.up + "/" + a.total + " UP");
    });

    document.getElementById("meta").textContent =
      up + " dari " + dipantau + " device UP" +
      (dijeda ? ", " + dijeda + " dijeda" : "") +
      (potongan.length > 1 ? "  ·  " + potongan.join("  ·  ") : "") +
      " · diperbarui " + new Date().toLocaleTimeString("id-ID");
  } catch (e) {
    // Distinguishes three causes that need different actions: session expired (log in again),
    // backend down (start uvicorn), or this page itself broken (open the Console).
    var pesan;
    if (e && e.sesiHabis) {
      pesan = e.message;
    } else if (e instanceof TypeError && String(e.message).indexOf("fetch") >= 0) {
      pesan = "Gagal terhubung ke backend";
    } else {
      pesan = "Data diterima, tetapi halaman gagal menggambarnya: " + e.message;
    }
    document.getElementById("meta").textContent = pesan;
    console.error("[NSM] gagal memuat dashboard:", e);
  }
}

pasangCahaya();
muat();

/*
 * Refresh pauses while the tab is hidden: dashboards stay open all day, and each request goes
 * through Java, Python and the database on a shared machine. On return, data is fetched once immediately.
 */
setInterval(function () {
  if (!document.hidden) muat();
}, 5000);

document.addEventListener("visibilitychange", function () {
  if (!document.hidden) muat();
});
