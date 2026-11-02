"""Merakit berkas Word laporan magang dari berkas Markdown di folder ini.

Format mengikuti kebiasaan laporan akademis di Indonesia: Times New Roman 12 pt,
spasi 1,5, margin kiri 4 cm, atas 4 cm, kanan 3 cm, bawah 3 cm, rata kanan kiri,
seluruh teks dan garis tabel berwarna hitam tanpa aksen warna apa pun.

Penanda khusus yang dikenali di dalam berkas Markdown:

    !SAMPUL                    halaman judul, seluruh isinya rata tengah
    !TANDATANGAN               blok tanda tangan dua kolom
    !DAFTARISI                 medan daftar isi otomatis Word
    !DAFTARGAMBAR              medan daftar gambar otomatis Word
    !DAFTARTABEL               medan daftar tabel otomatis Word
    !TABEL[Tabel 4.1 Judul]    keterangan tabel, diletakkan DI ATAS tabelnya
    !GAMBAR[Gambar 4.1 Judul](gambar/x.png)   gambar beserta keterangannya
    !GAMBAR[Judul](gambar/x.png){11cm}        sama, tapi lebar dibatasi 11 cm
                                               (dipakai untuk tangkapan layar
                                               agar tidak memenuhi lebar teks)
    \\pagebreak                 ganti halaman

Daftar isi, daftar gambar, dan daftar tabel dibuat sebagai MEDAN Word, bukan
sebagai teks mati. Akibatnya nomor halamannya baru muncul setelah medan itu
diperbarui di Word (pilih seluruh isi lalu tekan F9, atau klik kanan pada
daftarnya lalu pilih Update Field). Cara ini dipilih karena nomor halaman tidak
mungkin dihitung dari luar Word: ia bergantung pada pemenggalan halaman yang
baru ditentukan Word sendiri saat dokumennya dibuka.

Cara pakai:
    venv\\Scripts\\python.exe rakit_docx.py
"""
import os
import re
import struct

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

AKAR = os.path.dirname(os.path.abspath(__file__))
KELUARAN = os.path.join(AKAR, "Laporan-Magang-NSM.docx")

BERKAS = [
    "00-bagian-awal.md",
    "01-bab1.md",
    "02-bab2.md",
    "03-bab3.md",
    "04-bab4.md",
    "05-bab5.md",
    "06-bab6.md",
    "07-pustaka-lampiran.md",
]

# Naskah versi kedua. Ditulis ulang, bukan hasil pemotongan naskah pertama:
# susunan babnya mengikuti struktur baku laporan PKL di Indonesia dan panjangnya
# dirancang sejak awal supaya isi Bab I sampai VI muat di bawah 35 halaman.
BERKAS_V2 = [
    "v2-00-awal.md",
    "v2-01-bab1.md",
    "v2-02-bab2.md",
    "v2-03-bab3.md",
    "v2-04-bab4.md",
    "v2-05-bab5.md",
    "v2-06-bab6.md",
    "v2-07-pustaka.md",
]
KELUARAN_V2 = os.path.join(AKAR, "Laporan-Magang-NSM-v2.docx")

# Lampiran dibuat sebagai dokumen tersendiri, terpisah dari laporan utama.
BERKAS_LAMPIRAN = ["lampiran-00.md"]
KELUARAN_LAMPIRAN = os.path.join(AKAR, "Lampiran-Laporan-Magang-NSM.docx")

HITAM = RGBColor(0, 0, 0)
FONT = "Times New Roman"
FONT_KODE = "Courier New"

# Lebar dan tinggi bidang teks pada halaman A4 dengan margin yang dipakai.
LEBAR_TEKS_CM = 21.0 - 4.0 - 3.0
TINGGI_TEKS_CM = 29.7 - 4.0 - 3.0
TINGGI_GAMBAR_MAKS_CM = 19.5


# ---------------------------------------------------------------- utilitas XML

def _sisip_medan(paragraf, instruksi, teks_sementara):
    """Menyisipkan medan Word (mis. PAGE atau TOC) ke dalam satu paragraf.

    python-docx tidak punya API untuk medan, jadi elemennya disusun langsung.
    `teks_sementara` adalah yang terlihat sebelum medannya diperbarui.
    """
    jalan = paragraf.add_run()
    awal = OxmlElement("w:fldChar")
    awal.set(qn("w:fldCharType"), "begin")
    kode = OxmlElement("w:instrText")
    kode.set(qn("xml:space"), "preserve")
    kode.text = instruksi
    pisah = OxmlElement("w:fldChar")
    pisah.set(qn("w:fldCharType"), "separate")
    isi = OxmlElement("w:t")
    isi.text = teks_sementara
    akhir = OxmlElement("w:fldChar")
    akhir.set(qn("w:fldCharType"), "end")
    for e in (awal, kode, pisah, isi, akhir):
        jalan._r.append(e)
    return jalan


