"""Export part of report_service: CSV reports."""
from datetime import datetime

from ._inti import (PEMISAH, PERIODE_NAMA, ringkasan, riwayat_device)



def _bisa_dianggap_rumus(teks):
    """Would Excel interpret this cell as a formula rather than text?

    Cells starting with = + - @ are formulas, but not all are dangerous:
    "-" (meaning none) and "-12,5" (a negative number) stay as they are;
    "=cmd|" must be neutralized. Escaping everything would turn a plain hyphen
    into '- and make negative numbers uncountable.
    """
    if teks[:1] not in ("=", "+", "-", "@"):
        return False
    if teks in ("-", "+"):
        return False
    try:
        float(teks.replace(",", ".").lstrip("+-"))
        return False          # angka biasa, aman dibiarkan
    except ValueError:
        return True


def _sel(nilai):
    """Prepare one CSV cell: quote if needed and neutralize potential formulas."""
    if nilai is None:
        return ""
    teks = str(nilai)
    if _bisa_dianggap_rumus(teks):
        # A leading single quote forces Excel to read the cell as text.
        teks = "'" + teks
    if any(c in teks for c in (PEMISAH, '"', "\n", "\r")):
        teks = '"' + teks.replace('"', '""') + '"'
    return teks


def _baris(*nilai):
    return PEMISAH.join(_sel(v) for v in nilai)


def _angka(nilai, desimal=2):
    """Number with a decimal comma, as Indonesian Excel expects."""
    if nilai is None:
        return ""
    return f"{nilai:.{desimal}f}".replace(".", ",")


def csv_availability(db, period):
    """Availability report for all devices in one CSV file."""
    data = ringkasan(db, period)
    sekarang = datetime.now()
    line = [
        _baris("Laporan Availability NSM"),
        _baris("Periode", PERIODE_NAMA.get(data["periode"], data["periode"])),
        _baris("Benar-benar dipantau", data.get("diamati_teks", "-")),
        _baris("Dibuat pada", sekarang.strftime("%d %B %Y %H:%M:%S")),
        "",
        _baris("RINGKASAN"),
        _baris("Device hidup", f"{data['device_up']} dari {data['total_device']}"),
        _baris("Device dijeda", data.get("device_dijeda", 0)),
        _baris("Availability keseluruhan (%)", _angka(data["availability_rata"], 3)),
        _baris("Insiden gangguan", data["insiden_total"]),
        _baris("Total waktu down", data["total_down_teks"]),
        _baris("MTTR (rata-rata waktu pulih)", data["mttr_teks"]),
        _baris("Latency rata-rata (ms)", _angka(data["latency_rata_ms"])),
        "",
        _baris("RINCIAN PER DEVICE"),
        _baris("Status", "Device", "Alamat IP", "Tipe", "Lokasi",
               "Availability (%)", "Insiden", "Total down (detik)",
               "Total down", "Latency rata-rata (ms)", "Dipantau sejak",
               "Terakhir dicek"),
    ]

    for d in data.get("devices_semua", data["devices"]):
        if not d.get("aktif", True):
            status = "DIJEDA"
        elif d["is_reachable"] is True:
            status = "UP"
        elif d["is_reachable"] is False:
            status = "DOWN"
        else:
            status = "BELUM ADA DATA"
        line.append(_baris(
            status, d["name"], d["ip_address"], d["device_type"] or "-",
            d["location"] or "-", _angka(d["availability"], 3), d["insiden"],
            d["total_down_detik"], d["total_down_teks"],
            _angka(d["avg_latency_ms"]),
            (d["dipantau_sejak"] or "").replace("T", " ")[:19] or "-",
            (d["last_checked"] or "").replace("T", " ")[:19] or "-",
        ))

    line += [
        "",
        _baris("Catatan"),
        _baris("Availability dihitung dari lama pemantauan yang sebenarnya, "
               "bukan diandaikan periode penuh."),
        _baris("Kategori sebab berasal dari probe otomatis saat ping gagal. "
               "Sebab fisik (listrik, kabel, perangkat hang) tidak bisa "
               "dideteksi dari jaringan."),
        _baris("Device yang dijeda tidak ikut menghitung angka keseluruhan."),
    ]
    return "﻿" + "\r\n".join(line) + "\r\n"


def csv_riwayat(db, device_id, period):
    """Outage history of one device in one CSV file."""
    data = riwayat_device(db, device_id, period, limit=5000)
    if data.get("error"):
        return "﻿" + _baris("Kesalahan", data["error"]) + "\r\n"

    d = data["device"]
    r = data["ringkasan"]
    sekarang = datetime.now()
    line = [
        _baris("Riwayat Gangguan Device NSM"),
        _baris("Device", d["name"]),
        _baris("Alamat IP", d["ip_address"]),
        _baris("Tipe", d["device_type"] or "-"),
        _baris("Lokasi", d["location"] or "-"),
        _baris("Platform", d["platform"] or "belum diisi"),
        _baris("Periode", PERIODE_NAMA.get(data["periode"], data["periode"])),
        _baris("Dipantau sejak", (data["dipantau_sejak"] or "").replace("T", " ")[:19] or "-"),
        _baris("Dibuat pada", sekarang.strftime("%d %B %Y %H:%M:%S")),
        "",
        _baris("RINGKASAN"),
        _baris("Availability (%)", _angka(r["availability"], 3)),
        _baris("Jumlah gangguan", r["insiden"]),
        _baris("Total waktu down", r["total_down_teks"]),
        _baris("MTTR", r.get("mttr_teks", "-")),
        _baris("Latency rata-rata (ms)", _angka(data.get("avg_latency_ms"))),
        "",
        _baris("DAFTAR GANGGUAN"),
        _baris("No", "Mulai down", "Pulih", "Lama (detik)", "Lama gangguan",
               "Kategori", "Keterangan"),
    ]

    for i, g in enumerate(data["riwayat"], 1):
        line.append(_baris(
            i,
            g["mulai"].replace("T", " ")[:19],
            "belum pulih" if g["berlangsung"] else g["selesai"].replace("T", " ")[:19],
            g["durasi_detik"],
            g["durasi_teks"] + (" (masih berlangsung)" if g["berlangsung"] else ""),
            g["kategori_teks"],
            g["detail"] or "-",
        ))

    if not data["riwayat"]:
        line.append(_baris("", "Tidak ada gangguan pada periode ini"))
    return "﻿" + "\r\n".join(line) + "\r\n"


def nama_berkas(awalan, tambahan=None):
    """Download file name: letters, digits, and hyphens only."""
    section = [awalan]
    if tambahan:
        clean = "".join(c if c.isalnum() else "-" for c in str(tambahan))
        clean = "-".join(x for x in clean.split("-") if x)
        if clean:
            section.append(clean)
    section.append(datetime.now().strftime("%Y%m%d-%H%M"))
    return "-".join(section) + ".csv"
