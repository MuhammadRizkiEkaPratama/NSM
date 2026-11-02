package id.bsp.frontend.controller;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.BlockedIpRepository;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Tests for managing active accounts and their guards. The guard is the controller's refusal, not the hidden button. Worst cases: an admin revoking their own rights, and revoking the last active admin (recoverable only via direct SQL). */
class AdminControllerTest {

    private UserRepository repo;
    private AuditService audit;
    private AdminController c;
    private HttpServletRequest req;

    private static User user(long id, String nama, String role,
                             boolean enabled, boolean nonaktif) {
        User u = new User();
        u.setId(id);
        u.setUsername(nama);
        u.setRole(role);
        u.setEnabled(enabled);
        u.setNonaktif(nonaktif);
        return u;
    }

    private void masukSebagai(String nama) {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        nama, "x", AuthorityUtils.createAuthorityList("ROLE_ADMIN")));
    }

    @BeforeEach
    void siapkan() {
        repo = mock(UserRepository.class);
        audit = mock(AuditService.class);
        req = mock(HttpServletRequest.class);
        c = new AdminController(repo, mock(BlockedIpRepository.class), audit);
        masukSebagai("admin");
    }

    @AfterEach
    void bersihkan() {
        SecurityContextHolder.clearContext();
    }

    // Guard 1: no self-demotion.

    @Test
    void adminTidakBisaMencabutAksesnyaSendiri() {
        User aku = user(1, "admin", "ADMIN", true, false);
        when(repo.findById(1L)).thenReturn(Optional.of(aku));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(5L);

        String tujuan = c.setNonaktif(1L, true, req);

        assertTrue(tujuan.contains("galat=diri-sendiri"), "dapat: " + tujuan);
        verify(repo, never()).save(any());
        assertTrue(aku.isEnabled(), "akun sendiri tidak boleh ikut berubah");
    }

    @Test
    void adminTidakBisaMenurunkanRoleNyaSendiri() {
        User aku = user(1, "admin", "ADMIN", true, false);
        when(repo.findById(1L)).thenReturn(Optional.of(aku));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(5L);

        String tujuan = c.ubahRole(1L, "VIEWER", req);

        assertTrue(tujuan.contains("galat=diri-sendiri"), "dapat: " + tujuan);
        assertEquals("ADMIN", aku.getRole());
        verify(repo, never()).save(any());
    }

    @Test
    void adminTidakBisaMenghapusAkunnyaSendiri() {
        User aku = user(1, "admin", "ADMIN", true, false);
        when(repo.findById(1L)).thenReturn(Optional.of(aku));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(5L);

        String tujuan = c.hapus(1L, req);

        assertTrue(tujuan.contains("galat=diri-sendiri"), "dapat: " + tujuan);
        verify(repo, never()).deleteById(any());
    }

    // Guard 2: last active admin.

    @Test
    void adminAktifTerakhirTidakBisaDiturunkan() {
        User satusatunya = user(2, "budi", "ADMIN", true, false);
        when(repo.findById(2L)).thenReturn(Optional.of(satusatunya));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(1L);

        String tujuan = c.ubahRole(2L, "VIEWER", req);

        assertTrue(tujuan.contains("galat=admin-terakhir"), "dapat: " + tujuan);
        assertEquals("ADMIN", satusatunya.getRole());
        verify(repo, never()).save(any());
    }

    @Test
    void adminAktifTerakhirTidakBisaDihapus() {
        User satusatunya = user(2, "budi", "ADMIN", true, false);
        when(repo.findById(2L)).thenReturn(Optional.of(satusatunya));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(1L);

        assertTrue(c.hapus(2L, req).contains("galat=admin-terakhir"));
        verify(repo, never()).deleteById(any());
    }

    @Test
    void adminKeduaBolehDiturunkan() {
        User budi = user(2, "budi", "ADMIN", true, false);
        when(repo.findById(2L)).thenReturn(Optional.of(budi));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(2L);

        String tujuan = c.ubahRole(2L, "VIEWER", req);

        assertTrue(tujuan.contains("pesan=role-diubah"), "dapat: " + tujuan);
        assertEquals("VIEWER", budi.getRole());
        verify(repo).save(budi);
    }

    // Promotion is never guarded.

    @Test
    void menaikkanViewerJadiAdminSelaluBoleh() {
        // Promoting reduces nobody's access, so no guard applies, even with a single admin (the moment a second admin is most needed).
        User citra = user(3, "citra", "VIEWER", true, false);
        when(repo.findById(3L)).thenReturn(Optional.of(citra));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(1L);

        assertTrue(c.ubahRole(3L, "ADMIN", req).contains("pesan=role-diubah"));
        assertEquals("ADMIN", citra.getRole());
    }

    // ---- Alur normal pencabutan & pengembalian ----------------------------

    @Test
    void mencabutAksesMengunciTanpaMenghapus() {
        User dedi = user(4, "dedi", "VIEWER", true, false);
        when(repo.findById(4L)).thenReturn(Optional.of(dedi));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(2L);

        String tujuan = c.setNonaktif(4L, true, req);

        assertTrue(tujuan.contains("pesan=akses-dicabut"), "dapat: " + tujuan);
        assertFalse(dedi.isEnabled(), "tidak boleh bisa masuk lagi");
        assertTrue(dedi.isNonaktif(), "harus dibedakan dari akun yang menunggu");
        assertEquals("DINONAKTIFKAN", dedi.getKeadaan());
        verify(repo, never()).deleteById(any());
    }

    @Test
    void akunDicabutTidakIkutDaftarMenungguPersetujuan() {
        // This is why the `nonaktif` column exists: with only enabled=false, a removed account would reappear in the new-registrations list with an Approve button.
        User dedi = user(4, "dedi", "VIEWER", false, true);
        User baru = user(5, "eka", "VIEWER", false, false);

        assertEquals("DINONAKTIFKAN", dedi.getKeadaan());
        assertEquals("MENUNGGU", baru.getKeadaan());
        assertFalse(dedi.getKeadaan().equals(baru.getKeadaan()),
                "dua keadaan berbeda tidak boleh terbaca sama");
    }

    @Test
    void mengembalikanAksesMenghapusKuncianLama() {
        User dedi = user(4, "dedi", "VIEWER", false, true);
        dedi.setFailedAttempts(3);
        dedi.setLockLevel(2);
        dedi.setLockedUntil(java.time.LocalDateTime.now().plusHours(1));
        when(repo.findById(4L)).thenReturn(Optional.of(dedi));

        String tujuan = c.setNonaktif(4L, false, req);

        assertTrue(tujuan.contains("pesan=akses-dikembalikan"), "dapat: " + tujuan);
        assertTrue(dedi.isEnabled());
        assertFalse(dedi.isNonaktif());
        assertEquals(0, dedi.getFailedAttempts(), "hitungan gagal lama tidak boleh ikut hidup");
        assertEquals(0, dedi.getLockLevel());
        assertEquals(null, dedi.getLockedUntil());
    }

    // ---- Audit ------------------------------------------------------------

    @Test
    void percobaanYangDitolakTetapDicatatSebagaiGagal() {
        // Refused attempts must be audited too; otherwise an attempt to remove the last admin leaves no trace.
        User satusatunya = user(2, "budi", "ADMIN", true, false);
        when(repo.findById(2L)).thenReturn(Optional.of(satusatunya));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(1L);

        c.ubahRole(2L, "VIEWER", req);

        verify(audit).logRequest(eq(AuditService.UBAH_ROLE), eq("budi"),
                anyString(), eq(false), any());
    }

    @Test
    void penghapusanMencatatUsernameBukanId() {
        // The audit entry names the user, since the users row is gone afterwards.
        User dedi = user(4, "dedi", "VIEWER", true, false);
        when(repo.findById(4L)).thenReturn(Optional.of(dedi));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(2L);

        c.hapus(4L, req);

        verify(repo).deleteById(4L);
        verify(audit).logRequest(eq(AuditService.HAPUS_USER), eq("dedi"),
                anyString(), eq(true), any());
    }

    @Test
    void akunYangSudahTidakAdaDitolakDenganSopan() {
        when(repo.findById(99L)).thenReturn(Optional.empty());

        assertTrue(c.hapus(99L, req).contains("galat=tidak-ada"));
        assertTrue(c.ubahRole(99L, "ADMIN", req).contains("galat=tidak-ada"));
        assertTrue(c.setNonaktif(99L, true, req).contains("galat=tidak-ada"));
        verify(repo, never()).save(any());
        verify(audit, never()).logRequest(anyString(), anyString(), anyString(),
                anyBoolean(), any());
    }

    @Test
    void roleYangTidakDikenalJatuhKeViewer() {
        // The role value comes from a form and must not be trusted: storing "SUPERADMIN" would match no SecurityConfig rule.
        User citra = user(3, "citra", "ADMIN", true, false);
        when(repo.findById(3L)).thenReturn(Optional.of(citra));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(3L);

        c.ubahRole(3L, "SUPERADMIN", req);

        assertEquals("VIEWER", citra.getRole());
    }

    @Test
    void roleSamaTidakMenulisBarisAuditPalsu() {
        User citra = user(3, "citra", "VIEWER", true, false);
        when(repo.findById(3L)).thenReturn(Optional.of(citra));
        when(repo.countByRoleAndEnabledTrue("ADMIN")).thenReturn(3L);

        c.ubahRole(3L, "VIEWER", req);

        verify(repo, never()).save(any());
        verify(audit, times(0)).logRequest(eq(AuditService.UBAH_ROLE), anyString(),
                anyString(), anyBoolean(), any());
    }
}
