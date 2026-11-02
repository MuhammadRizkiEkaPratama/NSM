package id.bsp.frontend;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockServletContext;
import org.thymeleaf.context.WebContext;
import org.thymeleaf.spring6.SpringTemplateEngine;
import org.thymeleaf.web.servlet.IServletWebExchange;
import org.thymeleaf.web.servlet.JakartaServletWebApplication;

import java.util.Locale;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Renders both report pages in full, not just the navigation fragment. Guards that the templates render at all (an expression error is a 500) and that the print identity block exists (it is hidden on screen, so deleting it would go unnoticed). */
@SpringBootTest
class CetakTemplateTest {

    @Autowired
    private SpringTemplateEngine mesin;

    /** Renders a full page template with a model like the controller's. */
    private String render(String templat, String username, boolean isAdmin,
                          Integer deviceId, String period) {
        // WEB context, as in NavFragmentTest: all links use `@{/...}`, which needs a context path.
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        ctx.setVariable("username", username);
        ctx.setVariable("isAdmin", isAdmin);
        ctx.setVariable("period", period);
        if (deviceId != null) {
            ctx.setVariable("deviceId", deviceId);
        }
        return mesin.process(templat, ctx);
    }

    @Test
    void halamanLaporanBisaDirenderTanpaGalat() {
        String device = render("report_device", "rina", true, 6, "24h");
        assertTrue(device.contains("<body"), "report_device gagal dirender");

        String cetak = render("report_cetak", "rina", true, null, "24h");
        assertTrue(cetak.contains("<body"), "report_cetak gagal dirender");
    }

    @Test
    void blokIdentitasCetakAdaDiKeduaLaporan() {
        // Per-device page: each identity row is checked as a full `id="..."`, since a bare substring also matches a broken name.
        String device = render("report_device", "rina", true, 6, "24h");
        String[] wajibDevice = {
                "ic-perangkat", "ic-alamat", "ic-lokasi", "ic-periode",
                "ic-rentang", "ic-diamati", "ic-tanggal",
                "kepala-cetak", "kaki-cetak", "kaki-sumber",
        };
        for (String id : wajibDevice) {
            assertTrue(device.contains("id=\"" + id + "\""),
                    "report_device kehilangan bagian identitas cetak: " + id);
        }

        // Halaman laporan keseluruhan.
        String cetak = render("report_cetak", "rina", true, null, "24h");
        String[] wajibCetak = {
                "i-periode", "i-rentang", "i-diamati", "i-jumlah", "i-tanggal",
        };
        for (String id : wajibCetak) {
            assertTrue(cetak.contains("id=\"" + id + "\""),
                    "report_cetak kehilangan bagian identitas: " + id);
        }
    }

    /** Checks that `nama` is actually printed near its label, as element content (`>nama<`). Thymeleaf does not reject a misspelled `th:text`; it renders it as a plain attribute, so the value would be in the document but invisible. */
    private void adaDiDekat(String html, String label, String nama, String di) {
        int posisi = html.indexOf(label);
        assertTrue(posisi > 0, di + " kehilangan label \"" + label + "\"");
        String sekitar = html.substring(posisi,
                Math.min(html.length(), posisi + 300));
        nama = ">" + nama + "<";
        // The inspected excerpt is included in the failure message.
        assertTrue(sekitar.contains(nama),
                di + ": \"" + label + "\" ada tetapi nilainya tidak terisi. "
                        + "Ekspresi username kemungkinan tidak dinilai. "
                        + "Yang terbaca di sekitarnya: <<<" + sekitar + ">>>");
    }

    @Test
    void namaPenyusunBenarBenarDisisipkan() {
        // Checks that the expression is evaluated, not merely that the column exists; a misspelled `th:text` leaves the cell empty without an error.
        String device = render("report_device", "rina", true, 6, "24h");
        adaDiDekat(device, "Disusun oleh", "rina", "report_device");
        assertFalse(device.contains("${username}"),
                "ekspresi username tidak dinilai, tercetak apa adanya");

        String cetak = render("report_cetak", "rina", true, null, "24h");
        adaDiDekat(cetak, "Disusun oleh", "rina", "report_cetak");
        assertFalse(cetak.contains("${username}"),
                "ekspresi username tidak dinilai, tercetak apa adanya");
    }

    @Test
    void kopDokumenDicetakSEBELUMPerabotLayar() {
        // The print letterhead must come before the screen status card, since print order follows HTML order.
        String html = render("report_device", "rina", true, 6, "24h");
        int kop = html.indexOf("id=\"kepala-cetak\"");
        int kartu = html.indexOf("id=\"kepala\"");
        int kaki = html.indexOf("id=\"kaki-cetak\"");
        assertTrue(kop > 0 && kartu > 0 && kaki > 0,
                "salah satu penanda kepala/kaki cetak hilang");
        assertTrue(kop < kartu,
                "kop dokumen harus mendahului kartu status layar di HTML, "
                        + "karena urutan di kertas mengikuti urutan di HTML");
        assertTrue(kaki > kartu, "kaki dokumen harus berada di akhir halaman");
    }

    @Test
    void kakiCetakTidakMemakaiNamaKelasYangSudahDipakai() {
        // The footnote must not use the `.sumber` class, which the traffic table already uses for the uppercase SNMP/SSH badge.
        String html = render("report_device", "rina", true, 6, "24h");
        int kaki = html.indexOf("id=\"kaki-cetak\"");
        assertTrue(kaki > 0, "kaki cetak hilang");
        String blok = html.substring(kaki,
                Math.min(html.length(), kaki + 400));
        assertFalse(blok.contains("class=\"sumber\""),
                "kaki cetak memakai kelas `.sumber` yang sudah dipakai lencana "
                        + "tabel lalu lintas; catatan kakinya akan tercetak "
                        + "huruf besar di dalam kotak lencana");
        assertTrue(blok.contains("catatan-sumber"),
                "kaki cetak kehilangan blok catatan sumber data");
    }

    @Test
    void perabotLayarDisembunyikanDariKertas() {
        // Guards the print rule that hides `position: fixed` elements, which would otherwise repeat on every printed page and cover data.
        String device = render("report_device", "rina", true, 6, "24h");
        assertTrue(device.contains("@media print"),
                "blok gaya cetak hilang dari report_device");
        assertTrue(device.contains("#kepala-cetak, #kaki-cetak { display: none; }"),
                "kepala & kaki cetak harus tersembunyi di layar");
        assertTrue(device.contains("#jejak") && device.contains("#periode"),
                "penanda perabot layar yang disembunyikan saat cetak hilang");
    }
}
