package id.bsp.frontend.security;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.InternalAuthenticationServiceException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Tests the LDAP emergency path, the most important check in NSM's security layer. A wrong password must not open the MySQL path, or disabling someone in LDAP would not revoke access. Covers: wrong password -> reject without touching MySQL; LDAP down -> emergency path only for accounts flagged as emergency; regular accounts get an honest message; every emergency use is audited; connection failures are recognized even when wrapped. */
class LdapDaruratTest {

    private Authentication token() {
        return new UsernamePasswordAuthenticationToken("rina", "rahasia");
    }

    private User akun(boolean darurat) {
        User u = new User();
        u.setUsername("rina");
        u.setDarurat(darurat);
        return u;
    }

    /** Most important: a wrong password must NOT open the MySQL path. */
    @Test
    void sandiSalahDitolakDanMysqlTidakDisentuh() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        // LDAP answers and rejects.
        when(ldap.authenticate(any())).thenThrow(new BadCredentialsException("sandi salah"));

        LdapDenganDarurat p = new LdapDenganDarurat(ldap, mysql, users, audit);

        assertThrows(BadCredentialsException.class, () -> p.authenticate(token()));

        // Core of the whole test.
        verify(mysql, never()).authenticate(any());
        verify(users, never()).findByUsername(anyString());
    }

    /** LDAP down + emergency-flagged account: allowed through MySQL. */
    @Test
    void ldapMatiDanAkunDaruratBolehMasuk() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        when(ldap.authenticate(any())).thenThrow(
                new InternalAuthenticationServiceException("gagal",
                        new org.springframework.ldap.CommunicationException(
                                new javax.naming.CommunicationException("connect timed out"))));
        when(users.findByUsername("rina")).thenReturn(Optional.of(akun(true)));

        Authentication hasil = new UsernamePasswordAuthenticationToken(
                "rina", null, List.of());
        when(mysql.authenticate(any())).thenReturn(hasil);

        LdapDenganDarurat p = new LdapDenganDarurat(ldap, mysql, users, audit);
        assertSame(hasil, p.authenticate(token()));

        verify(mysql).authenticate(any());
    }

    /** LDAP down + regular account: rejected even if the MySQL password is correct. */
    @Test
    void ldapMatiDanAkunBiasaTetapDitolak() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        when(ldap.authenticate(any())).thenThrow(
                new InternalAuthenticationServiceException("gagal",
                        new java.net.ConnectException("Connection refused")));
        when(users.findByUsername("rina")).thenReturn(Optional.of(akun(false)));

        LdapDenganDarurat p = new LdapDenganDarurat(ldap, mysql, users, audit);
        // The type is `LdapTakTerjangkauException`, not `BadCredentialsException`: otherwise SecurityConfig cannot tell it from a wrong password (the honest message never shows) and `LoginAttemptListener` counts it as a failed attempt, so an LDAP outage could lock innocent accounts.
        AuthenticationException e = assertThrows(LdapTakTerjangkauException.class,
                () -> p.authenticate(token()));

        // MySQL must not be tried at all for a regular account.
        verify(mysql, never()).authenticate(any());

        // The message must honestly state that the identity server is down; "wrong password" would send people changing passwords.
        assertTrue(e.getMessage().toLowerCase().contains("ldap"),
                "pesan harus menyebut LDAP: " + e.getMessage());
        assertFalse(e.getMessage().toLowerCase().contains("sandi salah"),
                "jangan menyalahkan sandinya: " + e.getMessage());

        // Must NOT extend `BadCredentialsException`: Spring's event mapping is by type, so inheriting would revive the failed-password counting.
        assertFalse(e instanceof BadCredentialsException,
                "jangan wariskan dari BadCredentialsException: penghitung "
                + "salah-sandi akan menyala lagi diam-diam");
    }

    /** Account absent from MySQL entirely, while LDAP is down. */
    @Test
    void ldapMatiDanAkunTidakAdaDitolak() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        when(ldap.authenticate(any())).thenThrow(
                new InternalAuthenticationServiceException("gagal",
                        new java.net.ConnectException("Connection refused")));
        when(users.findByUsername("rina")).thenReturn(Optional.empty());

        LdapDenganDarurat p = new LdapDenganDarurat(ldap, mysql, users, audit);
        // Nothing can check the password in that case, and it must be reported as "server unreachable", not "wrong password".
        assertThrows(LdapTakTerjangkauException.class, () -> p.authenticate(token()));
        verify(mysql, never()).authenticate(any());
    }

    /** Emergency path use must be audited. */
    @Test
    void jalurDaruratSelaluDicatatAudit() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        when(ldap.authenticate(any())).thenThrow(
                new InternalAuthenticationServiceException("gagal",
                        new java.net.ConnectException("Connection refused")));
        when(users.findByUsername("rina")).thenReturn(Optional.of(akun(true)));
        when(mysql.authenticate(any())).thenReturn(
                new UsernamePasswordAuthenticationToken("rina", null, List.of()));

        new LdapDenganDarurat(ldap, mysql, users, audit).authenticate(token());

        verify(audit).logAuth(eq("rina"), eq(AuditService.LOGIN_DARURAT),
                anyString(), anyString(), any(), eq(true));
    }

    /** Emergency path refusals are audited too (a different event). */
    @Test
    void penolakanJalurDaruratJugaDicatat() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        when(ldap.authenticate(any())).thenThrow(
                new InternalAuthenticationServiceException("gagal",
                        new java.net.ConnectException("Connection refused")));
        when(users.findByUsername("rina")).thenReturn(Optional.of(akun(false)));

        assertThrows(LdapTakTerjangkauException.class,
                () -> new LdapDenganDarurat(ldap, mysql, users, audit).authenticate(token()));

        verify(audit).logAuth(eq("rina"), eq(AuditService.LOGIN_DARURAT_DITOLAK),
                anyString(), anyString(), any(), eq(false));
    }

    /** An emergency account tried with a WRONG password must be audited, since failed attempts against rarely used accounts almost always matter. */
    @Test
    void akunDaruratGagalSandiJugaDicatat() {
        AuthenticationProvider ldap = mock(AuthenticationProvider.class);
        AuthenticationProvider mysql = mock(AuthenticationProvider.class);
        UserRepository users = mock(UserRepository.class);
        AuditService audit = mock(AuditService.class);

        when(ldap.authenticate(any())).thenThrow(
                new InternalAuthenticationServiceException("gagal",
                        new java.net.ConnectException("Connection refused")));
        when(users.findByUsername("rina")).thenReturn(Optional.of(akun(true)));
        when(mysql.authenticate(any()))
                .thenThrow(new BadCredentialsException("sandi salah"));

        assertThrows(BadCredentialsException.class,
                () -> new LdapDenganDarurat(ldap, mysql, users, audit).authenticate(token()));

        verify(audit).logAuth(eq("rina"), eq(AuditService.LOGIN_DARURAT_DITOLAK),
                anyString(), anyString(), any(), eq(false));
        // And must not be recorded as a success.
        verify(audit, never()).logAuth(anyString(), eq(AuditService.LOGIN_DARURAT),
                anyString(), anyString(), any(), eq(true));
    }

    /** Connection failures must be recognized when wrapped in several layers (`InternalAuthenticationServiceException`, spring-ldap, `javax.naming`); checking only the outermost type would never trigger the emergency path. */
    @Test
    void kegagalanKoneksiDikenaliWalauBerlapis() {
        Throwable dalam = new java.net.ConnectException("Connection refused");
        Throwable tengah = new org.springframework.ldap.CommunicationException(
                new javax.naming.CommunicationException("gagal"));
        Throwable luar = new InternalAuthenticationServiceException("bungkus",
                new RuntimeException("lapis lagi", tengah));

        assertTrue(LdapDenganDarurat.karenaServerMati(luar),
                "CommunicationException berlapis harus dikenali");
        assertTrue(LdapDenganDarurat.karenaServerMati(
                new InternalAuthenticationServiceException("x", dalam)),
                "ConnectException berlapis harus dikenali");
        assertTrue(LdapDenganDarurat.karenaServerMati(
                new InternalAuthenticationServiceException("x",
                        new java.net.SocketTimeoutException("timeout"))));

        // Non-connection failures must not be treated as connection failures, or a wrong password would open the emergency path.
        assertFalse(LdapDenganDarurat.karenaServerMati(
                new BadCredentialsException("sandi salah")));
        assertFalse(LdapDenganDarurat.karenaServerMati(
                new RuntimeException("galat biasa")));
    }

    /** A self-referencing cause chain must not hang. */
    @Test
    void rantaiSebabMelingkarTidakBikinMacet() {
        RuntimeException e = new RuntimeException("melingkar") {
            @Override
            public synchronized Throwable getCause() {
                return this;
            }
        };
        assertFalse(LdapDenganDarurat.karenaServerMati(e));
    }
}
