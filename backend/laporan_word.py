"""NSM report as a compact but formal Word (.docx) file.

Why a Word version next to Excel and PDF:
* Excel -> for further processing (sort, filter, sum).
* PDF   -> to read or print as is; cannot be edited.
* Word  -> a formal document that can STILL be edited before handing it over
           (add an introduction, change the letterhead, etc.).

Style: Times New Roman with the BSP brand green (#2B6049) used sparingly on the
title, table header, and lines. The body stays black.

Deliberately NO signature block. A monitoring report is not signed: readers need to
know where the figures come from and when they were taken, not who signed. The
footer states that.

The content is compact (not as complete as the Excel file): summary, devices needing
attention, availability table, incident list, and reading notes.
"""
from datetime import datetime
from io import BytesIO

from docx import Document
from docx.shared import Pt, RGBColor, Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import report_service as rs

FONT = "Times New Roman"
HIJAU = RGBColor(0x2B, 0x60, 0x49)
HIJAU_HEX = "2B6049"
HIJAU_MUDA_HEX = "E4EFEA"
HITAM = RGBColor(0x00, 0x00, 0x00)
PUTIH = RGBColor(0xFF, 0xFF, 0xFF)


# ---------------------------------------------------------------------------
# Bantuan tampilan
# ---------------------------------------------------------------------------
def _pakai_tnr(run):
    """Force a run to use Times New Roman, including for non-Latin scripts.

    Setting `run.font.name` alone is sometimes not enough: Word stores Latin and
    complex/Asian fonts in different attributes, and if one is empty some text can fall
    back to the default font (Calibri). All of them are set here.
    """
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for atribut in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(atribut), FONT)


def _run(p, teks, size=11, bold=False, italic=False, warna=None):
    r = p.add_run("" if teks is None else str(teks))
    _pakai_tnr(r)
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    r.font.color.rgb = warna if warna is not None else HITAM
    return r


def _shade(cell, hex_warna):
    """Set the background color of a table cell (used for the green header row)."""
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_warna)
    tcpr.append(shd)


def _garis_bawah(p, hex_warna=HIJAU_HEX, tebal=12):
    """Bottom border under a paragraph, used as the letterhead separator."""
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(tebal))
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), hex_warna)
    pbdr.append(bottom)
    ppr.append(pbdr)


def _judul_bagian(doc, teks):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    _run(p, teks.upper(), size=12, bold=True, warna=HIJAU)
    return p


def _ket(doc, teks):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    _run(p, teks, size=8.5, italic=True)
    return p


def _tabel(doc, kepala, baris_data, lebar=None, rata_kanan=None):
    """Build a bordered table with a green header row and white text.

    `rata_kanan` = set of (0-based) column indexes whose content is numeric and
    right-aligned.
    """
    rata_kanan = rata_kanan or set()
    t = doc.add_table(rows=1, cols=len(kepala))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, teks in enumerate(kepala):
        sel = t.rows[0].cells[i]
        _shade(sel, HIJAU_HEX)
        p = sel.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(p, teks, size=9, bold=True, warna=PUTIH)

    for data in baris_data:
        sel = t.add_row().cells
        for i, nilai in enumerate(data):
            p = sel[i].paragraphs[0]
            if i in rata_kanan:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _run(p, nilai, size=9)

    if lebar:
        for i, w in enumerate(lebar):
            if w is None:
                continue
            for row in t.rows:
                row.cells[i].width = Mm(w)
    return t


def _waktu(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)[:19])
    except (ValueError, TypeError):
        return None


def _waktu_teks(iso):
    d = _waktu(iso)
    return d.strftime("%d-%m-%Y %H:%M:%S") if d else "-"


def _persen(nilai):
    return "-" if nilai is None else f"{nilai:.3f}%"


# ---------------------------------------------------------------------------
# Penyusun dokumen
# ---------------------------------------------------------------------------
def _atur_dasar(doc):
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(11)
    st.font.color.rgb = HITAM
    rpr = st.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for atribut in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(atribut), FONT)
    sec = doc.sections[0]
    sec.top_margin = Mm(18)
    sec.bottom_margin = Mm(16)
    sec.left_margin = Mm(18)
    sec.right_margin = Mm(16)


