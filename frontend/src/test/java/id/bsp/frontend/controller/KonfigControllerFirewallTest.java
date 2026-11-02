package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import tools.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.security.Principal;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Tests for the firewall block/unblock endpoints, the only POST path in NSM that writes to real devices. ADMIN/CSRF guards are SecurityConfig rules and not tested here. Covers: the blocker's name comes from the session, not the request body (a client-supplied `oleh` could forge the trail), and allowlist refusals from Python are audited with ok=false and a specific note. */
class KonfigControllerFirewallTest {

    private NetmonApiClient api;
    private AuditService audit;
    private KonfigController c;
    private HttpServletRequest req;
    private Principal siapa;

    @BeforeEach
    void siapkan() {
        api = mock(NetmonApiClient.class);
        audit = mock(AuditService.class);
        req = mock(HttpServletRequest.class);
        c = new KonfigController(api, audit, new ObjectMapper());
        siapa = mock(Principal.class);
        when(siapa.getName()).thenReturn("rina");
    }

    private static Map<String, Object> badan(String ip) {
        Map<String, Object> m = new HashMap<>();
        m.put("ip", ip);
        m.put("device_id", 1);
        m.put("alasan", "uji");
        m.put("pola", "manual");
        return m;
    }

    // Blocker name comes from the session, not the request body.

    @Test
    void olehDiambilDariSesiBukanDariBadanPermintaan() {
        Map<String, Object> isi = badan("10.20.30.40");
        isi.put("oleh", "penyerang-memalsukan-nama");   // dipalsukan pengirim
        when(api.postFirewallBlokir(any())).thenReturn(Map.of("ok", true, "ban_id", 1));

        c.firewallBlokir(isi, req, siapa);

        assertEquals("rina", isi.get("oleh"),
                "controller wajib MENIMPA 'oleh' dari badan permintaan, bukan memercayainya");
        verify(api).postFirewallBlokir(argThatOlehSama("rina"));
    }

    @Test
    void tanpaSesiOlehJadiTandaTanyaBukanNull() {
        Map<String, Object> isi = badan("10.20.30.40");
        when(api.postFirewallBlokir(any())).thenReturn(Map.of("ok", true, "ban_id", 1));

        c.firewallBlokir(isi, req, null); // No Principal (impossible through Spring, but must not NPE).

        assertEquals("?", isi.get("oleh"));
    }

    @Test
    void bukaBlokirJugaMengambilOlehDariSesi() {
        Map<String, Object> isi = new HashMap<>();
        isi.put("ip", "10.20.30.40");
        isi.put("oleh", "penyerang-memalsukan-nama");
        when(api.postFirewallBukaBlokir(any())).thenReturn(Map.of("ok", true));

        c.firewallBukaBlokir(isi, req, siapa);

        assertEquals("rina", isi.get("oleh"));
    }

    private static Map<String, Object> argThatOlehSama(String nama) {
        return org.mockito.ArgumentMatchers.argThat(m -> nama.equals(m.get("oleh")));
    }

    // Delegation to Python, as is.

    @Test
    void blokirBerhasilDidelegasikanApaAdanyaKeApi() {
        Map<String, Object> isi = badan("10.20.30.40");
        Object hasilApi = Map.of("ok", true, "ban_id", 7, "kedaluwarsa", "2026-08-18T10:00:00");
        when(api.postFirewallBlokir(any())).thenReturn(hasilApi);

        Object hasil = c.firewallBlokir(isi, req, siapa);

        assertEquals(hasilApi, hasil, "Java tidak boleh menyimpulkan apa pun sendiri, cukup meneruskan");
    }

    @Test
    void bukaBlokirBerhasilDidelegasikanApaAdanyaKeApi() {
        Map<String, Object> isi = new HashMap<>();
        isi.put("ip", "10.20.30.40");
        Object hasilApi = Map.of("ok", true, "ban_id", 7);
        when(api.postFirewallBukaBlokir(any())).thenReturn(hasilApi);

        Object hasil = c.firewallBukaBlokir(isi, req, siapa);

        assertEquals(hasilApi, hasil);
    }

    // ---- Audit: blokir berhasil ---------------------------------------------

    @Test
    void blokirBerhasilDiauditOkTrue() {
        Map<String, Object> isi = badan("10.20.30.40");
        when(api.postFirewallBlokir(any())).thenReturn(Map.of("ok", true, "ban_id", 1));

        c.firewallBlokir(isi, req, siapa);

        verify(audit).logRequest(eq(AuditService.FIREWALL_BLOKIR), eq("10.20.30.40"),
                eq("blokir 10.20.30.40"), eq(true), eq(req));
    }


