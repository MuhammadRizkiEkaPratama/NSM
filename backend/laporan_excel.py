"""NSM report as a formatted Excel (.xlsx) file.

Style: black Times New Roman body with thin BSP green accents. There are no status
colors (green/red); emphasis uses bold text and box borders, so the report prints
well and does not look like automatic template output.

Consequence: without red for DOWN, readers tell status apart by its TEXT (`DOWN`,
`DIJEDA`) rather than by color, so the status column is bold to stay prominent when
scanned.

The report has 6 sheets:
  1. `Ringkasan`          key figures on one page
  2. `Per Device`         availability of each device
  3. `Daftar Gangguan`    all incidents, newest first
  4. `Bandwidth`          traffic per interface (SNMP/SSH)
  5. `Statistik Latency`  average, minimum, maximum ping per device
  6. `Log Event`          raw UP/DOWN transitions for investigation

Three things make the file pleasant to use, not just full of data:
* Numbers are stored as numbers (percent, dates, latency) via number_format rather
  than as text, so they can be sorted and summed directly.
* The header row is frozen and has a filter.
* Column widths are computed from the longest content, not guessed.
"""
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import report_service as rs

# Style: black Times New Roman body with a BSP green accent. `BSP_HIJAU` is the
# official theme color of the company website, used sparingly: title, table header
# row, section labels, and lines. Table bodies stay black so numbers are easiest to
# read and print.
FONT = "Times New Roman"
HITAM = "000000"
PUTIH = "FFFFFF"
BSP_HIJAU = "2B6049"
GARIS = "9BB3A8"  # soft grayish green for table borders

garis_tipis = Side(style="thin", color=GARIS)
KOTAK = Border(left=garis_tipis, right=garis_tipis,
               top=garis_tipis, bottom=garis_tipis)


def F(size=11, bold=False, italic=False, color=HITAM):
    """Single entry point for fonts, so the WHOLE file uses Times New Roman. openpyxl
    defaults to Calibri, so a cell whose font name is left unset would deviate.
    """
    return Font(name=FONT, size=size, bold=bold, italic=italic, color=color)


def _judul_lembar(ws, teks, lebar_gabung, baris=1):
    ws.merge_cells(start_row=baris, start_column=1,
                   end_row=baris, end_column=lebar_gabung)
    sel = ws.cell(row=baris, column=1, value=teks)
    sel.font = F(15, bold=True, color=BSP_HIJAU)
    sel.alignment = Alignment(vertical="center")
    ws.row_dimensions[baris].height = 24
    return baris + 1


def _keterangan(ws, baris, teks):
    """Small caption row under the sheet title."""
    sel = ws.cell(row=baris, column=1, value=teks)
    sel.font = F(9)
    return sel


def _baris_info(ws, baris, label, nilai, lebar_gabung):
    lab = ws.cell(row=baris, column=1, value=label)
    lab.font = F(bold=True)
    sel = ws.cell(row=baris, column=2, value=nilai)
    sel.font = F()
    if lebar_gabung > 2:
        ws.merge_cells(start_row=baris, start_column=2,
                       end_row=baris, end_column=lebar_gabung)
    return sel


def _kepala_tabel(ws, baris, judul_kolom):
    for i, teks in enumerate(judul_kolom, 1):
        sel = ws.cell(row=baris, column=i, value=teks)
        sel.font = F(bold=True, color=PUTIH)
        sel.fill = PatternFill("solid", fgColor=BSP_HIJAU)
        sel.alignment = Alignment(horizontal="center", vertical="center",
                                  wrap_text=True)
        sel.border = KOTAK
    ws.row_dimensions[baris].height = 30
    return baris + 1


