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

/** Renders both Incident pages through the template engine (same pattern as NavFragmentTest). A Thymeleaf expression error is a 500 that controller tests cannot catch. `insiden_detail.html` also puts `${insidenId}` in a `<meta>` that its JavaScript reads; if it is missing the page loads silently with no data. */
@SpringBootTest
class InsidenTemplateTest {

    @Autowired
    private SpringTemplateEngine mesin;

    private String render(String templat, Integer insidenId) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        // NavAdvice supplies both to every page at runtime.
        ctx.setVariable("username", "admin");
        ctx.setVariable("isAdmin", true);
        if (insidenId != null) ctx.setVariable("insidenId", insidenId);
        return mesin.process(templat, ctx);
    }

    @Test
    void daftarInsidenBisaDirender() {
        String html = render("insiden", null);
        assertTrue(html.contains("<nav"), "navigasi tidak ikut terender");
        assertTrue(html.contains("id=\"terbuka\""),
                "wadah insiden berlangsung hilang; JavaScript tidak punya tempat menulis");
        assertTrue(html.contains("id=\"pulih\""), "wadah insiden pulih hilang");
        assertTrue(html.contains("id=\"ringkas-insiden\""), "kisi ringkasan hilang");
        assertTrue(html.contains("/insiden.js"),
                "berkas JavaScript-nya tidak dimuat; halaman akan kosong selamanya");
        assertTrue(html.contains("/css/insiden.css"), "gaya halamannya tidak dimuat");
    }

    @Test
    void navigasiMenandaiHalamanInsidenSedangDibuka() {
        // Without the active marker the menu would show no current page.
        String html = render("insiden", null);
        int posisi = html.indexOf("/insiden\"");
        assertTrue(posisi > 0, "tautan Insiden tidak ada di navigasi");
        String sekitar = html.substring(posisi, Math.min(html.length(), posisi + 200));
        assertTrue(sekitar.contains("aktif"),
                "tautan Insiden tidak ditandai aktif: " + sekitar);
    }

    @Test
    void garisWaktuBisaDirenderDanMembawaIdnya() {
        String html = render("insiden_detail", 42);
        assertTrue(html.contains("<nav"), "navigasi tidak ikut terender");
        assertTrue(html.contains("id=\"garis-waktu\""), "wadah garis waktu hilang");
        assertTrue(html.contains("id=\"kepala-insiden\""), "wadah kepala hilang");

        // Most important check here: JavaScript reads the incident number from this meta; if it is missing or empty the page loads without errors and never shows data.
        assertTrue(html.contains("name=\"insiden-id\""), "meta insiden-id hilang");
        assertTrue(html.contains("content=\"42\""),
                "nomor insiden tidak sampai ke meta; halaman akan kosong tanpa galat");

        // The back link to the list must exist; this page is not in the menu.
        assertTrue(html.contains("Semua insiden"), "jalan pulang ke daftar hilang");
    }

    @Test
    void halamanInsidenTidakMemuatSkripSebaris() {
        // The CSP forbids inline scripts (no `unsafe-inline`); an inline `<script>` would pass other tests and then be blocked silently by the browser.
        for (String t : new String[]{"insiden", "insiden_detail"}) {
            String html = render(t, 7);
            int i = 0;
            while ((i = html.indexOf("<script", i)) >= 0) {
                int tutup = html.indexOf('>', i);
                int akhir = html.indexOf("</script>", tutup);
                String isi = tutup >= 0 && akhir > tutup
                        ? html.substring(tutup + 1, akhir).trim() : "";
                assertTrue(isi.isEmpty(),
                        t + ": ada <script> berisi kode sebaris: " + isi);
                i = tutup + 1;
            }
        }
    }

    @Test
    void tidakAdaKebocoranEkspresiThymeleafYangBelumTerproses() {
        // A misspelled expression may render literally instead of throwing.
        for (String t : new String[]{"insiden", "insiden_detail"}) {
            String html = render(t, 9);
            assertFalse(html.contains("${"),
                    t + ": ada ekspresi Thymeleaf yang tidak terproses");
            assertFalse(html.contains("th:"),
                    t + ": ada atribut th: yang tersisa di keluaran");
        }
    }
}
