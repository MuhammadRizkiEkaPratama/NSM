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

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import static org.junit.jupiter.api.Assertions.assertTrue;

/** Renders EVERY NSM page and writes the result to `target/render/`. As a guard, it proves all pages still render after sweeping changes. As review material, the files can be opened in a browser and measured. Rendering through Thymeleaf avoids login; JavaScript-fetched content is not included (pages show the skeleton and "Memuat..."). */
@SpringBootTest
class RenderSemuaHalamanTest {

    /** All page templates; fragments are excluded since they cannot stand alone. */
    private static final String[] HALAMAN = {
        "dashboard", "report", "report_device", "services", "traffic",
        "kesehatan", "backup", "insiden", "insiden_detail", "wawasan",
        "agen", "tenant", "syslog", "ldap", "device_ssh",
        "konfig", "konfig_drift", "konfig_drift_device", "konfig_firewall",
        "konfig_identitas", "konfig_kepatuhan", "konfig_pagar",
        "konfig_penemuan",
        "konfig_perintah", "konfig_potret", "konfig_sot", "konfig_sot_device",
        "admin_audit", "admin_users",
        "account_email", "account_notifikasi", "account_password",
        "login", "signup", "forgot", "reset"
    };

    @Autowired
    private SpringTemplateEngine mesin;

    private String render(String templat) {
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        ctx.setVariable("username", "admin");
        ctx.setVariable("isAdmin", true);

        // Variables normally supplied by Spring Security or the controller. Listed one by one rather than caught with try/catch, which would report green for pages that never formed.
        ctx.setVariable("_csrf", new org.springframework.security.web.csrf.DefaultCsrfToken(
                "X-CSRF-TOKEN", "_csrf", "uji-token"));
        ctx.setVariable("lihatPenelusuran", false);
        ctx.setVariable("hanyaKeamanan", false);
        return mesin.process(templat, ctx);
    }

    @Test
    void semuaHalamanTerenderDanDitulisKeBerkas() throws IOException {
        Path keluar = Path.of("target", "render");
        Files.createDirectories(keluar);

        List<String> gagal = new ArrayList<>();
        int berhasil = 0;

        for (String t : HALAMAN) {
            String html;
            try {
                html = render(t);
            } catch (Exception e) {
                gagal.add(t + ": " + e.getClass().getSimpleName() + " " + e.getMessage());
                continue;
            }

            // Absolute `/css/...` paths do not resolve when opened from disk, so they are rewritten relative to the project root to use the real CSS. A timestamp on each asset prevents the browser from caching stale CSS.
            String cap = "?v=" + System.currentTimeMillis();
            String dipratinjau = html
                    .replace("href=\"/", "href=\"../../src/main/resources/static/")
                    .replace("src=\"/", "src=\"../../src/main/resources/static/")
                    .replaceAll("(\\.(?:css|js|svg))\"", "$1" + cap + "\"");
            Files.writeString(keluar.resolve(t + ".html"), dipratinjau,
                    StandardCharsets.UTF_8);
            berhasil++;
        }

        assertTrue(gagal.isEmpty(),
                "halaman yang gagal dirender: " + String.join(" | ", gagal));
        assertTrue(berhasil == HALAMAN.length,
                "hanya " + berhasil + " dari " + HALAMAN.length + " halaman terender");
    }

    @Test
    void setiapHalamanMemuatHurufDanTemaYangBaru() {
        // Every page must load `tema.js` and the Manrope font; a missed one falls back silently to the system font and can never go light.
        List<String> tanpaTema = new ArrayList<>();
        List<String> tanpaHuruf = new ArrayList<>();

        for (String t : HALAMAN) {
            String html = render(t);
            if (!html.contains("/js/tema.js")) {
                tanpaTema.add(t);
            }
            if (!html.contains("/vendor/font/manrope.css")) {
                tanpaHuruf.add(t);
            }
        }

        assertTrue(tanpaTema.isEmpty(), "tidak memuat tema.js: " + tanpaTema);
        assertTrue(tanpaHuruf.isEmpty(), "tidak memuat Manrope: " + tanpaHuruf);
    }

    @Test
    void tidakAdaHalamanYangMasihMerujukSpriteIkonLama() {
        // Icon references that were missed do not throw; the icon is simply not drawn.
        List<String> basi = new ArrayList<>();
        for (String t : HALAMAN) {
            if (render(t).contains("ikon-lucide.svg")) {
                basi.add(t);
            }
        }
        assertTrue(basi.isEmpty(), "masih merujuk sprite ikon lama: " + basi);
    }
}
