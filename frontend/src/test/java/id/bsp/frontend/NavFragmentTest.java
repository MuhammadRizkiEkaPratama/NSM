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

/** Renders the navigation fragment for real, not just reading it. Fragment errors would pass Mockito controller tests and then break every page with a 500. Rendered directly through the template engine, without HTTP or MockMvc. */
@SpringBootTest
class NavFragmentTest {

    @Autowired
    private SpringTemplateEngine mesin;

    /** Renders the bar fragment for one user state, through the wrapper template `uji_nav.html` in `src/test/resources` (a parameterized fragment can only be called from inside another template). */
    private String render(String halaman, String username, boolean isAdmin) {
        // WEB context, not a plain Context: `@{/...}` links need a context path from an HTTP request.
        MockServletContext servletContext = new MockServletContext();
        MockHttpServletRequest request = new MockHttpServletRequest(servletContext);
        MockHttpServletResponse response = new MockHttpServletResponse();
        IServletWebExchange exchange = JakartaServletWebApplication
                .buildApplication(servletContext)
                .buildExchange(request, response);

        WebContext ctx = new WebContext(exchange, Locale.forLanguageTag("id"));
        // NavAdvice supplies both to every page at runtime.
        ctx.setVariable("username", username);
        ctx.setVariable("isAdmin", isAdmin);
        ctx.setVariable("halamanUji", halaman);
        return mesin.process("uji_nav", ctx);
    }

    @Test
    void semuaHalamanBisaDirenderTanpaGalat() {
        // Every known marker value; an expression error in any of them fails here.
        String[] halaman = {"dashboard", "report", "insiden", "services",
                "traffic", "users", "audit", "backup", "kesehatan", "konfig",
                "notifikasi", "email", "password", ""};
        for (String h : halaman) {
            String html = render(h, "admin", true);
            assertTrue(html.contains("<nav"),
                    "fragmen kosong atau gagal dirender untuk halaman '" + h + "'");
        }
    }

    @Test
    void adminMelihatMenuAdminDanViewerTidak() {
        String htmlAdmin = render("dashboard", "admin", true);
        assertTrue(htmlAdmin.contains("Kelola User"), "admin harus melihat Kelola User");
        assertTrue(htmlAdmin.contains("Audit Log"), "admin harus melihat Audit Log");
        assertTrue(htmlAdmin.contains("Kesehatan"), "admin harus melihat Kesehatan");

        // Hiding a link is not a security measure (the controller guard is tested in AdminControllerTest); this only checks that `th:if` is still attached.
        String htmlViewer = render("dashboard", "viewer", false);
        assertFalse(htmlViewer.contains("Kelola User"), "viewer tidak boleh melihat Kelola User");
        assertFalse(htmlViewer.contains("Audit Log"), "viewer tidak boleh melihat Audit Log");
        assertFalse(htmlViewer.contains("Backup"), "viewer tidak boleh melihat Backup");
        assertFalse(htmlViewer.contains("/admin/konfig"),
                "viewer tidak boleh melihat tautan Konfigurasi");
    }

    @Test
    void halamanDiDalamMenuTetapMenandaiJudulMenunya() {
        // Without `punya-aktif` the bar would show no current page.
        assertTrue(render("audit", "admin", true).contains("punya-aktif"),
                "judul menu Admin harus ikut ditandai saat Audit Log dibuka");
        assertTrue(render("users", "admin", true).contains("punya-aktif"),
                "judul menu Admin harus ikut ditandai saat Kelola User dibuka");
        assertTrue(render("password", "admin", true).contains("punya-aktif"),
                "judul menu Akun harus ikut ditandai saat Password dibuka");
        assertTrue(render("konfig", "admin", true).contains("punya-aktif"),
                "judul menu Admin harus ikut ditandai saat Konfigurasi dibuka");

        // Pages whose link is in the main row must not mark the menu.
        assertFalse(render("dashboard", "admin", true).contains("punya-aktif"),
                "Dashboard ada di baris utama, tidak boleh menandai menu mana pun");
    }

    // The density-toggle test was removed together with the toggle itself; `--rapat` in `nsm.css` is fixed at 0.72.

    @Test
    void logoutTetapTerlihatLangsungTanpaMasukMenu() {
        // Deliberate: the logout link stays outside the menu.
        String html = render("dashboard", "admin", true);
        int posisiMenu = html.indexOf("isi-menu");
        int posisiLogout = html.indexOf("/logout");
        assertTrue(posisiLogout > 0, "tombol Logout harus ada");
        assertTrue(posisiLogout > posisiMenu,
                "Logout harus berada di luar dan sesudah blok menu");
    }
}
