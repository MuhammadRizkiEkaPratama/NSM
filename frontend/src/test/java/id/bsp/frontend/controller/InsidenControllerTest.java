package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests InsidenController, whose only real decision is clamping the time window. Without an upper bound, `?jam=99999999` would make Python scan the whole incident history and could stall the poller sharing the database. The rest only forwards JSON from Python. No Spring context, so it runs with MySQL down. */
class InsidenControllerTest {

    /** Fake that records the hours value it receives. */
    private static class ApiPencatat extends NetmonApiClient {
        final List<Integer> jamDiterima = new ArrayList<>();

        @Override
        public Object getInsiden(int jam) {
            jamDiterima.add(jam);
            return Map.of("terbuka", List.of(), "pulih", List.of(), "jam", jam);
        }
    }

    /** Audit that does not touch the database. */
    private static class AuditDiam extends AuditService {
        AuditDiam() { super(null); }

        @Override
        public void logRequest(String aksi, String target, String detail,
                               boolean berhasil, jakarta.servlet.http.HttpServletRequest r) {
        }
    }

    private ApiPencatat api;
    private InsidenController c;

    private void siapkan() {
        api = new ApiPencatat();
        c = new InsidenController(api, new AuditDiam(), null);
    }

    @Test
    void jamWajarDilewatkanApaAdanya() {
        siapkan();
        c.daftarApi(24);
        c.daftarApi(168);
        assertEquals(List.of(24, 168), api.jamDiterima);
    }

    @Test
    void jamYangTerlaluBesarDIPOTONG() {
        siapkan();
        c.daftarApi(99999999);
        assertEquals(1, api.jamDiterima.size());
        assertEquals(720, api.jamDiterima.get(0),
                "jendela tak terbatas memaksa Python memindai seluruh riwayat");
    }

    @Test
    void jamNolAtauNegatifDINAIKKAN() {
        // Counterpart: a limiter checking only the upper bound would pass `jam=0` and `jam=-5` through, giving a meaningless empty page.
        siapkan();
        c.daftarApi(0);
        c.daftarApi(-5);
        assertEquals(List.of(1, 1), api.jamDiterima);
    }

    @Test
    void halamanMengembalikanNamaTemplatYangBENAR() {
        // A wrong template name is a 500 on open; cheap to test.
        siapkan();
        assertEquals("insiden", c.daftar(null, null));
        assertEquals("insiden_detail", c.detail(3, new org.springframework.ui.ExtendedModelMap(), null));
    }

    @Test
    void nomorInsidenSampaiKeModel() {
        // If the number does not arrive, the page loads and never shows data, with no error.
        siapkan();
        org.springframework.ui.ExtendedModelMap model = new org.springframework.ui.ExtendedModelMap();
        c.detail(77, model, null);
        assertTrue(model.containsAttribute("insidenId"));
        assertEquals(77, model.getAttribute("insidenId"));
    }
}
