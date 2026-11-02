package id.bsp.frontend.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.ldap.DefaultSpringSecurityContextSource;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.ProviderManager;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.ldap.authentication.BindAuthenticator;
import org.springframework.security.ldap.authentication.LdapAuthenticationProvider;
import org.springframework.security.ldap.userdetails.DefaultLdapAuthoritiesPopulator;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

/**
 * Builds the authentication path: LDAP if configured, MySQL otherwise. With `nsm.ldap.url`
 * empty the behavior is exactly the MySQL-only default. Roles come from LDAP groups
 * (cn=nsm-admin -> ROLE_ADMIN, cn=nsm-viewer -> ROLE_USER, other groups ignored); users
 * without an NSM group get no role and are rejected, since a shared directory does not imply
 * shared access.
 */
@Configuration
public class LdapConfig {

    /**
     * LDAP group to application role map. A closed list on purpose, so a new directory group
     * cannot silently create a new NSM role.
     */
    static final java.util.Map<String, String> PETA_PERAN = java.util.Map.of(
            "ROLE_NSM-ADMIN", "ROLE_ADMIN",
            "ROLE_NSM-VIEWER", "ROLE_USER");

    static Collection<GrantedAuthority> petakan(Collection<? extends GrantedAuthority> asli) {
        List<GrantedAuthority> hasil = new ArrayList<>();
        for (GrantedAuthority g : asli) {
            String peran = PETA_PERAN.get(g.getAuthority().toUpperCase());
            if (peran != null && hasil.stream().noneMatch(x -> x.getAuthority().equals(peran))) {
                hasil.add(new SimpleGrantedAuthority(peran));
            }
        }

        // No NSM role means not an NSM user: reject instead of letting them in with no authorities.
        // A successful bind alone must not imply the right to use this application.
        if (hasil.isEmpty()) {
            throw new org.springframework.security.authentication.BadCredentialsException(
                    "Akun ini ada di direktori tetapi tidak punya grup NSM "
                    + "(nsm-admin / nsm-viewer), jadi tidak berhak memakai NSM.");
        }
        return hasil;
    }

    /**
     * The uid used to look up groups, taken from the found entry rather than from what was typed.
     * Groups are `posixGroup` with plain-uid `memberUid`; when login by email is enabled, the typed
     * name differs from the uid and the group filter `(memberUid={1})` would match nothing,
     * leaving the user with zero roles.
     */
    static String uidUntukGrup(org.springframework.ldap.core.DirContextOperations entri,
                               String diketik) {
        if (entri != null) {
            String uid = entri.getStringAttribute("uid");
            if (uid != null && !uid.isBlank()) {
                return uid;
            }
        }
        return diketik;
    }

    /**
     * Wraps ProviderManager so it publishes authentication events. A hand-built `ProviderManager`
     * uses `NullEventPublisher`; without events, `LoginAttemptListener` never sees successes or
     * failures, so audit entries and automatic lockout silently stop working.
     */
    private static AuthenticationManager berpenerbit(
            ProviderManager pm, org.springframework.context.ApplicationEventPublisher terbit) {
        pm.setAuthenticationEventPublisher(
                new org.springframework.security.authentication.DefaultAuthenticationEventPublisher(terbit));
        return pm;
    }

