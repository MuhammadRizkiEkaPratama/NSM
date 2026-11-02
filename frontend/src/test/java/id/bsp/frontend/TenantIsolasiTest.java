package id.bsp.frontend;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.service.KonteksTenant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Java side of tenancy: tenant context and platform role. Guards two silent leaks: context left on a reused Tomcat thread carrying into the next user's request, and "ADMIN" being read as a cross-tenant platform admin (which would widen the rights of existing ADMIN accounts). No Spring context, so it runs with MySQL down. */
class TenantIsolasiTest {

    @AfterEach
    void bersihkan() {
        KonteksTenant.bersihkan();
    }

    @Test
    void bawaannyaTanpaKonteks() {
        // No context means no filtering (pre-tenant behavior). A default that filters to a specific tenant would be a leak.
        assertNull(KonteksTenant.sekarang());
    }

    @Test
    void setelDanBersihkan() {
        KonteksTenant.setel(7L);
        assertEquals(7L, KonteksTenant.sekarang());
        KonteksTenant.bersihkan();
        assertNull(KonteksTenant.sekarang(),
                "konteks yang tidak dibersihkan akan terbawa ke permintaan berikutnya");
    }

    @Test
    void konteksTIDAKBocorAntarUtas() throws Exception {
        // ThreadLocal guarantees this; the test fails if someone replaces it with a static field.
        KonteksTenant.setel(1L);

        AtomicReference<Long> dariUtasLain = new AtomicReference<>(-1L);
        CountDownLatch selesai = new CountDownLatch(1);
        Thread t = new Thread(() -> {
            dariUtasLain.set(KonteksTenant.sekarang());
            KonteksTenant.setel(2L);
            selesai.countDown();
        });
        t.start();
        assertTrue(selesai.await(5, TimeUnit.SECONDS), "utas kedua tidak selesai");
        t.join();

        assertNull(dariUtasLain.get(),
                "utas lain melihat konteks tenant 1 -- ini kebocoran antar-permintaan");
        assertEquals(1L, KonteksTenant.sekarang(),
                "utas ini ikut berubah saat utas lain menyetel tenantnya sendiri");
    }

    @Test
    void adminBiasaBUKANAdminPlatform() {
        User u = new User();
        u.setRole("ADMIN");
        assertFalse(u.isAdminPlatform(),
                "peran ADMIN lama tidak boleh mendadak berarti lintas-tenant");

        u.setRole("VIEWER");
        assertFalse(u.isAdminPlatform());
    }

    @Test
    void adminPlatformDikenali() {
        // Counterpart check: a class that always answers false would pass the test above and platform roles would never work.
        User u = new User();
        u.setRole(User.PERAN_PLATFORM);
        assertTrue(u.isAdminPlatform());

        // Letter case must not decide access rights.
        u.setRole("admin_platform");
        assertTrue(u.isAdminPlatform());
    }

    @Test
    void peranKosongTIDAKBerartiPlatform() {
        // A default that opens a right is a silent failure; an unset role must fall to the least privilege.
        User u = new User();
        assertFalse(u.isAdminPlatform(), "peran null tidak boleh berarti platform");
        u.setRole("");
        assertFalse(u.isAdminPlatform());
    }

    @Test
    void tenantIdTersimpanDiAkun() {
        User u = new User();
        assertNull(u.getTenantId(), "bawaannya belum ditetapkan");
        u.setTenantId(3L);
        assertEquals(3L, u.getTenantId());
    }
}