def _field(p, perintah):
    """Embed a Word FIELD in a paragraph.

    Why a field and not plain text: the page count is only known after Word lays out the
    document, on the reader's computer. Writing "page 1 of 4" as text would guess a
    number that goes wrong as soon as a table gains a row.

    A field is a small instruction that Word recomputes every time the document is
    opened or printed, so `PAGE` and `NUMPAGES` stay correct after edits and when the
    document is saved as PDF.
    """
    mulai = OxmlElement("w:fldChar")
    mulai.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {perintah} "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    r = p.add_run()
    r.font.name = FONT
    r.font.size = Pt(8)
    r.font.color.rgb = HITAM
    r._r.append(mulai)
    r._r.append(instr)
    r._r.append(end)


def _kaki_halaman(doc, judul):
    """Page footer: document title at the left, `hal. N dari M` (page N of M) at the right.

    This matters beyond tidiness. A printed report changes hands as loose sheets:
    without page numbers a dropped sheet cannot be put back, and without a title on each
    sheet a table page separated from its header cannot be accounted for (which device,
    which period, requested by whom).

    Placed in the SECTION footer, so Word repeats it on every page.
    """
    p = doc.sections[0].footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # Right tab stop at the right edge of the text area, so the page number is
    # right-aligned regardless of the title's length.
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "right")
    # A4 text width (210mm) minus 18mm left and 16mm right margins, in twips (1 mm = 56.7 twip).
    tab.set(qn("w:pos"), str(int((210 - 18 - 16) * 56.7)))
    tabs.append(tab)
    p.paragraph_format.element.get_or_add_pPr().append(tabs)

    _run(p, judul, size=8)
    p.add_run("\t")
    _run(p, "hal. ", size=8)
    _field(p, "PAGE")
    _run(p, " dari ", size=8)
    _field(p, "NUMPAGES")


