package id.bsp.frontend.security;

import org.springframework.security.core.AuthenticationException;

/**
 * Login rejected because the identity server is unreachable, not because the credentials are
 * wrong. A separate type (not {@code BadCredentialsException}) so that {@code SecurityConfig}
 * can show the real reason instead of "Username atau password salah", and so that
 * {@code LoginAttemptListener} does not count it as a wrong password, which would lock innocent
 * accounts while LDAP is down. Not used for emergency-account attempts with a wrong password:
 * those really are checked and rejected, so they stay {@code BadCredentialsException}.
 */
public class LdapTakTerjangkauException extends AuthenticationException {

    public LdapTakTerjangkauException(String pesan) {
        super(pesan);
    }

    public LdapTakTerjangkauException(String pesan, Throwable sebab) {
        super(pesan, sebab);
    }
}
