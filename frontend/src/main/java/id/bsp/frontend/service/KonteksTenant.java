package id.bsp.frontend.service;

/**
 * Tenant for the HTTP request being served. It is a ThreadLocal and must be cleared in the
 * {@code finally} block of the filter that sets it ({@link #bersihkan()}): Tomcat reuses threads,
 * and a leftover value would leak one tenant's data to another user's request.
 */
public final class KonteksTenant {

    private static final ThreadLocal<Long> TENANT = new ThreadLocal<>();

    private KonteksTenant() {
    }

    public static void setel(Long tenantId) {
        TENANT.set(tenantId);
    }

    public static Long sekarang() {
        return TENANT.get();
    }

    public static void bersihkan() {
        TENANT.remove();
    }
}
