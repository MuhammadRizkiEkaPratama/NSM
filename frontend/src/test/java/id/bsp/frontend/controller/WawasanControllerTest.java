package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests WawasanController and TenantController. Guards two decisions: clamping the time window (an unbounded `?jam=` makes Python scan the whole history and can stall the poller) and template names (a wrong name is a 500). The rest only forwards JSON from Python. */
class WawasanControllerTest {

    private static class ApiPencatat extends NetmonApiClient {
        final List<Integer> jamPolaLog = new ArrayList<>();
        final List<Integer> jamAgen = new ArrayList<>();
        int panggilanBaseline = 0;
        int panggilanPrakiraan = 0;
        int panggilanAnggaran = 0;
        int panggilanTenant = 0;

        @Override
        public Object getBaseline() {
            panggilanBaseline++;
            return Map.of("semua", List.of(), "aneh", List.of());
        }

        @Override
        public Object getPolaLog(int jam) {
            jamPolaLog.add(jam);
            return Map.of("jam", jam, "baru", List.of(), "tersering", List.of());
        }

        @Override
        public Object getPrakiraan() {
            panggilanPrakiraan++;
            return Map.of("bandwidth", List.of(), "latency", List.of());
        }

        @Override
        public Object getPrakiraanAnggaran() {
            panggilanAnggaran++;
            return Map.of("anggaran", List.of());
        }

        @Override
        public Object getAgenSoc(int jam) {
            jamAgen.add(jam);
            return Map.of("jam", jam, "usulan", List.of());
        }

        @Override
        public Object getTenant() {
            panggilanTenant++;
            return Map.of("tenant", List.of(), "tanpa_tenant", List.of());
        }
    }

    private static class AuditDiam extends AuditService {
        AuditDiam() { super(null); }

        @Override
        public void logRequest(String aksi, String target, String detail,
                               boolean berhasil,
                               jakarta.servlet.http.HttpServletRequest r) {
            // Deliberately empty.
        }
    }

    private ApiPencatat api;
    private WawasanController w;
    private TenantController t;

    @BeforeEach
    void siapkan() {
        api = new ApiPencatat();
        w = new WawasanController(api, new AuditDiam());
        t = new TenantController(api, new AuditDiam());
    }

    @Test
    void namaTemplatBENAR() {
        assertEquals("wawasan", w.wawasan(null, null));
        assertEquals("agen", w.agen(null, null));
        assertEquals("tenant", t.halaman(null, null));
    }

    @Test
    void jamWajarDilewatkanApaAdanya() {
        w.polaLog(24);
        w.agenSoc(168);
        assertEquals(List.of(24), api.jamPolaLog);
        assertEquals(List.of(168), api.jamAgen);
    }

    @Test
    void jamYangTerlaluBesarDIPOTONG() {
        w.polaLog(99999999);
        w.agenSoc(99999999);
        assertEquals(720, api.jamPolaLog.get(0),
                "jendela tak terbatas memaksa Python memindai seluruh riwayat");
        assertEquals(720, api.jamAgen.get(0));
    }

    @Test
    void jamNolAtauNegatifDINAIKKAN() {
        // Counterpart: a limiter checking only the upper bound would pass `jam=0` through, giving an empty page that reads like "no data".
        w.polaLog(0);
        w.agenSoc(-5);
        assertEquals(1, api.jamPolaLog.get(0));
        assertEquals(1, api.jamAgen.get(0));
    }

    @Test
    void anggaranPunyaEndpointSENDIRI() {
        // The error budget takes 8.5 s for 11 devices versus 3.7 s for the other two forecast parts, so merging would block the page on the slowest.
        w.prakiraan();
        assertEquals(1, api.panggilanPrakiraan);
        assertEquals(0, api.panggilanAnggaran,
                "/api/prakiraan tidak boleh ikut menghitung anggaran galat");

        w.prakiraanAnggaran();
        assertEquals(1, api.panggilanAnggaran);
        assertEquals(1, api.panggilanPrakiraan,
                "/api/prakiraan/anggaran tidak boleh ikut menghitung tren");
    }

    @Test
    void keempatBagianWawasanPunyaJalurnyaSendiri() {
        // The page loads four SEPARATE parts so the fast ones show first; if one silently calls another, that benefit is lost.
        w.baseline();
        assertEquals(1, api.panggilanBaseline);
        assertEquals(0, api.panggilanPrakiraan);
        assertTrue(api.jamPolaLog.isEmpty());
    }

    @Test
    void tenantDilayaniTerpisah() {
        t.daftar();
        assertEquals(1, api.panggilanTenant);
    }
}
