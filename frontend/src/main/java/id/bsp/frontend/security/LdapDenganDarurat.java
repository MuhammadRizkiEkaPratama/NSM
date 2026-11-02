package id.bsp.frontend.security;

import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;

/**
 * LDAP authentication with an emergency fallback to MySQL when LDAP is down.
 * Not just two providers in sequence: `ProviderManager` moves on after any
 * `AuthenticationException`, including "wrong password", so a user whose password was changed
 * in LDAP would be retried against MySQL with the old one.
 *   LDAP says wrong password -> reject; MySQL is not touched.
 *   LDAP says correct        -> accept; roles come from LDAP.
 *   LDAP unreachable         -> only then the emergency path opens.
 * Unreachable is detected by `org.springframework.ldap.NamingException` subclasses, not
 * `BadCredentialsException`. Even then only accounts flagged `darurat` may log in, and every use
 * is logged prominently in the audit log.
 */
public class LdapDenganDarurat implements AuthenticationProvider {

    private final AuthenticationProvider ldap;
    private final AuthenticationProvider mysql;
    private final id.bsp.frontend.repository.UserRepository users;
    private final id.bsp.frontend.service.AuditService audit;

    public LdapDenganDarurat(AuthenticationProvider ldap,
                             AuthenticationProvider mysql,
                             id.bsp.frontend.repository.UserRepository users,
                             id.bsp.frontend.service.AuditService audit) {
        this.ldap = ldap;
        this.mysql = mysql;
        this.users = users;
        this.audit = audit;
    }

    /**
     * Whether this failure means "server unreachable". Checks the whole cause chain, because Spring
     * Security wraps connection failures in `InternalAuthenticationServiceException`.
     */
    static boolean karenaServerMati(Throwable t) {
        for (Throwable s = t; s != null; s = s.getCause()) {
            if (s instanceof org.springframework.ldap.CommunicationException
                    || s instanceof org.springframework.ldap.ServiceUnavailableException
                    || s instanceof java.net.ConnectException
                    || s instanceof java.net.SocketTimeoutException
                    || s instanceof java.net.UnknownHostException) {
                return true;
            }
            if (s.getCause() == s) {
                break;
            }
        }
        return false;
    }

    @Override
    public Authentication authenticate(Authentication auth) throws AuthenticationException {
        try {
            return ldap.authenticate(auth);
        } catch (AuthenticationException e) {
            if (!karenaServerMati(e)) {
                // LDAP answered and rejected: final. MySQL is deliberately not consulted.
                throw e;
            }
            return lewatJalurDarurat(auth, e);
        } catch (RuntimeException e) {
            if (!karenaServerMati(e)) {
                throw e;
            }
            return lewatJalurDarurat(auth, e);
        }
    }

    private Authentication lewatJalurDarurat(Authentication auth, Throwable sebab) {
        String nama = String.valueOf(auth.getName());

        boolean boleh = users.findByUsername(nama)
                .map(id.bsp.frontend.entity.User::isDarurat)
                .orElse(false);

        String ip = alamatDari(auth);

        if (!boleh) {
            // The message states the real situation; "wrong password" would make users change passwords while the identity server is down.
            audit.logAuth(nama, id.bsp.frontend.service.AuditService.LOGIN_DARURAT_DITOLAK,
                          nama, "LDAP tak terjangkau (" + ringkas(sebab)
                          + ") dan akun ini bukan akun darurat", ip, false);
            // A dedicated exception type, not BadCredentialsException (see LdapTakTerjangkauException);
            // otherwise this message never reaches the screen and the wrong-password counter rises.
            throw new LdapTakTerjangkauException(
                    "Server identitas (LDAP) tidak dapat dihubungi, dan akun ini "
                    + "bukan akun darurat. Hubungi administrator.");
        }

        Authentication hasil;
        try {
            hasil = mysql.authenticate(auth);
        } catch (AuthenticationException e) {
            // Failed emergency attempts are logged too: emergency accounts are rarely used, so a failed
            // attempt against one almost always means something.
            audit.logAuth(nama, id.bsp.frontend.service.AuditService.LOGIN_DARURAT_DITOLAK,
                          nama, "Akun darurat dicoba saat LDAP tak terjangkau ("
                          + ringkas(sebab) + "), tetapi kredensialnya ditolak MySQL",
                          ip, false);
            throw e;
        }

        // Logged prominently: emergency use should prompt the questions of why LDAP was down and for how long.
        audit.logAuth(nama, id.bsp.frontend.service.AuditService.LOGIN_DARURAT,
                      nama, "MASUK LEWAT JALUR DARURAT — LDAP tak terjangkau ("
                      + ringkas(sebab) + "). Login divalidasi terhadap MySQL.",
                      ip, true);
        return hasil;
    }

    /** Requester address, if Spring supplies it. May be null. */
    private static String alamatDari(Authentication auth) {
        Object d = auth.getDetails();
        if (d instanceof org.springframework.security.web.authentication.WebAuthenticationDetails w) {
            return w.getRemoteAddress();
        }
        return null;
    }

    private static String ringkas(Throwable t) {
        String p = t.getMessage();
        if (p == null) {
            p = t.getClass().getSimpleName();
        }
        return p.length() > 120 ? p.substring(0, 120) : p;
    }

    @Override
    public boolean supports(Class<?> authentication) {
        return ldap.supports(authentication);
    }
}