    @Bean
    public AuthenticationManager authenticationManager(
            CustomUserDetailsService detail,
            PasswordEncoder sandi,
            id.bsp.frontend.repository.UserRepository users,
            id.bsp.frontend.service.AuditService audit,
            org.springframework.context.ApplicationEventPublisher terbit,
            @Value("${nsm.ldap.url:}") String url,
            @Value("${nsm.ldap.basis-user:ou=people}") String basisUser,
            @Value("${nsm.ldap.filter-user:(|(uid={0})(mail={0}))}") String filterUser,
            @Value("${nsm.ldap.basis-grup:ou=groups}") String basisGrup,
            @Value("${nsm.ldap.timeout-sambung-ms:5000}") int timeoutSambung,
            @Value("${nsm.ldap.timeout-baca-ms:15000}") int timeoutBaca) {

        DaoAuthenticationProvider mysql = new DaoAuthenticationProvider(detail);
        mysql.setPasswordEncoder(sandi);

        if (url == null || url.isBlank()) {
            return berpenerbit(new ProviderManager(mysql), terbit);
        }

        DefaultSpringSecurityContextSource sumber =
                new DefaultSpringSecurityContextSource(url);
        // Timeouts are mandatory: without them a dead LDAP hangs the login page until the OS TCP
        // timeout and the emergency path never gets a chance. The default is 15000 ms and configurable:
        // a full login (socket, StartTLS, bind, DN search, user bind) takes about 3 s over the slow WAN
        // link to the directory, so a short budget would misreport a slow directory as a dead one.
        java.util.Map<String, Object> setelan = new java.util.HashMap<>();
        setelan.put("com.sun.jndi.ldap.connect.timeout", String.valueOf(timeoutSambung));
        setelan.put("com.sun.jndi.ldap.read.timeout", String.valueOf(timeoutBaca));
        sumber.setBaseEnvironmentProperties(setelan);

        // StartTLS: passwords must not cross the network in plaintext. It uses the same port (389) as
        // plain LDAP, so no extra firewall rule is needed. The certificate comes from the lab's internal CA and is
        // verified against the Java trust store; there is no setting that skips verification.
        if (url.startsWith("ldap://")) {
            sumber.setAuthenticationStrategy(
                    new org.springframework.ldap.core.support
                            .DefaultTlsDirContextAuthenticationStrategy());
        }

        sumber.afterPropertiesSet();

        BindAuthenticator bind = new BindAuthenticator(sumber);
        // The user DN is searched, not built from a pattern, so login works by uid or by email.
        // `{0}` is filled through a parameterized JNDI search (never concatenated, to prevent LDAP
        // injection). If two entries match, the search fails on purpose rather than picking one.
        bind.setUserSearch(new org.springframework.security.ldap.search
                .FilterBasedLdapUserSearch(basisUser, filterUser, sumber));

        DefaultLdapAuthoritiesPopulator grup =
                new DefaultLdapAuthoritiesPopulator(sumber, basisGrup);
        grup.setGroupSearchFilter("(memberUid={1})");
        grup.setGroupRoleAttribute("cn");

        LdapAuthenticationProvider ldapProv = new LdapAuthenticationProvider(bind, grup) {
            @Override
            protected Collection<? extends GrantedAuthority> loadUserAuthorities(
                    org.springframework.ldap.core.DirContextOperations userData,
                    String username, String password) {
                return petakan(super.loadUserAuthorities(
                        userData, uidUntukGrup(userData, username), password));
            }
        };

        // The recorded name is always the uid, whatever was typed, so one person does not appear as
        // two actors in the audit log (and name-based access checks see a single form).
        org.springframework.security.ldap.userdetails.LdapUserDetailsMapper dasar =
                new org.springframework.security.ldap.userdetails.LdapUserDetailsMapper();
        ldapProv.setUserDetailsContextMapper(
                new org.springframework.security.ldap.userdetails.UserDetailsContextMapper() {
            @Override
            public org.springframework.security.core.userdetails.UserDetails mapUserFromContext(
                    org.springframework.ldap.core.DirContextOperations ctx, String username,
                    Collection<? extends GrantedAuthority> wewenang) {
                return dasar.mapUserFromContext(ctx, uidUntukGrup(ctx, username), wewenang);
            }

            @Override
            public void mapUserToContext(
                    org.springframework.security.core.userdetails.UserDetails user,
                    org.springframework.ldap.core.DirContextAdapter ctx) {
                dasar.mapUserToContext(user, ctx);
            }
        });

        AuthenticationProvider ldap = ldapProv;

        return berpenerbit(new ProviderManager(
                new LdapDenganDarurat(ldap, mysql, users, audit)), terbit);
    }
}
