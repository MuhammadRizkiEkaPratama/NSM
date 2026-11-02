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

/** Renders the three pages (Insights, SOC Agent, Tenant) for real; same reasoning as `InsidenTemplateTest`. `fragmen/wawasan-jalur` uses `th:block th:if` to hide the Tenant link from viewers, a form that can fail without throwing. */
@SpringBootTest
class WawasanTemplateTest {

    @Autowired
    private SpringTemplateEngine mesin;

    private String render(String templat, boolean isAdmin) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        ctx.setVariable("username", isAdmin ? "admin" : "viewer");
        ctx.setVariable("isAdmin", isAdmin);
        return mesin.process(templat, ctx);
    }

    @Test
    void ketigaHalamanBisaDirender() {
        for (String t : new String[]{"wawasan", "agen", "tenant"}) {
            String html = render(t, true);
            assertTrue(html.contains("<nav"), t + ": navigasi tidak terender");
            assertTrue(html.contains("/wawasan.js"),
                    t + ": JavaScript-nya tidak dimuat; halaman akan kosong selamanya");
            assertTrue(html.contains("/css/wawasan.css"),
                    t + ": gaya halamannya tidak dimuat");
        }
    }

    @Test
    void wadahYangDitulisJavaScriptSemuanyaADA() {
        // If an id is missing, the JavaScript writes to a missing element and the page stays empty with no error.
        String wawasan = render("wawasan", true);
        for (String id : new String[]{"baseline", "baseline-ringkas",
                "baseline-catatan", "pola-baru", "pola-sering", "pola-ringkas",
                "prakiraan-latency", "prakiraan-bandwidth",
                "prakiraan-anggaran"}) {
            assertTrue(wawasan.contains("id=\"" + id + "\""),
                    "wawasan: wadah #" + id + " hilang");
        }

        String agen = render("agen", true);
        for (String id : new String[]{"agen-saklar", "agen-ringkas",
                "agen-usulan", "jendela", "meta"}) {
            assertTrue(agen.contains("id=\"" + id + "\""),
                    "agen: wadah #" + id + " hilang");
        }

        String tenant = render("tenant", true);
        for (String id : new String[]{"tenant-daftar", "tenant-yatim"}) {
            assertTrue(tenant.contains("id=\"" + id + "\""),
                    "tenant: wadah #" + id + " hilang");
        }
    }

    @Test
    void tautanTenantHanyaUNTUKAdmin() {
        // Hiding the link is not security; SecurityConfig guards `/admin/**`. This only checks viewers are not shown a link that would be refused.
        assertTrue(render("wawasan", true).contains("/admin/tenant"),
                "admin harus melihat tautan Tenant");
        assertFalse(render("wawasan", false).contains("/admin/tenant"),
                "viewer tidak boleh melihat tautan Tenant");

        // The two other links stay visible to viewers (read-only pages).
        String viewer = render("wawasan", false);
        assertTrue(viewer.contains("/agen"), "viewer harus melihat Agen SOC");
    }

    @Test
    void halamanYangSedangDibukaTIDAKJadiTautanKeDirinyaSendiri() {
        // A link to the current page does nothing, so it must not be a link.
        String html = render("wawasan", true);
        int posisi = html.indexOf("class=\"kini\"");
        assertTrue(posisi > 0, "halaman aktif tidak ditandai di jalur");
        assertTrue(html.substring(posisi, Math.min(html.length(), posisi + 60))
                        .contains("Wawasan"),
                "yang ditandai bukan Wawasan");
    }

    @Test
    void navigasiMenandaiWawasanSedangDibuka() {
        String html = render("wawasan", true);
        int i = html.indexOf("/wawasan\"");
        assertTrue(i > 0, "tautan Wawasan tidak ada di navigasi");
        assertTrue(html.substring(i, Math.min(html.length(), i + 200))
                        .contains("aktif"),
                "tautan Wawasan tidak ditandai aktif");
    }

    @Test
    void tidakAdaSkripSebarisDanTidakAdaEkspresiYangBocor() {
        // The CSP forbids inline scripts; a template with one would pass the other tests and be blocked silently by the browser.
        for (String t : new String[]{"wawasan", "agen", "tenant"}) {
            String html = render(t, true);
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
            assertFalse(html.contains("${"),
                    t + ": ada ekspresi Thymeleaf yang tidak terproses");
            assertFalse(html.contains("th:"),
                    t + ": ada atribut th: yang tersisa di keluaran");
        }
    }
}
