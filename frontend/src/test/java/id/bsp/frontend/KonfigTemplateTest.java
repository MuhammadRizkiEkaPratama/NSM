package id.bsp.frontend;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockServletContext;
import org.springframework.security.web.csrf.DefaultCsrfToken;
import org.thymeleaf.context.WebContext;
import org.thymeleaf.spring6.SpringTemplateEngine;
import org.thymeleaf.web.servlet.IServletWebExchange;
import org.thymeleaf.web.servlet.JakartaServletWebApplication;

import java.util.Locale;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Renders the six Configuration templates for real. Guards what fails silently: each page still loads its family CSS/JS, each content page keeps its way back (they are not in the menu), and the menu bar does not grow past six links (1366px). */
@SpringBootTest
class KonfigTemplateTest {

    /** Kelima halaman isi beserta nama templatnya. */
    private static final String[][] HALAMAN = {
            {"konfig_perintah",  "perintah",  "/admin/konfig/perintah"},
            {"konfig_kepatuhan", "kepatuhan", "/admin/konfig/kepatuhan"},
            {"konfig_identitas", "identitas", "/admin/konfig/identitas"},
            {"konfig_firewall",  "firewall",  "/admin/konfig/firewall"},
            {"konfig_potret",    "potret",    "/admin/konfig/potret"}
    };

    @Autowired
    private SpringTemplateEngine mesin;