def _nomor_halaman(bagian, format_angka):
    """Menetapkan format nomor halaman satu bagian: 'lowerRoman' atau 'decimal'."""
    sectPr = bagian._sectPr
    for lama in sectPr.findall(qn("w:pgNumType")):
        sectPr.remove(lama)
    e = OxmlElement("w:pgNumType")
    e.set(qn("w:fmt"), format_angka)
    e.set(qn("w:start"), "1")
    sectPr.append(e)


def _garis_tabel(tabel):
    """Memberi garis hitam tipis pada seluruh sisi dan seluruh sel."""
    tblPr = tabel._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for sisi in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement("w:" + sisi)
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "6")
        e.set(qn("w:space"), "0")
        e.set(qn("w:color"), "000000")
        borders.append(e)
    tblPr.append(borders)


def _baru_ganti_halaman(dok):
    """True bila paragraf terakhir hanya berisi penanda ganti halaman.

    Dipakai supaya `\\pagebreak` di akhir berkas bab dan permintaan halaman
    baru dari judul BAB berikutnya tidak dijalankan dua kali, yang akan
    menyisipkan satu halaman kosong di antara setiap bab.
    """
    if not dok.paragraphs:
        return True
    akhir = dok.paragraphs[-1]
    if akhir.text.strip():
        return False
    return bool(akhir._p.findall(".//" + qn("w:br")))