def _kop(doc, data, dibuat_oleh):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    _run(p, "DIVISI NETWORK SECURITY", size=10.5, bold=True, warna=HIJAU)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    _run(p, "Laporan Ketersediaan Perangkat Jaringan", size=16, bold=True,
         warna=HIJAU)

    p = doc.add_paragraph()
    _run(p, "NSM (Network Status Monitor)", size=10)
    _garis_bawah(p)

    rentang = _waktu_teks(data.get("mulai")) + " s.d. " + _waktu_teks(data.get("selesai"))
    # "Monitoring duration" is the SHORTEST window among all devices, not the longest: the
    # least-observed device decides how far the combined figure can be trusted.
    observed = data.get("diamati_teks", "-")
    if data.get("diamati_beragam"):
        observed = (data.get("diamati_teks", "-") + " s.d. "
                   + data.get("diamati_maks_teks", "-")
                   + " (berbeda tiap perangkat)")
    if not data.get("periode_penuh"):
        observed += " (periode belum terpenuhi seluruhnya)"
    jumlah = f"{data['total_device']} perangkat dipantau"
    if data.get("device_dijeda"):
        jumlah += f", {data['device_dijeda']} dijeda"

    content = [
        ("Periode laporan", rs.PERIODE_NAMA.get(data["periode"], data["periode"])),
        ("Rentang waktu", rentang),
        ("Lama pemantauan", observed),
        ("Jumlah perangkat", jumlah),
        ("Disusun oleh", dibuat_oleh or "-"),
        ("Tanggal cetak", datetime.now().strftime("%d-%m-%Y %H:%M:%S")),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.allow_autofit = False
    for label, nilai in content:
        sel = t.add_row().cells
        _run(sel[0].paragraphs[0], label, size=9.5, bold=True)
        _run(sel[1].paragraphs[0], nilai, size=9.5)
        sel[0].width = Mm(45)
        sel[1].width = Mm(130)


def _bagian_ringkasan(doc, s):
    _judul_bagian(doc, "I. Ringkasan")
    lat_note = ""
    if s.get("device_paling_lambat"):
        lat_note = ("Terlambat: " + s["device_paling_lambat"]["name"] +
                   f" ({s['device_paling_lambat']['ms']} ms)")
    top = "Tidak ada"
    top_note = ""
    if s.get("top_offender"):
        top = s["top_offender"]["name"]
        top_note = (f"{s['top_offender']['insiden']} gangguan, total "
                   f"{s['top_offender']['total_down_teks']}")
    streak_note = "Belum pernah ada gangguan"
    if s.get("insiden_terakhir"):
        streak_note = ("Gangguan terakhir: " + s["insiden_terakhir"]["device"] +
                      " pada " + _waktu_teks(s["insiden_terakhir"]["waktu"]))

    line = [
        ("Perangkat merespons saat laporan dibuat",
         f"{s['device_up']} dari {s['total_device']}",
         (f"{s['device_down']} perangkat tidak merespons"
          if s["device_down"] else "Seluruh perangkat merespons")),
        ("Ketersediaan keseluruhan", _persen(s["availability_rata"]),
         "Rata-rata seluruh perangkat aktif pada periode ini"),
        ("Jumlah gangguan", str(s["insiden_total"]),
         "Total waktu tidak merespons: " + s["total_down_teks"]),
        ("Rata-rata waktu pemulihan (MTTR)", s.get("mttr_teks", "-"),
         "Total waktu pulih dibagi jumlah gangguan yang telah selesai"),
        ("Latency rata-rata",
         "-" if s["latency_rata_ms"] is None else f"{s['latency_rata_ms']} ms",
         lat_note),
        ("Perangkat paling bermasalah", top, top_note),
        ("Berjalan tanpa gangguan", s.get("uptime_streak_teks", "-"), streak_note),
    ]
    _tabel(doc, ["Keterangan", "Nilai", "Catatan"], line,
           lebar=[62, 28, 85])


def _bagian_perhatian(doc, s):
    _judul_bagian(doc, "II. Perangkat yang Perlu Perhatian")
    _ket(doc, "Perangkat disorot bila ketersediaannya di bawah 99%, mengalami "
              "3 gangguan atau lebih, atau sedang tidak merespons saat laporan "
              "dibuat.")

    need = [d for d in (s.get("devices_semua") or s["devices"])
             if d.get("aktif", True) and (
                 (d["availability"] is not None and d["availability"] < 99)
                 or d["insiden"] >= 3 or d["is_reachable"] is False)]
    need.sort(key=lambda d: 101 if d["availability"] is None else d["availability"])

    if not need:
        p = doc.add_paragraph()
        _run(p, "Tidak ada perangkat yang memerlukan perhatian pada periode "
                "ini. Seluruh perangkat aktif berada di atas 99% ketersediaan "
                "dan sedang merespons.", size=9.5)
        return

    for d in need:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        judul = d["name"] + " (" + d["ip_address"]
        judul += (", " + d["location"] + ")") if d.get("location") else ")"
        _run(p, judul, size=9.5, bold=True)

        number = ("Ketersediaan " + _persen(d["availability"]) +
                 f"  |  {d['insiden']} gangguan  |  total tidak merespons " +
                 d["total_down_teks"])
        if d["is_reachable"] is False:
            number += "  |  SEDANG TIDAK MERESPONS"
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        _run(p, number, size=9)

        cause = []
        if d["is_reachable"] is False:
            cause.append("sedang tidak merespons")
        if d["availability"] is not None and d["availability"] < 99:
            cause.append("ketersediaan di bawah 99%")
        if d["insiden"] >= 3:
            cause.append(f"{d['insiden']} gangguan pada periode ini")
        if (d["insiden"] >= 5 and d.get("mttr_detik") is not None
                and d["mttr_detik"] < 120):
            cause.append("sering putus singkat lalu pulih sendiri (rata-rata "
                         + str(d.get("mttr_teks", "-")) +
                         "), menandakan sambungan yang tidak stabil")
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        _run(p, "Alasan disorot: " + "; ".join(cause) + ".", size=9, italic=True)


def _bagian_tabel_device(doc, s):
    _judul_bagian(doc, "III. Ketersediaan per Perangkat")
    line = []
    for d in (s.get("devices_semua") or s["devices"]):
        if not d.get("aktif", True):
            status = "DIJEDA"
        elif d["is_reachable"] is True:
            status = "UP"
        elif d["is_reachable"] is False:
            status = "DOWN"
        else:
            status = "-"
        line.append([
            status, d["name"], d["ip_address"], d["location"] or "-",
            _persen(d["availability"]), str(d["insiden"]),
            d["total_down_teks"],
            "-" if d["avg_latency_ms"] is None else f"{d['avg_latency_ms']} ms",
        ])
    _tabel(doc, ["Status", "Perangkat", "Alamat IP", "Lokasi", "Ketersediaan",
                 "Gangguan", "Total tidak merespons", "Latency"], line,
           rata_kanan={4, 5, 7})


def _bagian_gangguan(doc, db, s, period):
    _judul_bagian(doc, "IV. Daftar Gangguan")
    semua = []
    for d in (s.get("devices_semua") or s["devices"]):
        riwayat = rs.riwayat_device(db, d["id"], period, limit=1000)
        for g in riwayat.get("riwayat", []):
            semua.append((d, g))
    semua.sort(key=lambda x: x[1]["mulai"], reverse=True)

    if not semua:
        p = doc.add_paragraph()
        _run(p, "Tidak ada gangguan pada periode ini.", size=9.5, italic=True)
        return

    _ket(doc, "Seluruh gangguan pada periode ini, diurutkan dari yang terbaru. "
              "Sebab diambil dari pemeriksaan otomatis saat ping gagal.")
    line = []
    for i, (d, g) in enumerate(semua, 1):
        recover = ("belum pulih" if g["berlangsung"]
                 else _waktu_teks(g["selesai"]))
        old = g["durasi_teks"] + (" (berjalan)" if g["berlangsung"] else "")
        line.append([
            str(i), d["name"], _waktu_teks(g["mulai"]), recover, old,
            g["kategori_teks"],
        ])
    _tabel(doc, ["No", "Perangkat", "Mulai", "Pulih", "Lama",
                 "Penyebab menurut pemeriksaan"], line,
           lebar=[10, 34, 30, 30, 24, 50])


def _bagian_catatan(doc, s):
    _judul_bagian(doc, "Catatan")
    content = [
        "Ketersediaan dihitung atas lama pemantauan yang sebenarnya, bukan "
        "diandaikan periode penuh. Perangkat yang baru mulai dipantau akan "
        "menunjukkan angka yang lebih peka terhadap satu gangguan.",
        "Penyebab gangguan berasal dari pemeriksaan otomatis saat ping gagal. "
        "\"Tidak ada respons\" berarti ping gagal dan tidak ada port TCP yang "
        "menjawab; \"Ping diblokir\" berarti ping gagal tetapi port TCP masih "
        "menjawab. Penyebab fisik seperti listrik padam, kabel lepas, atau "
        "perangkat yang berhenti bekerja tidak dapat dibedakan dari jaringan.",
        "Perangkat yang dijeda tidak ikut menghitung angka keseluruhan, namun "
        "riwayat gangguannya tetap tersimpan dan ditampilkan.",
    ]
    if not s.get("periode_penuh"):
        content.insert(0, "Periode yang diminta belum terpenuhi seluruhnya. Angka "
                      "pada laporan ini dihitung dari " +
                      (s.get("diamati_teks") or "-") + " pemantauan.")
    for i, t in enumerate(content, 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        _run(p, f"{i}. {t}", size=8.5)


def _kaki(doc, s):
    """Document footer. Not a signature block: there is deliberately no place to sign."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    _garis_bawah(p, tebal=6)
    p2 = doc.add_paragraph()
    _run(p2, "Dibuat otomatis oleh NSM (Network Status Monitor). "
             "Data per " + _waktu_teks(s.get("selesai")) + ".", size=8)


# ---------------------------------------------------------------------------
# Titik masuk
# ---------------------------------------------------------------------------
def buat_laporan_word(db, period, dibuat_oleh=None):
    """Return the contents of the .docx file (summary report) as bytes."""
    s = rs.ringkasan(db, period)
    doc = Document()
    _atur_dasar(doc)
    _kaki_halaman(doc, "Laporan Ketersediaan Perangkat Jaringan  |  NSM  |  "
                       "periode " + str(s.get("periode_teks") or period))
    _kop(doc, s, dibuat_oleh)
    _bagian_ringkasan(doc, s)
    _bagian_perhatian(doc, s)
    _bagian_tabel_device(doc, s)
    _bagian_gangguan(doc, db, s, period)
    _bagian_catatan(doc, s)
    _kaki(doc, s)

    file = BytesIO()
    doc.save(file)
    return file.getvalue()


def nama_berkas(awalan, tambahan=None):
    section = [awalan]
    if tambahan:
        clean = "".join(c if c.isalnum() else "-" for c in str(tambahan))
        clean = "-".join(x for x in clean.split("-") if x)
        if clean:
            section.append(clean)
    section.append(datetime.now().strftime("%Y%m%d-%H%M"))
    return "-".join(section) + ".docx"
