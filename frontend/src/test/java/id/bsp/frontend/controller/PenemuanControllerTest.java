package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Device discovery: three WRITE paths through this controller. ADMIN/CSRF guards are SecurityConfig rules, not tested here. Checks that Python's refusal reason and code are forwarded as is (the scan guard's human-readable sentence is the point), that refused attempts are audited with ok=false, and that scans are audited even though they change no device (they send packets to every address of a subnet). */
class PenemuanControllerTest {

    private NetmonApiClient api;
    private AuditService audit;
    private PenemuanController c;
    private HttpServletRequest req;

    @BeforeEach
    void siapkan() {
        api = mock(NetmonApiClient.class);
        audit = mock(AuditService.class);
        req = mock(HttpServletRequest.class);
        c = new PenemuanController(api, audit);
    }

    private static Map<String, Object> peta(Object... pasangan) {
        Map<String, Object> m = new HashMap<>();
        for (int i = 0; i < pasangan.length; i += 2) {
            m.put(String.valueOf(pasangan[i]), pasangan[i + 1]);
        }
        return m;
    }

    // 1. Successful scan.
    @Test
    void pindaiBerhasilDiauditBerikutJumlahnya() {
        when(api.postPenemuanPindai(any())).thenReturn(ResponseEntity.ok(
                peta("jaringan", "192.168.56.0/24", "total", 7, "baru", 2, "diperbarui", 5)));

        ResponseEntity<Object> hasil = c.pindai(peta("jaringan", "192.168.56.0/24"), req);

        assertEquals(HttpStatus.OK, hasil.getStatusCode());
        verify(audit).logRequest(eq(AuditService.PENEMUAN_PINDAI),
                eq("192.168.56.0/24"), contains("7 menjawab"), eq(true), any());
    }

    @Test
    void memindaiTetapDiauditWalauTidakMengubahPerangkatApaPun() {
        // A scan that finds nothing is still a scan: packets were sent, so the audit entry must not depend on the result.
        when(api.postPenemuanPindai(any())).thenReturn(ResponseEntity.ok(
                peta("jaringan", "10.0.0.0/28", "total", 0, "baru", 0, "diperbarui", 0)));

        c.pindai(peta("jaringan", "10.0.0.0/28"), req);

        verify(audit).logRequest(eq(AuditService.PENEMUAN_PINDAI),
                eq("10.0.0.0/28"), contains("0 menjawab"), eq(true), any());
    }

    // 2. Python rejection: the sentence arrives and is recorded as a failure
    @Test
    void alasanPenolakanDiteruskanApaAdanyaBerikutKodenya() {
        String alasan = "8.8.8.0/24 bukan rentang alamat pribadi. Memindai alamat "
                      + "publik dari jaringan ini terlihat sebagai pemindaian "
                      + "bermusuhan di sisi penerimanya.";
        when(api.postPenemuanPindai(any())).thenReturn(
                ResponseEntity.badRequest().body(peta("detail", alasan)));

        ResponseEntity<Object> hasil = c.pindai(peta("jaringan", "8.8.8.0/24"), req);

        assertEquals(HttpStatus.BAD_REQUEST, hasil.getStatusCode(),
                "400 dari Python harus tetap 400 -- bukan 500 'terjadi kesalahan'");
        assertTrue(hasil.getBody() instanceof Map<?, ?> m
                        && alasan.equals(m.get("detail")),
                "kalimat penolakannya hilang di perjalanan -> " + hasil.getBody());
    }

    @Test
    void pemindaianYangDitolakDiauditSebagaiGAGAL() {
        when(api.postPenemuanPindai(any())).thenReturn(ResponseEntity.badRequest()
                .body(peta("detail", "10.0.0.0/8 berisi 16777216 alamat, melebihi batas 1024.")));

        c.pindai(peta("jaringan", "10.0.0.0/8"), req);

        verify(audit).logRequest(eq(AuditService.PENEMUAN_PINDAI), eq("10.0.0.0/8"),
                contains("DITOLAK"), eq(false), any());
    }

