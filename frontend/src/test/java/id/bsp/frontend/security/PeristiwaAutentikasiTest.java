package id.bsp.frontend.security;

import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.event.AuthenticationFailureBadCredentialsEvent;
import org.springframework.security.authentication.event.AuthenticationSuccessEvent;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Tests that the AuthenticationManager PUBLISHES authentication events. A hand-built `new ProviderManager(...)` uses a `NullEventPublisher`, so `LoginAttemptListener` receives nothing: no LOGIN_SUCCESS/LOGIN_FAILED in the audit, and failure counts never rise, so accounts are never locked. The second is the dangerous one because the login page still rejects wrong passwords as normal. */
class PeristiwaAutentikasiTest {

    /** Recording publisher, so the published events can be inspected. */
    private static class Perekam implements ApplicationEventPublisher {
        final List<Object> terbit = new ArrayList<>();

        @Override
        public void publishEvent(ApplicationEvent event) {
            terbit.add(event);
        }

        @Override
        public void publishEvent(Object event) {
            terbit.add(event);
        }

        boolean ada(Class<?> jenis) {
            return terbit.stream().anyMatch(jenis::isInstance);
        }
    }

    private AuthenticationManager buat(Perekam perekam, CustomUserDetailsService detail) {
        // LDAP is left empty on purpose: this tests the event publisher, and the no-LDAP branch also uses a hand-built ProviderManager that can forget the publisher the same way.
        PasswordEncoder sandi = new BCryptPasswordEncoder();
        // The last two numbers are the directory timeouts. They have no effect here since the LDAP URL is empty, but real-looking values keep the call representative if copied.
        return new LdapConfig().authenticationManager(
                detail, sandi,
                mock(UserRepository.class), mock(AuditService.class),
                perekam, "", "ou=people", "(|(uid={0})(mail={0}))", "ou=groups",
                5000, 15000);
    }

    private CustomUserDetailsService detailDengan(String username, String sandiPolos) {
        CustomUserDetailsService detail = mock(CustomUserDetailsService.class);
        UserDetails u = new User(username,
                new BCryptPasswordEncoder().encode(sandiPolos),
                List.of(new SimpleGrantedAuthority("ROLE_ADMIN")));
        when(detail.loadUserByUsername(username)).thenReturn(u);
        when(detail.loadUserByUsername("tidak-ada"))
                .thenThrow(new UsernameNotFoundException("tidak ada"));
        return detail;
    }

    /** Most important: without this event the failure count never rises and passwords can be tried without limit. */
    @Test
    void loginGagalMenerbitkanPeristiwaGagal() {
        Perekam perekam = new Perekam();
        AuthenticationManager m = buat(perekam, detailDengan("rina", "benar"));

        assertThrows(AuthenticationException.class, () ->
                m.authenticate(new UsernamePasswordAuthenticationToken("rina", "salah")));

        assertTrue(perekam.ada(AuthenticationFailureBadCredentialsEvent.class),
                "kegagalan login tidak diterbitkan: kunci otomatis dan audit "
                + "LOGIN_FAILED sama-sama tidak akan pernah jalan");
    }

    @Test
    void loginBerhasilMenerbitkanPeristiwaBerhasil() {
        Perekam perekam = new Perekam();
        AuthenticationManager m = buat(perekam, detailDengan("rina", "benar"));

        m.authenticate(new UsernamePasswordAuthenticationToken("rina", "benar"));

        assertTrue(perekam.ada(AuthenticationSuccessEvent.class),
                "keberhasilan login tidak diterbitkan: LOGIN_SUCCESS tidak "
                + "akan pernah tercatat, dan hitungan gagal tidak pernah "
                + "direset setelah login yang benar");
    }

    /** Repeated attempts must publish repeated events, not just once; otherwise the lockout threshold is never reached. */
    @Test
    void tiapPercobaanGagalMenerbitkanPeristiwaSendiri() {
        Perekam perekam = new Perekam();
        AuthenticationManager m = buat(perekam, detailDengan("rina", "benar"));

        for (int i = 0; i < 5; i++) {
            assertThrows(AuthenticationException.class, () ->
                    m.authenticate(new UsernamePasswordAuthenticationToken("rina", "salah")));
        }

        long n = perekam.terbit.stream()
                .filter(AuthenticationFailureBadCredentialsEvent.class::isInstance)
                .count();
        assertEquals(5, n, "lima percobaan gagal harus jadi lima peristiwa");
    }
}