def _lebarkan(ws, dari=1, lebar_minimum=9, lebar_maksimum=42):
    """Column widths follow the longest content, computed ONLY from table rows.

    `dari` = the header row. Rows above it (sheet title, notes) are ignored on purpose:
    a long sentence in column A would widen the whole column to dozens of characters
    when the table only holds a row number there. Merged cells are skipped for the same
    reason, since their text is meant to span several columns.
    """
    gabungan = set()
    for rentang in ws.merged_cells.ranges:
        for baris in ws[rentang.coord]:
            for sel in baris:
                gabungan.add(sel.coordinate)

    length = {}
    for baris in ws.iter_rows(min_row=dari):
        for sel in baris:
            if sel.value is None or sel.coordinate in gabungan:
                continue
            n = 19 if isinstance(sel.value, datetime) else len(str(sel.value))
            if n > length.get(sel.column, 0):
                length[sel.column] = n
    for kolom, n in length.items():
        ws.column_dimensions[get_column_letter(kolom)].width = \
            max(lebar_minimum, min(lebar_maksimum, n + 2))


def _waktu(iso):
    """Convert ISO text to a datetime so Excel recognizes it as a date."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)[:19])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Lembar 1 — Ringkasan
# ---------------------------------------------------------------------------
def _lembar_ringkasan(wb, data, dibuat_oleh):
    ws = wb.active
    ws.title = "Ringkasan"
    b = _judul_lembar(ws, "Laporan Ketersediaan Perangkat Jaringan NSM", 4)
    b += 1

    for label, nilai in [
        ("Periode", rs.PERIODE_NAMA.get(data["periode"], data["periode"])),
        # Shortest window among all devices. If the windows differ a lot, the range is stated:
        # a single figure would read as valid for every device when it is not.
        ("Benar-benar dipantau",
         (data.get("diamati_teks", "-") + " s.d. " + data.get("diamati_maks_teks", "-")
          + " (berbeda tiap perangkat)")
         if data.get("diamati_beragam") else data.get("diamati_teks", "-")),
        ("Dibuat pada", datetime.now()),
        ("Dibuat oleh", dibuat_oleh or "-"),
    ]:
        sel = _baris_info(ws, b, label, nilai, 4)
        if isinstance(nilai, datetime):
            sel.number_format = "dd mmmm yyyy hh:mm"
        b += 1

    b += 1
    lab = ws.cell(row=b, column=1, value="ANGKA UTAMA")
    lab.font = F(12, bold=True, color=BSP_HIJAU)
    b += 1
    kepala = b
    b = _kepala_tabel(ws, b, ["Keterangan", "Nilai", "Catatan"])

    content = [
        ("Device hidup saat laporan dibuat",
         f"{data['device_up']} dari {data['total_device']}",
         "Device yang dijeda tidak ikut dihitung"),
        ("Device dijeda", data.get("device_dijeda", 0),
         "Sengaja tidak dipantau, riwayat lamanya tetap tersimpan"),
        ("Availability keseluruhan", data["availability_rata"],
         "Rata-rata seluruh device aktif pada periode ini"),
        ("Jumlah gangguan", data["insiden_total"], ""),
        ("Total waktu tidak merespons", data["total_down_teks"], ""),
        ("MTTR (rata-rata waktu pulih)", data["mttr_teks"],
         "Total waktu pulih dibagi jumlah gangguan yang sudah selesai"),
        ("Latency rata-rata (ms)", data["latency_rata_ms"], ""),
        ("Device paling bermasalah",
         (data["top_offender"]["name"] + " (" +
          str(data["top_offender"]["insiden"]) + "x)")
         if data.get("top_offender") else "Tidak ada gangguan", ""),
        ("Tanpa gangguan selama", data.get("uptime_streak_teks", "-"), ""),
    ]
    for label, nilai, catatan in content:
        c1 = ws.cell(row=b, column=1, value=label)
        c1.border = KOTAK
        c1.font = F()
        sel = ws.cell(row=b, column=2, value=nilai)
        sel.border = KOTAK
        sel.font = F()
        sel.alignment = Alignment(horizontal="right")
        if label.startswith("Availability"):
            sel.number_format = '0.000"%"'
            sel.font = F(bold=True)
        elif label.startswith("Latency"):
            sel.number_format = "0.00"
        c = ws.cell(row=b, column=3, value=catatan)
        c.border = KOTAK
        c.font = F(9)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        b += 1

    ws.freeze_panes = ws.cell(row=kepala + 1, column=1)
    _lebarkan(ws)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["C"].width = 46
    return ws


# ---------------------------------------------------------------------------
# Lembar 2 — Rincian per device
# ---------------------------------------------------------------------------
def _lembar_device(wb, data):
    ws = wb.create_sheet("Per Device")
    b = _judul_lembar(ws, "Rincian per Device", 12)
    b += 1
    kepala = b
    b = _kepala_tabel(ws, b, [
        "Status", "Device", "Alamat IP", "Tipe", "Lokasi", "Availability (%)",
        "Gangguan", "Total tidak merespons (detik)", "Total tidak merespons",
        "Latency rata-rata (ms)", "Dipantau sejak", "Terakhir dicek",
    ])

    for d in data.get("devices_semua", data["devices"]):
        if not d.get("aktif", True):
            status = "DIJEDA"
        elif d["is_reachable"] is True:
            status = "UP"
        elif d["is_reachable"] is False:
            status = "DOWN"
        else:
            status = "BELUM ADA DATA"

        nilai = [
            status, d["name"], d["ip_address"], d["device_type"] or "-",
            d["location"] or "-", d["availability"], d["insiden"],
            d["total_down_detik"], d["total_down_teks"], d["avg_latency_ms"],
            _waktu(d.get("dipantau_sejak")), _waktu(d.get("last_checked")),
        ]
        for i, v in enumerate(nilai, 1):
            sel = ws.cell(row=b, column=i, value=v)
            sel.border = KOTAK
            sel.font = F()
            if i == 1:
                sel.font = F(bold=True)
                sel.alignment = Alignment(horizontal="center")
            elif i == 6:
                sel.number_format = '0.000'
                # Availability below 99% is bolded instead of colored red.
                sel.font = F(bold=(v is not None and v < 99))
            elif i == 10:
                sel.number_format = "0.00"
            elif i in (11, 12):
                sel.number_format = "dd/mm/yyyy hh:mm:ss"
            elif i in (7, 8):
                sel.alignment = Alignment(horizontal="right")
        b += 1

    ws.freeze_panes = ws.cell(row=kepala + 1, column=3)
    ws.auto_filter.ref = f"A{kepala}:L{b - 1}"
    _lebarkan(ws, dari=kepala)
    # Charts go BELOW the table, not beside it: the number of devices can grow, and a
    # chart anchored at column N would be overwritten once the table widens.
    _grafik_per_device(ws, kepala, b - 1, 2, 6, f"A{b + 2}")
    return ws


# ---------------------------------------------------------------------------
# Lembar 3 — Daftar gangguan
# ---------------------------------------------------------------------------
def _lembar_gangguan(wb, db, data, period):
    ws = wb.create_sheet("Daftar Gangguan")
    b = _judul_lembar(ws, "Daftar Gangguan", 8)
    _keterangan(ws, b, "Urut dari yang terbaru. Sebab diambil dari pemeriksaan "
                       "otomatis saat ping gagal.")
    b += 2
    kepala = b
    b = _kepala_tabel(ws, b, [
        "No", "Device", "Alamat IP", "Mulai tidak merespons", "Pulih",
        "Lama (detik)", "Lama", "Penyebab menurut pemeriksaan",
    ])

    semua = []
    for d in data.get("devices_semua", data["devices"]):
        riwayat = rs.riwayat_device(db, d["id"], period, limit=1000)
        for g in riwayat.get("riwayat", []):
            semua.append((d, g))
    semua.sort(key=lambda x: x[1]["mulai"], reverse=True)

    for i, (d, g) in enumerate(semua, 1):
        nilai = [
            i, d["name"], d["ip_address"], _waktu(g["mulai"]),
            None if g["berlangsung"] else _waktu(g["selesai"]),
            g["durasi_detik"],
            g["durasi_teks"] + (" (masih berlangsung)" if g["berlangsung"] else ""),
            g["kategori_teks"],
        ]
        for k, v in enumerate(nilai, 1):
            sel = ws.cell(row=b, column=k, value=v)
            sel.border = KOTAK
            sel.font = F()
            if k in (4, 5):
                sel.number_format = "dd/mm/yyyy hh:mm:ss"
            elif k == 6:
                sel.alignment = Alignment(horizontal="right")
            elif k == 8:
                sel.alignment = Alignment(wrap_text=True, vertical="top")
                sel.font = F(9)
        if g["berlangsung"]:
            sel = ws.cell(row=b, column=5, value="belum pulih")
            sel.font = F(italic=True)
            sel.number_format = "General"
        b += 1

    if not semua:
        c = ws.cell(row=b, column=1, value="Tidak ada gangguan pada periode ini")
        c.font = F(italic=True)

    ws.freeze_panes = ws.cell(row=kepala + 1, column=1)
    if semua:
        ws.auto_filter.ref = f"A{kepala}:H{b - 1}"
    _lebarkan(ws, dari=kepala)
    ws.column_dimensions["H"].width = 52
    return ws


# ---------------------------------------------------------------------------
# Lembar 4 — Bandwidth per interface
# ---------------------------------------------------------------------------
def _lembar_bandwidth(wb, db, devices, period):
    ws = wb.create_sheet("Bandwidth")
    b = _judul_lembar(ws, "Bandwidth per Interface", 10)
    _keterangan(ws, b, "Laju lalu lintas tiap interface. Hanya perangkat yang "
                       "punya kredensial SNMP atau SSH yang bisa dibaca.")
    b += 2
    kepala = b
    b = _kepala_tabel(ws, b, [
        "Device", "Interface", "In terakhir", "Out terakhir",
        "In rata-rata", "Out rata-rata", "In puncak", "Out puncak",
        "Jumlah sampel", "Sumber",
    ])

    exists = False
    for d in devices:
        bw = rs.bandwidth_device(db, d["id"], period)
        if not bw.get("didukung"):
            continue
        for it in bw.get("interfaces", []):
            exists = True
            nilai = [
                d["name"], it["iface"], it["in_teks"], it["out_teks"],
                it["in_rata_teks"], it["out_rata_teks"],
                it["in_puncak_teks"], it["out_puncak_teks"],
                it["jumlah_sampel"], it.get("source") or "-",
            ]
            for k, v in enumerate(nilai, 1):
                sel = ws.cell(row=b, column=k, value=v)
                sel.border = KOTAK
                sel.font = F()
                if 3 <= k <= 9:
                    sel.alignment = Alignment(horizontal="right")
            b += 1

    if not exists:
        c = ws.cell(row=b, column=1,
                    value="Belum ada data bandwidth pada periode ini.")
        c.font = F(italic=True)

    ws.freeze_panes = ws.cell(row=kepala + 1, column=1)
    if exists:
        ws.auto_filter.ref = f"A{kepala}:J{b - 1}"
    _lebarkan(ws, dari=kepala)
    return ws


# ---------------------------------------------------------------------------
# Lembar 5 — Statistik latency
# ---------------------------------------------------------------------------
def _lembar_latency(wb, db, devices, period):
    ws = wb.create_sheet("Statistik Latency")
    mulai, _finish, _label = rs.rentang(period)
    b = _judul_lembar(ws, "Statistik Latency", 7)
    _keterangan(ws, b, "Dihitung dari seluruh ping yang berhasil pada periode. "
                       "Perangkat yang tidak pernah merespons tidak punya angka.")
    b += 2
    kepala = b
    b = _kepala_tabel(ws, b, [
        "Device", "Alamat IP", "Saat ini (ms)", "Rata-rata (ms)",
        "Minimum (ms)", "Maksimum (ms)", "Jumlah sampel",
    ])

    for d in devices:
        stat = rs.statistik_latency(db, d["id"], mulai)
        nilai = [
            d["name"], d["ip_address"], d.get("response_time_ms"),
            stat["rata_ms"], stat["min_ms"], stat["max_ms"],
            stat["jumlah_sampel"],
        ]
        for k, v in enumerate(nilai, 1):
            sel = ws.cell(row=b, column=k, value=v)
            sel.border = KOTAK
            sel.font = F()
            if 3 <= k <= 6:
                sel.number_format = "0.00"
                sel.alignment = Alignment(horizontal="right")
            elif k == 7:
                sel.alignment = Alignment(horizontal="right")
        b += 1

    ws.freeze_panes = ws.cell(row=kepala + 1, column=1)
    ws.auto_filter.ref = f"A{kepala}:G{b - 1}"
    _lebarkan(ws, dari=kepala)
    return ws


# ---------------------------------------------------------------------------
# Lembar 6 — Log event mentah
# ---------------------------------------------------------------------------
def _lembar_event(wb, db, devices, period):
    ws = wb.create_sheet("Log Event")
    b = _judul_lembar(ws, "Log Event (Mentah)", 8)
    _keterangan(ws, b, "Semua transisi UP/DOWN dan baris awal pemantauan apa "
                       "adanya, terbaru di atas. Untuk penelusuran per kejadian.")
    b += 2
    kepala = b
    b = _kepala_tabel(ws, b, [
        "No", "Device", "Waktu", "Tipe", "Lama", "Kategori",
        "Keterangan", "RTT terakhir (ms)",
    ])

    semua = []
    for d in devices:
        ev = rs.event_mentah(db, d["id"], period, limit=500)
        for e in ev.get("events", []):
            semua.append((d, e))
    semua.sort(key=lambda x: x[1]["timestamp"] or "", reverse=True)

    for i, (d, e) in enumerate(semua, 1):
        nilai = [
            i, d["name"], _waktu(e["timestamp"]), e["event_type"],
            e["duration_teks"], e["kategori_teks"],
            e.get("detail") or "-", e.get("last_rtt_ms"),
        ]
        for k, v in enumerate(nilai, 1):
            sel = ws.cell(row=b, column=k, value=v)
            sel.border = KOTAK
            sel.font = F()
            if k == 3:
                sel.number_format = "dd/mm/yyyy hh:mm:ss"
            elif k == 4:
                sel.font = F(bold=True)
                sel.alignment = Alignment(horizontal="center")
            elif k == 7:
                sel.alignment = Alignment(wrap_text=True, vertical="top")
                sel.font = F(9)
            elif k == 8:
                sel.number_format = "0.00"
                sel.alignment = Alignment(horizontal="right")
        b += 1

    if not semua:
        c = ws.cell(row=b, column=1, value="Tidak ada event pada periode ini.")
        c.font = F(italic=True)

    ws.freeze_panes = ws.cell(row=kepala + 1, column=1)
    if semua:
        ws.auto_filter.ref = f"A{kepala}:H{b - 1}"
    _lebarkan(ws, dari=kepala)
    ws.column_dimensions["G"].width = 46
    return ws


# ---------------------------------------------------------------------------
# Lembar grafik
# ---------------------------------------------------------------------------
def _gaya_grafik(ch, judul, judul_y, tinggi=8.0, lebar=20.0):
    """Shared settings for all charts: size, axis titles, and legend.

    The default width is 20 cm, roughly the printable width of portrait A4 minus
    margins, so charts are not cut off when the sheet is printed.
    """
    ch.title = judul
    ch.style = 2                      # garis tipis, latar putih; enak dicetak
    ch.height = tinggi
    ch.width = lebar
    ch.y_axis.title = judul_y
    ch.x_axis.delete = False  # openpyxl hides axes unless set explicitly; a chart without axis numbers is unreadable
    ch.y_axis.delete = False
    return ch


def _lembar_grafik(wb, db, device, period, nama="Grafik"):
    """Availability and latency series per device, plus two line charts.

    The table is written too, not hidden: a report with only pictures cannot be
    re-checked, so a reader who doubts the shape of a line must be able to find the
    numbers on the same sheet.
    """
    from openpyxl.chart import LineChart, Reference

    mulai, selesai, _label = rs.rentang(period)
    series = rs.deret_per_jam(db, device["id"], mulai, selesai)
    titik = series["titik"]

    ws = wb.create_sheet(nama)
    b = _judul_lembar(ws, f"Grafik Ketersediaan — {device['name']}", 6)
    _keterangan(ws, b,
                f"Dirangkum per {series['satuan']}. Availability dihitung dari WAKTU "
                f"(waktu diamati dikurangi waktu tidak merespons), dasar yang sama "
                f"dengan kartu di lembar Riwayat, sehingga kedua angka pasti cocok. "
                f"Baris kosong = pemantauan sedang tidak berjalan pada {series['satuan']} "
                f"itu, bukan perangkatnya mati.")
    b += 2

    kepala = b
    b = _kepala_tabel(ws, b, [
        f"Waktu (per {series['satuan']})", "Availability (%)",
        "Latency rata-rata (ms)", "Waktu diamati (detik)",
        "Tidak merespons (detik)", "Sampel ping",
    ])
    line_begin = b
    for t in titik:
        nilai = [t["kotak"], t["availability"], t["latency_ms"],
                 t["diamati_detik"], t["down_detik"], t["sampel"]]
        for k, v in enumerate(nilai, 1):
            sel = ws.cell(row=b, column=k, value=v)
            sel.border = KOTAK
            sel.font = F()
            if k == 2:
                sel.number_format = "0.000"
                sel.font = F(bold=(v is not None and v < 100))
            elif k == 3:
                sel.number_format = "0.00"
            elif k in (4, 5):
                sel.number_format = "0"
            if k > 1:
                sel.alignment = Alignment(horizontal="right")
        b += 1

    if not titik:
        c = ws.cell(row=b, column=1,
                    value="Belum ada hasil ping pada periode ini, grafik tidak bisa digambar.")
        c.font = F(italic=True)
        _lebarkan(ws, dari=kepala)
        return ws

    baris_akhir = b - 1
    sumbu = Reference(ws, min_col=1, min_row=line_begin, max_row=baris_akhir)

    g1 = LineChart()
    g1.add_data(Reference(ws, min_col=2, min_row=kepala, max_row=baris_akhir),
                titles_from_data=True)
    g1.set_categories(sumbu)
    _gaya_grafik(g1, f"Ketersediaan per {series['satuan']}", "Availability (%)")
    # Scale locked to 0-100. Left automatic, Excel would draw an all-healthy period with a
    # 99.9-100 axis, so a tenth-of-a-percent ripple would look like a major outage.
    g1.y_axis.scaling.min = 0
    g1.y_axis.scaling.max = 100
    ws.add_chart(g1, "H3")

    g2 = LineChart()
    g2.add_data(Reference(ws, min_col=3, min_row=kepala, max_row=baris_akhir),
                titles_from_data=True)
    g2.set_categories(sumbu)
    _gaya_grafik(g2, f"Latency rata-rata per {series['satuan']}", "Milidetik")
    ws.add_chart(g2, "H21")

    ws.freeze_panes = ws.cell(row=line_begin, column=1)
    _lebarkan(ws, dari=kepala)
    return ws


def _grafik_per_device(ws, kepala, baris_akhir, kolom_nama, kolom_nilai, jangkar):
    """Per-device availability bars, placed on the Per Device sheet."""
    from openpyxl.chart import BarChart, Reference

    if baris_akhir < kepala + 1:
        return
    g = BarChart()
    g.type = "col"
    g.add_data(Reference(ws, min_col=kolom_nilai, min_row=kepala,
                         max_row=baris_akhir), titles_from_data=True)
    g.set_categories(Reference(ws, min_col=kolom_nama, min_row=kepala + 1,
                               max_row=baris_akhir))
    _gaya_grafik(g, "Availability tiap perangkat", "Availability (%)", tinggi=9.0)
    g.legend = None
    g.y_axis.scaling.min = 0
    g.y_axis.scaling.max = 100
    ws.add_chart(g, jangkar)


# ---------------------------------------------------------------------------
# Titik masuk
# ---------------------------------------------------------------------------
def create_report(db, period, dibuat_oleh=None):
    """Return the contents of the overall report .xlsx as bytes."""
    data = rs.ringkasan(db, period)
    daftar = data.get("devices_semua", data["devices"])
    wb = Workbook()
    _lembar_ringkasan(wb, data, dibuat_oleh)
    _lembar_device(wb, data)
    _lembar_gangguan(wb, db, data, period)
    _lembar_bandwidth(wb, db, daftar, period)
    _lembar_latency(wb, db, daftar, period)
    _lembar_event(wb, db, daftar, period)

    file = BytesIO()
    wb.save(file)
    return file.getvalue()


def buat_laporan_device(db, device_id, period, dibuat_oleh=None):
    """.xlsx report for one device (history + bandwidth + event log)."""
    data = rs.riwayat_device(db, device_id, period, limit=5000)
    wb = Workbook()
    ws = wb.active
    ws.title = "Riwayat"

    if data.get("error"):
        c = ws.cell(row=1, column=1, value=data["error"])
        c.font = F(bold=True)
        file = BytesIO()
        wb.save(file)
        return file.getvalue()

    d = data["device"]
    r = data["ringkasan"]
    mulai, _finish, _label = rs.rentang(period)
    stat = rs.statistik_latency(db, device_id, mulai)

    b = _judul_lembar(ws, f"Riwayat Gangguan Device {d['name']}", 7)
    b += 1
    for label, nilai in [
        ("Alamat IP", d["ip_address"]),
        ("Tipe", d["device_type"] or "-"),
        ("Lokasi", d["location"] or "-"),
        ("Platform", d["platform"] or "belum diisi"),
        ("Periode", rs.PERIODE_NAMA.get(data["periode"], data["periode"])),
        ("Dipantau sejak", _waktu(data.get("dipantau_sejak"))),
        ("Availability (%)", r["availability"]),
        ("Jumlah gangguan", r["insiden"]),
        ("Total tidak merespons", r["total_down_teks"]),
        ("MTTR", r.get("mttr_teks", "-")),
        ("Latency rata-rata (ms)", stat["rata_ms"]),
        ("Latency minimum (ms)", stat["min_ms"]),
        ("Latency maksimum (ms)", stat["max_ms"]),
        ("Jumlah sampel latency", stat["jumlah_sampel"]),
        ("Dibuat pada", datetime.now()),
        ("Dibuat oleh", dibuat_oleh or "-"),
    ]:
        sel = _baris_info(ws, b, label, nilai, 4)
        if isinstance(nilai, datetime):
            sel.number_format = "dd mmmm yyyy hh:mm"
        elif label.startswith("Availability"):
            sel.number_format = '0.000'
            sel.font = F(bold=True)
        elif label.startswith("Latency"):
            sel.number_format = "0.00"
        b += 1

    b += 1
    kepala = b
    b = _kepala_tabel(ws, b, [
        "No", "Mulai tidak merespons", "Pulih", "Lama (detik)", "Lama",
        "Penyebab menurut pemeriksaan", "Keterangan pemeriksaan",
    ])
    for i, g in enumerate(data["riwayat"], 1):
        nilai = [
            i, _waktu(g["mulai"]),
            None if g["berlangsung"] else _waktu(g["selesai"]),
            g["durasi_detik"],
            g["durasi_teks"] + (" (masih berlangsung)" if g["berlangsung"] else ""),
            g["kategori_teks"], g["detail"] or "-",
        ]
        for k, v in enumerate(nilai, 1):
            sel = ws.cell(row=b, column=k, value=v)
            sel.border = KOTAK
            sel.font = F()
            if k in (2, 3):
                sel.number_format = "dd/mm/yyyy hh:mm:ss"
            elif k == 4:
                sel.alignment = Alignment(horizontal="right")
            elif k in (6, 7):
                sel.alignment = Alignment(wrap_text=True, vertical="top")
                sel.font = F(9)
        if g["berlangsung"]:
            sel = ws.cell(row=b, column=3, value="belum pulih")
            sel.font = F(italic=True)
            sel.number_format = "General"
        b += 1

    if not data["riwayat"]:
        c = ws.cell(row=b, column=1, value="Tidak ada gangguan pada periode ini")
        c.font = F(italic=True)

    ws.freeze_panes = ws.cell(row=kepala + 1, column=1)
    _lebarkan(ws, dari=kepala)
    ws.column_dimensions["F"].width = 46
    ws.column_dimensions["G"].width = 52

    _lembar_grafik(wb, db, d, period)
    _lembar_bandwidth(wb, db, [d], period)
    _lembar_event(wb, db, [d], period)

    file = BytesIO()
    wb.save(file)
    return file.getvalue()


def nama_berkas(awalan, tambahan=None):
    section = [awalan]
    if tambahan:
        clean = "".join(c if c.isalnum() else "-" for c in str(tambahan))
        clean = "-".join(x for x in clean.split("-") if x)
        if clean:
            section.append(clean)
    section.append(datetime.now().strftime("%Y%m%d-%H%M"))
    return "-".join(section) + ".xlsx"