    @Test
    void alasanPenolakanIkutMasukBarisAudit() {
        // An audit row that only says "DITOLAK" forces people to open the Python log to learn why.
        when(api.postPenemuanPindai(any())).thenReturn(ResponseEntity.badRequest()
                .body(peta("detail", "melebihi batas 1024")));

        c.pindai(peta("jaringan", "10.0.0.0/8"), req);

        verify(audit).logRequest(any(), any(), contains("melebihi batas 1024"),
                eq(false), any());
    }

    // 3. Approval: the only path into the `devices` table.
    @Test
    void persetujuanDiauditDanBarisnyaMENYEBUTperangkatBelumAktif() {
        // The audit note must say the device entered unmonitored; otherwise missing data later reads as data loss.
        when(api.postPenemuanSetujui(anyInt(), any())).thenReturn(ResponseEntity.ok(
                peta("device_id", 12, "nama", "Switch Baru",
                     "ip_address", "192.168.56.150", "aktif", 0)));

        c.setujui(3, peta("nama", "Switch Baru"), req);

        verify(audit).logRequest(eq(AuditService.PENEMUAN_SETUJUI), eq("3"),
                contains("BELUM AKTIF"), eq(true), any());
    }

    @Test
    void barisAuditPersetujuanMenyebutAlamatDanNamanya() {
        when(api.postPenemuanSetujui(anyInt(), any())).thenReturn(ResponseEntity.ok(
                peta("device_id", 12, "nama", "Switch Baru",
                     "ip_address", "192.168.56.150", "aktif", 0)));

        c.setujui(3, peta("nama", "Switch Baru"), req);

        verify(audit).logRequest(any(), any(), contains("192.168.56.150"), eq(true), any());
    }

    @Test
    void persetujuanGandaDitolakDanDiauditSebagaiGAGAL() {
        when(api.postPenemuanSetujui(anyInt(), any())).thenReturn(ResponseEntity.badRequest()
                .body(peta("detail", "temuan 3 sudah jadi device #12")));

        ResponseEntity<Object> hasil = c.setujui(3, peta("nama", "Dua kali"), req);

        assertEquals(HttpStatus.BAD_REQUEST, hasil.getStatusCode());
        verify(audit).logRequest(eq(AuditService.PENEMUAN_SETUJUI), eq("3"),
                contains("sudah jadi device"), eq(false), any());
    }

    // -----------------------------------------------------------------------
    // 4. Pengabaian
    // -----------------------------------------------------------------------
    @Test
    void pengabaianDiaudit() {
        when(api.postPenemuanAbaikan(anyInt())).thenReturn(ResponseEntity.ok(
                peta("id", 5, "ip_address", "192.168.56.99", "status", "diabaikan")));

        c.abaikan(5, req);

        verify(audit).logRequest(eq(AuditService.PENEMUAN_ABAIKAN), eq("5"),
                contains("192.168.56.99"), eq(true), any());
    }

    @Test
    void pengabaianYangDitolakDiauditSebagaiGAGAL() {
        when(api.postPenemuanAbaikan(anyInt())).thenReturn(ResponseEntity.badRequest()
                .body(peta("detail", "temuan 5 sudah jadi device #12")));

        c.abaikan(5, req);

        verify(audit).logRequest(eq(AuditService.PENEMUAN_ABAIKAN), eq("5"),
                contains("DITOLAK"), eq(false), any());
    }

    // 5. An unexpected response body must not fail the request.
    @Test
    void badanBalasanKosongTidakMeledak() {
        // An audit row reading "?" is better than an action aborted because its record was hard to write; the browser still gets the original body.
        when(api.postPenemuanSetujui(anyInt(), any()))
                .thenReturn(ResponseEntity.ok(null));

        ResponseEntity<Object> hasil = c.setujui(3, peta("nama", "X"), req);

        assertEquals(HttpStatus.OK, hasil.getStatusCode());
        verify(audit).logRequest(eq(AuditService.PENEMUAN_SETUJUI), eq("3"),
                contains("?"), eq(true), any());
    }

    // -----------------------------------------------------------------------
    // 6. Membuka halamannya ikut diaudit
    // -----------------------------------------------------------------------
    @Test
    void membukaHalamanDiauditDanMengembalikanTemplatnya() {
        assertEquals("konfig_penemuan", c.beranda(null, req));
        verify(audit).logRequest(eq(AuditService.VIEW_PENEMUAN), eq(null),
                any(), eq(true), any());
    }
}
