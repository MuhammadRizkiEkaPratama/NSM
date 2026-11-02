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

/** Renders the Syslog page and checks that its supporting files are loaded. The page is filled entirely by JavaScript, so a missing or misnamed `<script src="/syslog.js">` still returns HTTP 200 and stays empty forever. Same reasoning as `WawasanTemplateTest`. */
@SpringBootTest
class SyslogTemplateTest {

    @Autowired
    private SpringTemplateEngine mesin;

    private String render(boolean isAdmin) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        ctx.setVariable("username", isAdmin ? "admin" : "viewer");
        ctx.setVariable("isAdmin", isAdmin);
        return mesin.process("syslog", ctx);
    }

    @Test
    void halamanTerenderDanNavigasinyaAda() {
        String html = render(true);
        assertTrue(html.contains("<nav"), "navigasi tidak terender");
        assertFalse(html.contains("Exception"), "ada kekecualian di dalam HTML");
    }

    @Test
    void berkasPendukungnyaIkutDimuat() {
        String html = render(true);
        assertTrue(html.contains("/syslog.js"),
                "syslog.js tidak dimuat; halaman akan terlihat sempurna dan kosong selamanya");
        assertTrue(html.contains("/css/syslog.css"),
                "syslog.css tidak dimuat");
        assertTrue(html.contains("/vendor/echarts.min.js"),
                "ECharts tidak dimuat; grafiknya tidak akan pernah muncul");
        assertTrue(html.contains("/vendor/font/manrope.css"),
                "huruf Manrope tidak dimuat; halaman jatuh ke huruf sistem tanpa tanda");
        assertTrue(html.contains("/js/tema.js"),
                "tema.js tidak dimuat; mode terang tidak akan pernah menyala");
    }

    @Test
    void kerangkaYangDiisiJavaScriptSemuanyaAda() {
        String html = render(true);
        // If any of these ids is missing or renamed, syslog.js fails silently (querySelector returns null and addEventListener throws).
        for (String id : new String[]{
                "sl-ubin", "sl-grafik", "sl-tag", "sl-pengirim", "sl-baris",
                "sl-jam", "sl-cari", "sl-penting",
                "sl-sebelum", "sl-sesudah", "sl-halaman-ket", "sl-saring-aktif",
                "sl-grafik-ket", "sl-grafik-kosong"}) {
            assertTrue(html.contains("id=\"" + id + "\""),
                    "elemen #" + id + " hilang dari templat; syslog.js akan berhenti diam-diam");
        }
    }

    @Test
    void tabelnyaLimaKolomSesuaiAturanTampilan() {
        String html = render(true);
        int th = html.split("<th scope=\"col\">", -1).length - 1;
        assertTrue(th == 5,
                "tabel pesan harus 5 kolom sesuai keputusan tampilan, terhitung " + th);
        assertTrue(html.contains("Sebelumnya") && html.contains("Berikutnya"),
                "tombol paginasi tidak ada; 2.000 pesan akan tumpah ke satu halaman");
    }

    @Test
    void kejujuranTentangSyslogTidakDihapusDariHalaman() {
        // Required: UDP syslog is unauthenticated and device names on this page are guesses from the sender address, so the page must say so.
        String html = render(true);
        assertTrue(html.contains("tidak terautentikasi"),
                "peringatan bahwa syslog tidak terautentikasi hilang dari halaman");
        assertTrue(html.contains("TEBAKAN"),
                "keterangan bahwa nama perangkat adalah tebakan hilang dari halaman");
    }

    @Test
    void tautanSyslogAdaDiMenuUntukSemuaOrang() {
        // Not admin-only: non-admins need to see what devices complain about.
        for (boolean admin : new boolean[]{true, false}) {
            String html = render(admin);
            assertTrue(html.contains("/syslog"),
                    "tautan Syslog tidak muncul di menu untuk "
                            + (admin ? "admin" : "viewer"));
        }
    }
}