    @Test
    void blokirGagalTeknisDiauditOkFalseTanpaKeteranganAllowlist() {
        Map<String, Object> isi = badan("10.20.30.40");
        when(api.postFirewallBlokir(any()))
                .thenReturn(Map.of("ok", false, "error", "server menolak"));

        c.firewallBlokir(isi, req, siapa);

        verify(audit).logRequest(eq(AuditService.FIREWALL_BLOKIR), eq("10.20.30.40"),
                eq("blokir 10.20.30.40"), eq(false), eq(req));
    }

    // Audit: allowlist refusal, the most important case.

    @Test
    void blokirDitolakAllowlistDiauditOkFalseDenganKeteranganKhusus() {
        // Mirrors the `penjaga_aksi.DitolakPengaman` answer forwarded by FastAPI: {"ok": false, "ditolak": true, "pesan": "..."}.
        Map<String, Object> isi = badan("192.168.56.1"); // NSM's own address.
        when(api.postFirewallBlokir(any())).thenReturn(
                Map.of("ok", false, "ditolak", true,
                        "pesan", "192.168.56.1 ada di allowlist"));

        c.firewallBlokir(isi, req, siapa);

        verify(audit).logRequest(eq(AuditService.FIREWALL_BLOKIR), eq("192.168.56.1"),
                eq("blokir 192.168.56.1 (DITOLAK pengaman allowlist)"),
                eq(false), eq(req));
    }

    @Test
    void percobaanBlokirYangDitolakTetapDiauditBukanDilewati() {
        // Refused attempts must be audited, as in AdminControllerTest.
        Map<String, Object> isi = badan("192.168.56.1");
        when(api.postFirewallBlokir(any())).thenReturn(
                Map.of("ok", false, "ditolak", true, "pesan", "dilindungi"));

        c.firewallBlokir(isi, req, siapa);

        verify(audit).logRequest(any(), any(), any(), eq(false), any());
    }

    // Audit: unblock, including unusual response shapes.

    @Test
    void bukaBlokirBerhasilDiauditOkTrue() {
        Map<String, Object> isi = new HashMap<>();
        isi.put("ip", "10.20.30.40");
        when(api.postFirewallBukaBlokir(any())).thenReturn(Map.of("ok", true, "ban_id", 1));

        c.firewallBukaBlokir(isi, req, siapa);

        verify(audit).logRequest(eq(AuditService.FIREWALL_BUKA_BLOKIR), eq("10.20.30.40"),
                eq("buka blokir 10.20.30.40"), eq(true), eq(req));
    }

    @Test
    void bukaBlokirGagalDiauditOkFalse() {
        Map<String, Object> isi = new HashMap<>();
        isi.put("ip", "10.20.30.40");
        when(api.postFirewallBukaBlokir(any()))
                .thenReturn(Map.of("ok", false, "error", "gagal menghubungi perangkat"));

        c.firewallBukaBlokir(isi, req, siapa);

        verify(audit).logRequest(eq(AuditService.FIREWALL_BUKA_BLOKIR), eq("10.20.30.40"),
                eq("buka blokir 10.20.30.40"), eq(false), eq(req));
    }

    @Test
    void bukaBlokirIpTanpaBanAktifTetapOkTrueBukanGalat() {
        // `penjaga_aksi.unblock()` answers {"ok": true, "tidak_ada_ban": true} for an IP that is not blocked; that is not a failure.
        Map<String, Object> isi = new HashMap<>();
        isi.put("ip", "10.20.30.99");
        when(api.postFirewallBukaBlokir(any()))
                .thenReturn(Map.of("ok", true, "tidak_ada_ban", true));

        c.firewallBukaBlokir(isi, req, siapa);

        verify(audit).logRequest(eq(AuditService.FIREWALL_BUKA_BLOKIR), eq("10.20.30.99"),
                eq("buka blokir 10.20.30.99"), eq(true), eq(req));
    }

    @Test
    void bukaBlokirJawabanBukanMapTetapDiauditOkTrue() {
        // The `ok` expression is permissive on purpose: only an explicit ok=false downgrades the audit result, not a missing "ok" key.
        Map<String, Object> isi = new HashMap<>();
        isi.put("ip", "10.20.30.40");
        when(api.postFirewallBukaBlokir(any())).thenReturn("bukan-map-sama-sekali");

        c.firewallBukaBlokir(isi, req, siapa);

        verify(audit).logRequest(any(), any(), any(), eq(true), any());
    }
}