def _ukuran_png(jalur):
    """Membaca lebar dan tinggi berkas PNG dari kepalanya, tanpa pustaka gambar."""
    with open(jalur, "rb") as f:
        kepala = f.read(24)
    if len(kepala) < 24 or kepala[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    lebar, tinggi = struct.unpack(">II", kepala[16:24])
    return lebar, tinggi


# --------------------------------------------------------------------- gaya

def siapkan_gaya(dok):
    normal = dok.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(12)
    normal.font.color.rgb = HITAM
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    p = normal.paragraph_format
    p.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    p.space_after = Pt(0)
    p.space_before = Pt(0)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for nama, ukuran, tebal in (("Heading 1", 14, True),
                                ("Heading 2", 12, True),
                                ("Heading 3", 12, True)):
        g = dok.styles[nama]
        g.font.name = FONT
        g.font.size = Pt(ukuran)
        g.font.bold = tebal
        g.font.italic = False
        g.font.color.rgb = HITAM
        g.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        gp = g.paragraph_format
        gp.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        gp.space_before = Pt(6)
        gp.space_after = Pt(6)
        # Hanya judul BAB yang wajib menempel pada isinya. Memasang aturan ini
        # pada judul subbab membuat Word mendorong judul beserta paragraf
        # pertamanya ke halaman berikutnya setiap kali ruang di bawah menipis,
        # dan ruang yang ditinggalkannya terbuang.
        gp.keep_with_next = (nama == "Heading 1")

    dok.styles["Heading 1"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    dok.styles["Heading 2"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    dok.styles["Heading 3"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Gaya keterangan dibuat tersendiri supaya daftar gambar dan daftar tabel
    # bisa dibangun Word dari gaya itu, bukan dari tebakan atas isi teksnya.
    for nama in ("KeteranganGambar", "KeteranganTabel"):
        g = dok.styles.add_style(nama, 1)
        g.base_style = dok.styles["Normal"]
        g.font.name = FONT
        g.font.size = Pt(11)
        g.font.color.rgb = HITAM
        gp = g.paragraph_format
        gp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        gp.line_spacing_rule = WD_LINE_SPACING.SINGLE
        gp.space_before = Pt(6)
        gp.space_after = Pt(6)
        gp.keep_with_next = (nama == "KeteranganTabel")

    g = dok.styles.add_style("Kode", 1)
    g.base_style = dok.styles["Normal"]
    g.font.name = FONT_KODE
    g.font.size = Pt(10)
    g.font.color.rgb = HITAM
    gp = g.paragraph_format
    gp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    gp.line_spacing_rule = WD_LINE_SPACING.SINGLE
    gp.left_indent = Cm(0.8)
    gp.space_before = Pt(0)
    gp.space_after = Pt(0)

    g = dok.styles.add_style("IsiTabel", 1)
    g.base_style = dok.styles["Normal"]
    g.font.name = FONT
    g.font.size = Pt(11)
    g.font.color.rgb = HITAM
    gp = g.paragraph_format
    gp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    gp.line_spacing_rule = WD_LINE_SPACING.SINGLE
    gp.space_before = Pt(2)
    gp.space_after = Pt(2)


def siapkan_halaman(bagian):
    bagian.page_width = Cm(21.0)
    bagian.page_height = Cm(29.7)
    bagian.left_margin = Cm(4.0)
    bagian.top_margin = Cm(4.0)
    bagian.right_margin = Cm(3.0)
    bagian.bottom_margin = Cm(3.0)


def pasang_nomor(bagian, sembunyikan_halaman_pertama=False):
    # Halaman judul tetap dihitung sebagai halaman i, tetapi nomornya tidak
    # dicetak. Itu kebiasaan yang berlaku pada laporan akademis di Indonesia.
    if sembunyikan_halaman_pertama:
        bagian.different_first_page_header_footer = True
    kaki = bagian.footer
    kaki.is_linked_to_previous = False
    par = kaki.paragraphs[0] if kaki.paragraphs else kaki.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    par.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    for j in list(par.runs):
        j._r.getparent().remove(j._r)
    jalan = _sisip_medan(par, " PAGE ", "1")
    jalan.font.name = FONT
    jalan.font.size = Pt(11)
    jalan.font.color.rgb = HITAM


# ------------------------------------------------------------------ penulisan

POLA_GAYA = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)")


def tulis_teks(par, teks, ukuran=None):
    """Menulis teks dengan tiga penanda: **tebal**, *miring*, dan `kode`.

    Huruf miring dipakai untuk kata dan ungkapan asing sesuai kaidah EYD.
    Nama diri seperti nama protokol, merek dagang, dan nama produk sengaja
    TIDAK diberi penanda miring, karena kaidah yang sama mengecualikannya.
    """
    for potong in POLA_GAYA.split(teks):
        if not potong:
            continue
        if potong.startswith("**") and potong.endswith("**"):
            isi, tebal, miring, kode = potong[2:-2], True, False, False
        elif potong.startswith("*") and potong.endswith("*"):
            isi, tebal, miring, kode = potong[1:-1], False, True, False
        elif potong.startswith("`") and potong.endswith("`"):
            isi, tebal, miring, kode = potong[1:-1], False, False, True
        else:
            isi, tebal, miring, kode = potong, False, False, False
        jalan = par.add_run(isi)
        jalan.font.name = FONT_KODE if kode else FONT
        jalan.font.color.rgb = HITAM
        jalan.font.bold = tebal
        jalan.font.italic = miring
        if ukuran is not None:
            jalan.font.size = ukuran
        elif kode:
            jalan.font.size = Pt(11)


def paragraf(dok, teks, indent=True):
    par = dok.add_paragraph()
    par.paragraph_format.first_line_indent = Cm(1.27) if indent else Cm(0)
    par.paragraph_format.space_after = Pt(0)
    tulis_teks(par, teks)
    return par


def sisip_gambar(dok, keterangan, jalur, lebar_maks_cm=None):
    penuh = os.path.join(AKAR, jalur.replace("/", os.sep))
    par = dok.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    par.paragraph_format.first_line_indent = Cm(0)
    par.paragraph_format.space_before = Pt(10)
    par.paragraph_format.space_after = Pt(0)
    if not os.path.exists(penuh):
        tulis_teks(par, "[gambar tidak ditemukan: " + jalur + "]")
    else:
        ukuran = _ukuran_png(penuh)
        lebar_cm = lebar_maks_cm or LEBAR_TEKS_CM
        if ukuran:
            tinggi_cm = lebar_cm * ukuran[1] / ukuran[0]
            if tinggi_cm > TINGGI_GAMBAR_MAKS_CM:
                lebar_cm = lebar_cm * TINGGI_GAMBAR_MAKS_CM / tinggi_cm
        par.add_run().add_picture(penuh, width=Cm(lebar_cm))
    ket = dok.add_paragraph(style="KeteranganGambar")
    tulis_teks(ket, keterangan)
    return par


def sisip_tabel(dok, baris):
    lebar = max(len(b) for b in baris)
    tabel = dok.add_table(rows=len(baris), cols=lebar)
    tabel.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabel.autofit = True
    _garis_tabel(tabel)
    for i, isi_baris in enumerate(baris):
        for k in range(lebar):
            sel = tabel.cell(i, k)
            sel.text = ""
            par = sel.paragraphs[0]
            par.style = dok.styles["IsiTabel"]
            teks = isi_baris[k] if k < len(isi_baris) else ""
            tulis_teks(par, teks, ukuran=Pt(11))
            if i == 0:
                for jalan in par.runs:
                    jalan.font.bold = True
    kosong = dok.add_paragraph()
    kosong.paragraph_format.space_after = Pt(6)
    kosong.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    return tabel


def sisip_kode(dok, baris_kode):
    for baris in baris_kode:
        par = dok.add_paragraph(style="Kode")
        jalan = par.add_run(baris if baris else " ")
        jalan.font.name = FONT_KODE
        jalan.font.size = Pt(10)
        jalan.font.color.rgb = HITAM
    kosong = dok.add_paragraph()
    kosong.paragraph_format.space_after = Pt(6)
    kosong.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE


def sisip_daftar_medan(dok, instruksi, catatan):
    par = dok.add_paragraph()
    par.paragraph_format.first_line_indent = Cm(0)
    _sisip_medan(par, instruksi, catatan)


def sisip_tandatangan(dok):
    # Satu kolom saja: ini magang kerja langsung ke perusahaan, bukan magang
    # berkredit kuliah, jadi tidak ada dosen pembimbing yang perlu menandatangani.
    baris_isi = ("Menyetujui,\nPembimbing Lapangan\nPT Bumi Siak Pusako\n\n\n\n\n"
                 "( Jarizal )")
    for n, baris in enumerate(baris_isi.split("\n")):
        par = dok.add_paragraph() if n > 0 else dok.add_paragraph()
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        par.paragraph_format.space_after = Pt(0)
        jalan = par.add_run(baris)
        jalan.font.name = FONT
        jalan.font.size = Pt(12)
        jalan.font.color.rgb = HITAM
    dok.add_paragraph()


# --------------------------------------------------------------------- parser

def baca_semua(berkas):
    potongan = []
    for nama in berkas:
        jalur = os.path.join(AKAR, nama)
        with open(jalur, "r", encoding="utf-8") as f:
            potongan.append(f.read())
    return "\n".join(potongan).split("\n")


def rakit(berkas=BERKAS, keluaran=KELUARAN):
    dok = Document()
    siapkan_gaya(dok)
    siapkan_halaman(dok.sections[0])
    _nomor_halaman(dok.sections[0], "lowerRoman")
    pasang_nomor(dok.sections[0], sembunyikan_halaman_pertama=True)

    baris = baca_semua(berkas)
    i = 0
    mode_sampul = False
    ket_tabel = None
    bagian_isi_dibuat = False

    while i < len(baris):
        b = baris[i].rstrip()
        polos = b.strip()

        # ---- ganti halaman -------------------------------------------------
        if polos == "\\pagebreak":
            if mode_sampul:
                mode_sampul = False
            if not _baru_ganti_halaman(dok):
                dok.add_page_break()
            i += 1
            continue

        # ---- halaman judul --------------------------------------------------
        if polos == "!SAMPUL":
            mode_sampul = True
            i += 1
            continue

        if mode_sampul:
            m_logo = re.match(r"^!LOGO\((.+)\)$", polos)
            if m_logo:
                jalur_logo = os.path.join(AKAR, m_logo.group(1).replace("/", os.sep))
                par = dok.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
                par.paragraph_format.first_line_indent = Cm(0)
                par.paragraph_format.space_after = Pt(10)
                if os.path.exists(jalur_logo):
                    par.add_run().add_picture(jalur_logo, width=Cm(3.2))
                i += 1
                continue
            par = dok.add_paragraph()
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            par.paragraph_format.first_line_indent = Cm(0)
            par.paragraph_format.space_after = Pt(10)
            if polos:
                jalan = par.add_run(polos)
                jalan.font.name = FONT
                jalan.font.color.rgb = HITAM
                # Judul laporan dibuat lebih besar dan tebal; sisanya biasa.
                if polos.startswith("IMPLEMENTASI SISTEM NSM") or polos.startswith("IMPLEMENTASI PROYEK NSM"):
                    jalan.font.size = Pt(14)
                    jalan.font.bold = True
                elif polos in ("LAPORAN PRAKTIK KERJA LAPANGAN",
                               "NANJING XIAOZHUANG UNIVERSITY"):
                    jalan.font.bold = True
            i += 1
            continue

        # ---- penanda khusus -------------------------------------------------
        if polos == "!DAFTARISI":
            sisip_daftar_medan(dok, ' TOC \\o "1-3" \\h \\z \\u ',
                               "[Daftar isi akan terisi setelah medan diperbarui di Word: "
                               "tekan Ctrl+A lalu F9]")
            i += 1
            continue

        if polos == "!DAFTARGAMBAR":
            sisip_daftar_medan(dok, ' TOC \\h \\z \\t "KeteranganGambar,1" ',
                               "[Daftar gambar akan terisi setelah medan diperbarui di Word: "
                               "tekan Ctrl+A lalu F9]")
            i += 1
            continue

        if polos == "!DAFTARTABEL":
            sisip_daftar_medan(dok, ' TOC \\h \\z \\t "KeteranganTabel,1" ',
                               "[Daftar tabel akan terisi setelah medan diperbarui di Word: "
                               "tekan Ctrl+A lalu F9]")
            i += 1
            continue

        if polos == "!TANDATANGAN":
            sisip_tandatangan(dok)
            i += 1
            continue

        m = re.match(r"^!TABEL\[(.+)\]$", polos)
        if m:
            ket_tabel = m.group(1)
            i += 1
            continue

        m = re.match(r"^!GAMBAR\[(.+)\]\((.+?)\)(?:\{(\d+(?:\.\d+)?)cm\})?$", polos)
        if m:
            lebar = float(m.group(3)) if m.group(3) else None
            sisip_gambar(dok, m.group(1), m.group(2), lebar_maks_cm=lebar)
            i += 1
            continue

        # ---- judul ----------------------------------------------------------
        if polos.startswith("### "):
            dok.add_paragraph(polos[4:], style="Heading 3")
            i += 1
            continue

        if polos.startswith("## "):
            dok.add_paragraph(polos[3:], style="Heading 2")
            i += 1
            continue

        if polos.startswith("# "):
            judul = polos[2:]
            # Bagian isi dimulai pada BAB I; di situ penomoran halaman
            # berganti dari angka romawi ke angka biasa.
            if judul.startswith("BAB I ") and not bagian_isi_dibuat:
                bagian = dok.add_section(WD_SECTION.NEW_PAGE)
                siapkan_halaman(bagian)
                _nomor_halaman(bagian, "decimal")
                pasang_nomor(bagian)
                bagian_isi_dibuat = True
            elif len(dok.paragraphs) > 0 and not _baru_ganti_halaman(dok):
                dok.add_page_break()
            dok.add_paragraph(judul, style="Heading 1")
            i += 1
            continue

        # ---- blok kode ------------------------------------------------------
        if polos.startswith("```"):
            i += 1
            isi = []
            while i < len(baris) and not baris[i].strip().startswith("```"):
                isi.append(baris[i].rstrip())
                i += 1
            i += 1
            sisip_kode(dok, isi)
            continue

        # ---- tabel ----------------------------------------------------------
        if polos.startswith("|"):
            kumpulan = []
            while i < len(baris) and baris[i].strip().startswith("|"):
                sel = [s.strip() for s in baris[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", s) for s in sel if s):
                    kumpulan.append(sel)
                i += 1
            if ket_tabel:
                par = dok.add_paragraph(style="KeteranganTabel")
                tulis_teks(par, ket_tabel)
                ket_tabel = None
            sisip_tabel(dok, kumpulan)
            continue

        # ---- daftar bernomor dan bertanda ------------------------------------
        m = re.match(r"^(\d+)\.\s+(.*)$", polos)
        if m:
            par = dok.add_paragraph()
            par.paragraph_format.left_indent = Cm(1.27)
            par.paragraph_format.first_line_indent = Cm(-0.64)
            par.paragraph_format.space_after = Pt(4)
            tulis_teks(par, m.group(1) + ". " + m.group(2))
            i += 1
            continue

        if polos.startswith("- "):
            par = dok.add_paragraph()
            par.paragraph_format.left_indent = Cm(1.27)
            par.paragraph_format.first_line_indent = Cm(-0.64)
            par.paragraph_format.space_after = Pt(4)
            tulis_teks(par, "•  " + polos[2:])
            i += 1
            continue

        # ---- paragraf biasa --------------------------------------------------
        if polos:
            # Baris yang seluruhnya tebal diperlakukan sebagai anak judul
            # tanpa nomor, jadi tidak diberi indentasi baris pertama.
            berdiri_sendiri = polos.startswith("**") and polos.rstrip().endswith("**") \
                and polos.count("**") == 2
            paragraf(dok, polos, indent=not berdiri_sendiri)
        i += 1

    dok.save(keluaran)
    return keluaran


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "v2":
        jalur = rakit(BERKAS_V2, KELUARAN_V2)
    elif len(sys.argv) > 1 and sys.argv[1] == "lampiran":
        jalur = rakit(BERKAS_LAMPIRAN, KELUARAN_LAMPIRAN)
    else:
        jalur = rakit()
    print("tersimpan:", jalur)
    print("ukuran   :", round(os.path.getsize(jalur) / 1024 / 1024, 2), "MB")