    /** Renders one full template with a WEB context; `@{/...}` links need a context path (same as NavFragmentTest). */
    private String render(String templat) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        // Supplied by NavAdvice to every page at runtime.
        ctx.setVariable("username", "admin");
        ctx.setVariable("isAdmin", true);
        // Only the command page uses the CSRF token, but it is set for all: a missing token breaks render with an unhelpful error.
        ctx.setVariable("_csrf", new DefaultCsrfToken("X-CSRF-TOKEN", "_csrf", "uji"));
        return mesin.process(templat, ctx);
    }

    @Test
    void keenamHalamanBisaDirenderTanpaGalat() {
        assertTrue(render("konfig").contains("<nav"),
                "beranda Konfigurasi gagal dirender");
        for (String[] h : HALAMAN) {
            assertTrue(render(h[0]).contains("<nav"),
                    "templat '" + h[0] + "' gagal dirender");
        }
    }

    @Test
    void tiapHalamanMemuatGayaDanSkripKeluarganya() {
        // konfig.css holds all styles of this page family; a page that forgets it still renders but unstyled.
        String[] semua = {"konfig", "konfig_perintah", "konfig_kepatuhan",
                "konfig_identitas", "konfig_firewall", "konfig_potret"};
        for (String t : semua) {
            String html = render(t);
            assertTrue(html.contains("/css/konfig.css"),
                    "templat '" + t + "' tidak memuat konfig.css");
            assertTrue(html.contains("/konfig.js"),
                    "templat '" + t + "' tidak memuat konfig.js");
            assertTrue(html.contains("name=\"viewport\""),
                    "templat '" + t + "' tidak punya meta viewport; di ponsel "
                            + "ia akan tampil menyusut ~38%");
        }
    }

    @Test
    void berandaMenautkanKelimaHalamanIsinya() {
        String html = render("konfig");
        for (String[] h : HALAMAN) {
            assertTrue(html.contains("href=\"" + h[2] + "\""),
                    "beranda tidak menautkan " + h[2]);
        }
    }

    @Test
    void tiapHalamanIsiPunyaJalanPulangDanJalanMenyamping() {
        for (String[] h : HALAMAN) {
            String html = render(h[0]);

            assertTrue(html.contains("href=\"/admin/konfig\""),
                    "'" + h[0] + "' kehilangan jalan pulang ke beranda");

            // The current page is plain text, not a link to itself.
            assertFalse(html.contains("href=\"" + h[2] + "\""),
                    "'" + h[0] + "' menautkan dirinya sendiri di jalur");

            // The four siblings stay directly reachable without going through the home page.
            for (String[] lain : HALAMAN) {
                if (lain[1].equals(h[1])) continue;
                assertTrue(html.contains("href=\"" + lain[2] + "\""),
                        "'" + h[0] + "' tidak bisa berpindah ke " + lain[2]);
            }
        }
    }

    @Test
    void bilahMenuTidakIkutBertambah() {
        // The content pages are reached through home-page cards and the page strip, not the menu, which carries only one configuration link.
        String html = render("konfig");
        int nav = html.indexOf("<nav");
        int tutupNav = html.indexOf("</nav>");
        assertTrue(nav > 0 && tutupNav > nav, "bilah menu tidak ditemukan");
        String isiNav = html.substring(nav, tutupNav);

        assertFalse(isiNav.contains("/admin/konfig/"),
                "ada halaman anak yang menyelinap ke bilah menu; menu ini "
                        + "pernah dipangkas dari sebelas jadi enam tautan, dan "
                        + "lima tautan baru akan membatalkannya");

        int jumlah = 0, dari = 0;
        while ((dari = isiNav.indexOf("/admin/konfig", dari)) >= 0) { jumlah++; dari++; }
        assertEquals(1, jumlah,
                "bilah menu harus memuat tepat satu tautan konfigurasi");
    }

    // Source-of-truth pages: not added to `HALAMAN` because that array assumes /konfig.js, while konfig_sot*.html load /sot.js. A separate test repeats the same three checks for that script family.

    /** Extra context `deviceId`, read only by `konfig_sot_device`. */
    private String renderSotDevice(int deviceId) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);
        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        ctx.setVariable("username", "admin");
        ctx.setVariable("isAdmin", true);
        ctx.setVariable("_csrf", new DefaultCsrfToken("X-CSRF-TOKEN", "_csrf", "uji"));
        ctx.setVariable("deviceId", deviceId);
        return mesin.process("konfig_sot_device", ctx);
    }

    @Test
    void keduaHalamanSotBisaDirenderTanpaGalat() {
        assertTrue(render("konfig_sot").contains("<nav"),
                "templat 'konfig_sot' gagal dirender");
        assertTrue(renderSotDevice(5).contains("<nav"),
                "templat 'konfig_sot_device' gagal dirender");
    }

    @Test
    void keduaHalamanSotMemuatGayaDanSkripKeluarganya() {
        // sot.js, NOT konfig.js -- see the note above the HALAMAN array.
        for (String html : new String[]{render("konfig_sot"), renderSotDevice(5)}) {
            assertTrue(html.contains("/css/konfig.css"),
                    "halaman SoT tidak memuat konfig.css");
            assertTrue(html.contains("/sot.js"),
                    "halaman SoT tidak memuat sot.js");
            assertTrue(html.contains("name=\"viewport\""),
                    "halaman SoT tidak punya meta viewport");
        }
    }

    @Test
    void halamanDetailSotPunyaMetaCsrf() {
        // Regression: the template once lacked <meta name="_csrf">, so "Simpan" failed with an unexplained 403.
        String html = renderSotDevice(5);
        assertTrue(html.contains("name=\"_csrf\""),
                "konfig_sot_device kehilangan meta _csrf -- tombol Simpan "
                        + "akan ditolak 403 oleh Spring Security");
        assertTrue(html.contains("name=\"_csrf_header\""),
                "konfig_sot_device kehilangan meta _csrf_header");
    }

    @Test
    void berandaMenautkanKartuSot() {
        assertTrue(render("konfig").contains("href=\"/admin/konfig/sot\""),
                "beranda tidak menautkan kartu Sumber Kebenaran");
    }

    @Test
    void halamanDaftarSotPunyaJalanPulang() {
        assertTrue(render("konfig_sot").contains("href=\"/admin/konfig\""),
                "'konfig_sot' kehilangan jalan pulang ke beranda");
    }

    // Drift detection pages: same pattern as SoT but read-only, so `konfig_drift_device` has no _csrf meta and no Save button.

    private String renderDriftDevice(int deviceId) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);
        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        ctx.setVariable("username", "admin");
        ctx.setVariable("isAdmin", true);
        ctx.setVariable("deviceId", deviceId);
        return mesin.process("konfig_drift_device", ctx);
    }

    @Test
    void keduaHalamanDriftBisaDirenderTanpaGalat() {
        assertTrue(render("konfig_drift").contains("<nav"),
                "templat 'konfig_drift' gagal dirender");
        assertTrue(renderDriftDevice(5).contains("<nav"),
                "templat 'konfig_drift_device' gagal dirender");
    }

    @Test
    void keduaHalamanDriftMemuatGayaDanSkripKeluarganya() {
        for (String html : new String[]{render("konfig_drift"), renderDriftDevice(5)}) {
            assertTrue(html.contains("/css/konfig.css"),
                    "halaman Drift tidak memuat konfig.css");
            assertTrue(html.contains("/drift.js"),
                    "halaman Drift tidak memuat drift.js");
        }
    }

    @Test
    void berandaMenautkanKartuDrift() {
        assertTrue(render("konfig").contains("href=\"/admin/konfig/drift\""),
                "beranda tidak menautkan kartu Deteksi Penyimpangan");
    }

    @Test
    void halamanDaftarDriftPunyaJalanPulang() {
        assertTrue(render("konfig_drift").contains("href=\"/admin/konfig\""),
                "'konfig_drift' kehilangan jalan pulang ke beranda");
    }

    // Automation guard: a single read-only page (no per-device detail).

    @Test
    void halamanPagarBisaDirenderTanpaGalat() {
        assertTrue(render("konfig_pagar").contains("<nav"),
                "templat 'konfig_pagar' gagal dirender");
    }

    @Test
    void halamanPagarMemuatGayaDanSkripKeluarganya() {
        String html = render("konfig_pagar");
        assertTrue(html.contains("/css/konfig.css"), "halaman Pagar tidak memuat konfig.css");
        assertTrue(html.contains("/pagar.js"), "halaman Pagar tidak memuat pagar.js");
    }

    @Test
    void berandaMenautkanKartuPagar() {
        assertTrue(render("konfig").contains("href=\"/admin/konfig/pagar\""),
                "beranda tidak menautkan kartu Pagar Otomasi");
    }

    @Test
    void halamanPagarPunyaJalanPulang() {
        assertTrue(render("konfig_pagar").contains("href=\"/admin/konfig\""),
                "'konfig_pagar' kehilangan jalan pulang ke beranda");
    }

    // Device discovery: the only configuration page that SENDS PACKETS and can ADD devices, so it gets safety checks beyond rendering.

    @Test
    void halamanPenemuanBisaDirenderTanpaGalat() {
        assertTrue(render("konfig_penemuan").contains("<nav"),
                "templat 'konfig_penemuan' gagal dirender");
    }

    @Test
    void halamanPenemuanMemuatGayaDanSkripKeluarganya() {
        String html = render("konfig_penemuan");
        assertTrue(html.contains("/css/konfig.css"),
                "halaman Penemuan tidak memuat konfig.css");
        assertTrue(html.contains("/penemuan.js"),
                "halaman Penemuan tidak memuat penemuan.js");
    }

    @Test
    void halamanPenemuanPunyaMetaCsrf() {
        // All three buttons POST; without the _csrf meta Spring Security returns 403, which reads like a permissions error.
        String html = render("konfig_penemuan");
        assertTrue(html.contains("name=\"_csrf\""),
                "'konfig_penemuan' tidak menanam token CSRF; ketiga tombolnya akan 403");
        assertTrue(html.contains("name=\"_csrf_header\""),
                "'konfig_penemuan' tidak menanam nama kepala CSRF");
    }

    @Test
    void halamanPenemuanMengatakanPerangkatDibuatBelumAktif() {
        // The sentence that an approved device is not yet monitored must be present, or users will think NSM is broken.
        String html = render("konfig_penemuan");
        assertTrue(html.contains("BELUM AKTIF"),
                "halaman Penemuan tidak menyebut bahwa perangkat dibuat belum aktif");
    }

    @Test
    void halamanPenemuanMenjelaskanTingkatBukti() {
        // A device matching the tiered `dokumentasi` definition is recognized, but nobody has run that platform's commands on a real device; the approver should be told.
        String html = render("konfig_penemuan");
        assertTrue(html.contains("dokumentasi"),
                "halaman Penemuan tidak menjelaskan arti tingkat bukti");
    }

    @Test
    void berandaMenautkanKartuPenemuan() {
        assertTrue(render("konfig").contains("href=\"/admin/konfig/penemuan\""),
                "beranda tidak menautkan kartu Penemuan Perangkat");
    }

    @Test
    void halamanPenemuanPunyaJalanPulang() {
        assertTrue(render("konfig_penemuan").contains("href=\"/admin/konfig\""),
                "'konfig_penemuan' kehilangan jalan pulang ke beranda");
    }
}
